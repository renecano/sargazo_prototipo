"""Servicios de la API: conjuntos de datos validados (en caché) y trabajos en segundo plano."""
from __future__ import annotations

import secrets
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from src.api.almacen import Almacen, armar_registro, b64
from src.ingestion.lector import ConjuntoDatos
from src.ingestion.validador import ReporteValidacion, validar_conjunto
from src.model.campos import CamposMalla
from src.model.metricas import resumir
from src.model.simulacion import Parametros, simular

PATRON_CONJUNTO = r"^[A-Za-z0-9_\-]{1,64}$"
NOMBRES_CONJUNTO = {
    "demo": "Demo sintético · 120 h",
    "demo_errores": "Demo con errores sembrados (prueba del validador)",
}


class ErrorConAccion(Exception):
    """Error que la interfaz muestra con su causa y la acción para corregirlo."""

    def __init__(self, causa: str, accion: str, archivo: str | None = None, codigo: int = 400):
        super().__init__(causa)
        self.causa, self.accion, self.archivo, self.codigo = causa, accion, archivo, codigo

    def a_dict(self) -> dict:
        return {"causa": self.causa, "accion": self.accion, "archivo": self.archivo}


class ServicioDatos:
    """Valida conjuntos bajo data/ y conserva en memoria el último resultado de cada uno."""

    def __init__(self, dir_datos: Path):
        self.dir_datos = Path(dir_datos)
        self._cache: dict[str, tuple[tuple, ReporteValidacion, ConjuntoDatos | None]] = {}
        self._lock = threading.Lock()

    def _huella_rapida(self, conjunto_id: str) -> tuple:
        d = self.dir_datos / conjunto_id
        if not d.is_dir():
            return ()
        archivos = sorted(list(d.glob("*.txt")) + list(d.glob("corrientes/*.txt")))
        return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in archivos)

    def listar(self) -> list[dict]:
        filas = []
        if self.dir_datos.is_dir():
            for d in sorted(p for p in self.dir_datos.iterdir() if p.is_dir() and p.name != "simulations"):
                n = len(list(d.glob("*.txt")))
                guardado = self._cache.get(d.name)
                filas.append({
                    "id": d.name,
                    "nombre": NOMBRES_CONJUNTO.get(d.name, d.name),
                    "archivos": n,
                    "validado": None if not guardado else guardado[1].valido,
                })
        orden = {"demo": 0, "demo_errores": 1}
        return sorted(filas, key=lambda f: (orden.get(f["id"], 2), f["id"]))

    def validar(self, conjunto_id: str, progreso=None, forzar: bool = False):
        huella = self._huella_rapida(conjunto_id)
        with self._lock:
            guardado = self._cache.get(conjunto_id)
            if guardado and guardado[0] == huella and not forzar:
                if progreso:
                    progreso(1, 1, "Resultado de validación en caché (archivos sin cambios)")
                return guardado[1], guardado[2]
        reporte, conjunto = validar_conjunto(self.dir_datos / conjunto_id, progreso)
        with self._lock:
            self._cache[conjunto_id] = (huella, reporte, conjunto)
        return reporte, conjunto

    def conjunto_valido(self, conjunto_id: str) -> ConjuntoDatos:
        reporte, conjunto = self.validar(conjunto_id)
        if conjunto is None:
            errores = reporte.errores
            primero = errores[0] if errores else None
            raise ErrorConAccion(
                causa=("El conjunto de datos no pasó la validación"
                       + (f": {primero.detalle}" if primero else ".")),
                accion=(primero.accion if primero and primero.accion
                        else "Revisa el reporte de validación y corrige los archivos."),
                archivo=primero.archivo if primero else None,
                codigo=409,
            )
        return conjunto

    def campos(self, conjunto_id: str) -> dict:
        """Campos para la capa animada y el hover, compactos (enteros escalados en base64)."""
        c = self.conjunto_valido(conjunto_id)
        ola = np.where(np.isfinite(c.ola_dir), np.round(c.ola_dir * 10), 65535).astype("<u2")
        return {
            "conjunto": c.resumen(),
            "malla": {
                "lon0": float(c.lons[0]), "dlon": float(c.lons[1] - c.lons[0]), "nx": int(c.lons.size),
                "lat0": float(c.lats[0]), "dlat": float(c.lats[1] - c.lats[0]), "ny": int(c.lats.size),
                "resolucion_grados": 0.16,
            },
            "horas": c.horas,
            "tiempos_utc": [t.strftime("%Y-%m-%dT%H:%MZ") for t in c.tiempos],
            "codificacion": {
                "viento": "int16-le, m/s × 100, forma [horas, ny, nx]",
                "corriente": "int16-le, m/s × 1000, forma [ny, nx] (estacionaria)",
                "ola_dir": "uint16-le, grados × 10, 65535 = sin dato (tierra)",
                "mar": "uint8, 1 = nodo de mar",
            },
            "viento_u": b64(np.round(c.viento_u * 100).astype("<i2")),
            "viento_v": b64(np.round(c.viento_v * 100).astype("<i2")),
            "corriente_u": b64(np.round(c.corriente_u * 1000).astype("<i2")),
            "corriente_v": b64(np.round(c.corriente_v * 1000).astype("<i2")),
            "ola_dir": b64(ola),
            "mar": b64(c.mar.astype(np.uint8)),
        }


def ejecutar_simulacion(datos: ServicioDatos, almacen: Almacen, conjunto_id: str, p: Parametros,
                        progreso=None) -> dict:
    conjunto = datos.conjunto_valido(conjunto_id)
    if p.horizonte_h > conjunto.horas:
        raise ErrorConAccion(f"El horizonte ({p.horizonte_h} h) excede las {conjunto.horas} h del conjunto.",
                             "Reduce el horizonte.", codigo=422)
    resultado = simular(CamposMalla(conjunto), p, progreso=progreso)
    registro = armar_registro(resultado, resumir(resultado), conjunto.resumen())
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
