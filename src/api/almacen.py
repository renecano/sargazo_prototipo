"""Persistencia de simulaciones como archivos JSON en data/simulations/.

Cada archivo es autocontenido: id, fecha de ejecución, conjunto de entrada (con huella
SHA-256), parámetros, versión del modelo, semilla, bitácora y resultados. Las
posiciones de todas las partículas se guardan cuantizadas a 0.0002° (~22 m, muy por
debajo de la malla de 0.16°) en uint16 little-endian codificado en base64.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.config import LAT_MIN, LON_MIN, VERSION_APP
from src.model import costa
from src.model.simulacion import VARADA, Resultado

PATRON_ID = re.compile(r"^sim-\d{8}-\d{6}-[0-9a-f]{4}$")
ESCALA_POSICION = 5000.0  # unidades por grado → 0.0002°


def b64(arreglo: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arreglo).tobytes()).decode("ascii")


def codificar_posiciones(lon: np.ndarray, lat: np.ndarray) -> dict:
    qlon = np.round((lon - LON_MIN) * ESCALA_POSICION).astype("<u2")
    qlat = np.round((lat - LAT_MIN) * ESCALA_POSICION).astype("<u2")
    return {
        "codificacion": {
            "tipo": "uint16-le-base64",
            "forma": list(lon.shape),
            "lon": f"lon = {LON_MIN} + valor / {ESCALA_POSICION:g}",
            "lat": f"lat = {LAT_MIN} + valor / {ESCALA_POSICION:g}",
            "lon0": LON_MIN, "lat0": LAT_MIN, "escala": ESCALA_POSICION,
        },
        "lon": b64(qlon),
        "lat": b64(qlat),
    }


def decodificar_posiciones(datos: dict) -> tuple[np.ndarray, np.ndarray]:
    c = datos["codificacion"]
    forma = tuple(c["forma"])
    qlon = np.frombuffer(base64.b64decode(datos["lon"]), dtype="<u2").reshape(forma)
    qlat = np.frombuffer(base64.b64decode(datos["lat"]), dtype="<u2").reshape(forma)
    return c["lon0"] + qlon / c["escala"], c["lat0"] + qlat / c["escala"]


def nuevo_id(ahora: datetime) -> str:
    return f"sim-{ahora:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def zonas_por_particula(resultado: Resultado) -> np.ndarray:
    """Índice en costa.ZONAS del tramo donde varó cada partícula (255 = no varó)."""
    codigos = np.full(resultado.estado.shape, 255, dtype=np.uint8)
    varadas = resultado.estado == VARADA
    if varadas.any():
        indice = {z["id"]: k for k, z in enumerate(costa.ZONAS)}
        zonas = costa.zona_costera(resultado.lon[-1, varadas], resultado.lat[-1, varadas])
        codigos[varadas] = [indice[z] for z in zonas]
    return codigos


def armar_registro(resultado: Resultado, resumen: dict, conjunto: dict) -> dict:
    ahora = datetime.now(timezone.utc)
    series = resumen.pop("series")
    return {
        "id": nuevo_id(ahora),
        "creada_utc": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version_modelo": resultado.version_modelo,
        "version_app": VERSION_APP,
        "conjunto": conjunto,
        "parametros": resultado.parametros.a_dict(),
        "resumen": resumen,
        "resultados": {
            "horas": resultado.horas,
            "particulas": codificar_posiciones(resultado.lon, resultado.lat),
            "hora_varada": b64(resultado.hora_varada.astype("<i2")),
            "hora_fuera": b64(resultado.hora_fuera.astype("<i2")),
            "zona_varada": b64(zonas_por_particula(resultado)),
            "zonas": [{"id": z["id"], "nombre": z["nombre"], "ancla": list(z["ancla"])} for z in costa.ZONAS],
            "series": series,
        },
        "bitacora": resultado.bitacora,
        "duracion_s": round(resultado.duracion_s, 3),
    }


class Almacen:
    def __init__(self, directorio: Path):
        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _ruta(self, sim_id: str) -> Path:
        if not PATRON_ID.match(sim_id):
            raise KeyError(sim_id)
        return self.directorio / f"{sim_id}.json"

    def guardar(self, registro: dict) -> Path:
        ruta = self._ruta(registro["id"])
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(registro, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporal.replace(ruta)
        return ruta

    def cargar(self, sim_id: str) -> dict:
        ruta = self._ruta(sim_id)
        if not ruta.is_file():
            raise KeyError(sim_id)
        return json.loads(ruta.read_text(encoding="utf-8"))

    def listar(self) -> list[dict]:
        """Metadatos de todas las simulaciones, de la más reciente a la más antigua."""
        filas = []
        with self._lock:
            for ruta in self.directorio.glob("sim-*.json"):
                mtime = ruta.stat().st_mtime
                guardado = self._cache.get(ruta.name)
                if guardado and guardado[0] == mtime:
                    filas.append(guardado[1])
                    continue
                try:
                    r = json.loads(ruta.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                arribos = r["resumen"].get("arribos", [])
                meta = {
                    "id": r["id"],
                    "creada_utc": r["creada_utc"],
                    "version_modelo": r["version_modelo"],
                    "conjunto": r["conjunto"]["id"],
                    "sintetico": r["conjunto"].get("sintetico", False),
                    "parametros": r["parametros"],
                    "varadas_pct": r["resumen"]["varadas_pct"],
                    "fuera_pct": r["resumen"]["fuera_pct"],
                    "arribo_principal": arribos[0]["nombre"] if arribos else None,
                    "arribo_principal_prob": arribos[0]["probabilidad"] if arribos else None,
                }
                self._cache[ruta.name] = (mtime, meta)
                filas.append(meta)
        return sorted(filas, key=lambda m: m["creada_utc"] + m["id"], reverse=True)
