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
from src.config import ARCHIVO_OLEAJE, COEF_PERIODO, COEF_STOKES, RESOLUCION_GRADOS
from src.ingestion.lector import ConjuntoDatos
from src.ingestion.validador import ReporteValidacion, validar_conjunto
from src.model.campos import NODOS_EXTRAPOLACION, R_MINIMA, CamposOleaje
from src.model import costa
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
        self._campos: tuple[str, CamposOleaje] | None = None
        self._lock = threading.Lock()

    def _huella_rapida(self) -> tuple:
        if not self.dir_semar.is_dir():
            return ()
        ruta = self.dir_semar / ARCHIVO_OLEAJE
        if not ruta.is_file():
            return ()
        return (ruta.name, ruta.stat().st_mtime_ns, ruta.stat().st_size)

    @property
    def disponibles(self) -> bool:
        return (self.dir_semar / ARCHIVO_OLEAJE).is_file()

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

    def campos_modelo(self) -> CamposOleaje:
        """Los campos de oleaje tal como los usa el modelo (con la franja costera extendida)."""
        c = self.conjunto_valido()
        with self._lock:
            if self._campos and self._campos[0] == c.huella_sha256:
                return self._campos[1]
        campos = CamposOleaje(c)
        with self._lock:
            self._campos = (c.huella_sha256, campos)
        return campos

    def ola_en(self, lon: float, lat: float, hora: float) -> dict:
        """Ola y deriva (γ = 1) que el modelo usa en un punto y una hora de pronóstico."""
        m = self.campos_modelo()
        x, y = np.array([lon]), np.array([lat])
        h, d = m.ola(x, y, hora)
        u, v = m.velocidades(x, y, hora)
        hay = bool(np.isfinite(h[0]) and np.isfinite(d[0]))
        rapidez = float(np.hypot(u[0], v[0]))
        return {
            "lon": lon, "lat": lat, "hora": hora, "en_tierra": bool(costa.en_tierra(x, y)[0]),
            "altura_m": float(h[0]) if hay else None,
            "direccion_desde": float(d[0]) if hay else None,
            "u_ms": float(u[0]), "v_ms": float(v[0]), "rapidez_ms": rapidez,
            "rumbo_hacia": float(np.degrees(np.arctan2(u[0], v[0])) % 360) if rapidez > 0 else None,
        }

    def campos(self) -> dict:
        """Altura y dirección de ola por bloque, tal como las usa el modelo, para el oleaje
        animado y el hover de la interfaz (enteros escalados en base64)."""
        c = self.conjunto_valido()
        m = self.campos_modelo()
        con_rumbo = np.isfinite(m.altura) & (np.hypot(m.seno, m.coseno) > R_MINIMA)
        direccion = np.mod(np.round(np.degrees(np.arctan2(m.seno, m.coseno)) * 10), 3600)

        return {
            "datos": c.resumen(),
            "malla": {
                "lon0": float(c.lons[0]), "dlon": float(c.lons[1] - c.lons[0]), "nx": int(c.lons.size),
                "lat0": float(c.lats[0]), "dlat": float(c.lats[1] - c.lats[0]), "ny": int(c.lats.size),
                "resolucion_grados": RESOLUCION_GRADOS,
            },
            "horas": [int(h) for h in c.horas],
            "modelo": {"coef_stokes": COEF_STOKES, "coef_periodo": COEF_PERIODO,
                       "nodos_extrapolacion": NODOS_EXTRAPOLACION},
            "codificacion": {
                "ola_dir": "uint16-le, grados «desde» × 10, 65535 = sin dato, forma [bloques, ny, nx]",
                "ola_altura": "uint16-le, m × 100, 65535 = sin dato, forma [bloques, ny, nx]",
                "extrapolado": "uint8, 1 = nodo sin dato en el archivo, extendido desde sus vecinos; forma [bloques, ny, nx]",
            },
            "ola_dir": b64(np.where(con_rumbo, direccion, 65535).astype("<u2")),
            "ola_altura": b64(np.where(con_rumbo, np.round(np.nan_to_num(m.altura) * 100), 65535).astype("<u2")),
            "extrapolado": b64(m.extrapolado.astype(np.uint8)),
        }


def ejecutar_simulacion(datos: ServicioDatos, almacen: Almacen, p: Parametros, progreso=None) -> dict:
    conjunto = datos.conjunto_valido()
    dominio = (float(conjunto.lons[0]), float(conjunto.lons[-1]), float(conjunto.lats[0]), float(conjunto.lats[-1]))
    resultado = simular(datos.campos_modelo(), p, dominio=dominio, progreso=progreso)
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
