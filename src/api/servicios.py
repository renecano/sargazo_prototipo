"""Servicios de la API: datos de SEMAR validados (en caché) y trabajos en segundo plano."""
from __future__ import annotations

import secrets
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from src.api.almacen import Almacen, armar_registro, b64
from src.config import ARCHIVO_VIENTO, CARPETA_CORRIENTES, RESOLUCION_GRADOS
from src.ingestion.lector import ConjuntoDatos
from src.ingestion.validador import ReporteValidacion, validar_conjunto
from src.model.campos import CamposMalla
from src.model.metricas import resumir
from src.model.simulacion import Parametros, simular

class ErrorConAccion(Exception):
    """Error que la interfaz muestra con su causa y la acción para corregirlo."""

    def __init__(self, causa: str, accion: str, archivo: str | None = None, codigo: int = 400):
        super().__init__(causa)
        self.causa, self.accion, self.archivo, self.codigo = causa, accion, archivo, codigo

    def a_dict(self) -> dict:
        return {"causa": self.causa, "accion": self.accion, "archivo": self.archivo}


class ServicioDatos:
    """Valida los datos de SEMAR (una sola carpeta) y conserva en memoria el último resultado."""

    def __init__(self, dir_semar: Path):
        self.dir_semar = Path(dir_semar)
        self._cache: tuple[tuple, ReporteValidacion, ConjuntoDatos | None] | None = None
        self._lock = threading.Lock()

    def _huella_rapida(self) -> tuple:
        if not self.dir_semar.is_dir():
            return ()
        archivos = sorted(list(self.dir_semar.glob("*.txt")) + list(self.dir_semar.glob(f"{CARPETA_CORRIENTES}/*.txt")))
        return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in archivos)

    @property
    def disponibles(self) -> bool:
        return (self.dir_semar / ARCHIVO_VIENTO).is_file()

    def validar(self, progreso=None, forzar: bool = False):
        huella = self._huella_rapida()
        with self._lock:
            if self._cache and self._cache[0] == huella and not forzar:
                if progreso:
                    progreso(1, 1, "Resultado de validación en caché (archivos sin cambios)")
                return self._cache[1], self._cache[2]
        reporte, conjunto = validar_conjunto(self.dir_semar, progreso)
        with self._lock:
            self._cache = (huella, reporte, conjunto)
        return reporte, conjunto

    def conjunto_valido(self) -> ConjuntoDatos:
        reporte, conjunto = self.validar()
        if conjunto is None:
            errores = reporte.errores
            primero = errores[0] if errores else None
            raise ErrorConAccion(
                causa="Los datos de SEMAR no pasaron la validación" + (f": {primero.detalle}" if primero else "."),
                accion=(primero.accion if primero and primero.accion
                        else "Revisa el reporte de validación y corrige los archivos."),
                archivo=primero.archivo if primero else None,
                codigo=409,
            )
        return conjunto

    def campos(self) -> dict:
        """Viento y oleaje para las flechas y el hover, compactos (enteros escalados en base64)."""
        c = self.conjunto_valido()

        def entero(x, escala, tipo, vacio):
            return b64(np.where(np.isfinite(x), np.round(x * escala), vacio).astype(tipo))

        hay_ola = c.ola_altura is not None
        return {
            "datos": c.resumen(),
            "malla": {
                "lon0": float(c.lons[0]), "dlon": float(c.lons[1] - c.lons[0]), "nx": int(c.lons.size),
                "lat0": float(c.lats[0]), "dlat": float(c.lats[1] - c.lats[0]), "ny": int(c.lats.size),
                "resolucion_grados": RESOLUCION_GRADOS,
            },
            "tiempos_viento_utc": [t.strftime("%Y-%m-%dT%H:%MZ") for t in c.tiempos_viento],
            "ola_horas": [int(h) for h in c.ola_horas],
            "codificacion": {
                "viento": "int16-le, m/s × 100, −32768 = sin dato (tierra), forma [tiempos, ny, nx]",
                "ola_dir": "uint16-le, grados «desde» × 10, 65535 = sin dato, forma [horas, ny, nx]",
                "ola_altura": "uint16-le, m × 100, 65535 = sin dato, forma [horas, ny, nx]",
            },
            "viento_u": entero(c.viento_u, 100, "<i2", -32768),
            "viento_v": entero(c.viento_v, 100, "<i2", -32768),
            "ola_dir": entero(c.ola_dir, 10, "<u2", 65535) if hay_ola else None,
            "ola_altura": entero(c.ola_altura, 100, "<u2", 65535) if hay_ola else None,
        }


def ejecutar_simulacion(datos: ServicioDatos, almacen: Almacen, p: Parametros, progreso=None) -> dict:
    conjunto = datos.conjunto_valido()
    dominio = (float(conjunto.lons[0]), float(conjunto.lons[-1]), float(conjunto.lats[0]), float(conjunto.lats[-1]))
    resultado = simular(CamposMalla(conjunto), p, dominio=dominio, progreso=progreso)
    resumen = resumir(resultado)
    resumen["advertencias"] = conjunto.advertencias + resumen["advertencias"]
    registro = armar_registro(resultado, resumen, conjunto.resumen())
    almacen.guardar(registro)
    return registro


@dataclass
class Trabajo:
    id: str
    tipo: str
    estado: str = "en_curso"   # en_curso | terminado | error
    avance: int = 0
    total: int = 1
    mensaje: str = ""
    bitacora: list[str] = field(default_factory=list)
    resultado: dict | None = None
    error: dict | None = None

    def a_dict(self, incluir_resultado: bool = True) -> dict:
        return {
            "id": self.id, "tipo": self.tipo, "estado": self.estado, "avance": self.avance,
            "total": self.total, "mensaje": self.mensaje, "bitacora": self.bitacora[-40:],
            "resultado": self.resultado if incluir_resultado else None, "error": self.error,
        }


class GestorTrabajos:
    MAX_TRABAJOS = 50

    def __init__(self):
        self._trabajos: dict[str, Trabajo] = {}
        self._lock = threading.Lock()

    def lanzar(self, tipo: str, funcion: Callable[[Callable], dict]) -> Trabajo:
        trabajo = Trabajo(id=f"{tipo}-{secrets.token_hex(4)}", tipo=tipo)
        with self._lock:
            if len(self._trabajos) >= self.MAX_TRABAJOS:
                for viejo in list(self._trabajos)[: len(self._trabajos) - self.MAX_TRABAJOS + 1]:
                    del self._trabajos[viejo]
            self._trabajos[trabajo.id] = trabajo

        def progreso(k, n, mensaje):
            trabajo.avance, trabajo.total, trabajo.mensaje = k, n, mensaje

        def correr():
            try:
                trabajo.resultado = funcion(progreso)
                trabajo.estado = "terminado"
            except ErrorConAccion as e:
                trabajo.error, trabajo.estado = e.a_dict(), "error"
            except ValueError as e:
                trabajo.error = {"causa": str(e), "accion": "Corrige los parámetros e intenta de nuevo.", "archivo": None}
                trabajo.estado = "error"
            except Exception as e:  # noqa: BLE001 — se reporta a la interfaz y a la consola
                traceback.print_exc()
                trabajo.error = {"causa": f"Error interno: {e}", "accion": "Revisa la consola del servidor.", "archivo": None}
                trabajo.estado = "error"

        threading.Thread(target=correr, daemon=True, name=trabajo.id).start()
        return trabajo

    def obtener(self, trabajo_id: str) -> Trabajo:
        with self._lock:
            return self._trabajos[trabajo_id]
