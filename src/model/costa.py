"""Costa aproximada del dominio y reglas de varamiento.

La línea de costa es una simplificación manual (decenas de vértices) de la Península
de Yucatán, Belice, Cozumel, Isla Mujeres y el occidente de Cuba. Es suficiente para
una malla de 0.16° (~17 km), pero NO resuelve bahías, lagunas ni cayos: es uno de
los límites documentados del prototipo.

Para que la prueba de tierra sea rápida con miles de partículas, los polígonos se
rasterizan una sola vez a una máscara de ~0.004° (~440 m).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from src.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, RADIO_TIERRA_M

# (lon, lat). Los polígonos que tocan el borde del dominio se cierran por fuera de él.
PENINSULA = [
    (-92.60, 18.52), (-92.20, 18.55), (-91.85, 18.64), (-91.50, 18.79), (-91.18, 18.97),
    (-90.95, 19.12), (-90.72, 19.36), (-90.70, 19.62), (-90.54, 19.84), (-90.48, 20.10),
    (-90.48, 20.45), (-90.43, 20.72), (-90.40, 20.86), (-90.33, 21.02), (-90.03, 21.17),
    (-89.66, 21.29), (-89.25, 21.34), (-88.89, 21.40), (-88.50, 21.48), (-88.23, 21.57),
    (-87.99, 21.61), (-87.68, 21.53), (-87.45, 21.48), (-87.32, 21.55), (-87.07, 21.60),
    (-86.98, 21.54), (-86.82, 21.42), (-86.80, 21.25), (-86.76, 21.17), (-86.74, 21.14),
    (-86.76, 21.08), (-86.78, 21.03), (-86.83, 20.93), (-86.87, 20.85), (-86.97, 20.72),
    (-87.07, 20.63), (-87.13, 20.57), (-87.23, 20.50), (-87.31, 20.40), (-87.37, 20.30),
    (-87.43, 20.21), (-87.46, 20.05), (-87.47, 19.90), (-87.47, 19.80), (-87.45, 19.58),
    (-87.43, 19.40), (-87.45, 19.31), (-87.52, 19.10), (-87.58, 18.95), (-87.71, 18.71),
    (-87.76, 18.50), (-87.83, 18.27), (-87.86, 18.15), (-87.96, 17.92), (-88.05, 17.75),
    (-88.18, 17.52), (-88.25, 17.25), (-88.30, 17.00), (-88.33, 16.70), (-92.60, 16.70),
]
COZUMEL = [
    (-86.73, 20.59), (-86.80, 20.61), (-86.90, 20.58), (-86.96, 20.52), (-87.00, 20.42),
    (-87.02, 20.33), (-86.99, 20.27), (-86.93, 20.28), (-86.84, 20.35), (-86.78, 20.45),
    (-86.74, 20.53),
]
ISLA_MUJERES = [(-86.755, 21.265), (-86.715, 21.205), (-86.730, 21.198), (-86.765, 21.255)]
CUBA = [
    (-84.95, 21.86), (-84.88, 21.93), (-84.70, 21.98), (-84.50, 22.06), (-84.42, 22.20),
    (-84.38, 22.33), (-84.22, 22.50), (-84.02, 22.64), (-83.80, 22.76), (-83.40, 22.95),
    (-83.40, 22.20), (-83.60, 22.20), (-84.00, 22.05), (-84.30, 21.95), (-84.51, 21.76),
    (-84.65, 21.80), (-84.85, 21.82),
]
POLIGONOS = {
    "peninsula": PENINSULA,
    "cozumel": COZUMEL,
    "isla_mujeres": ISLA_MUJERES,
    "cuba": CUBA,
}

# Tramos de costa para resumir arribos. "ancla" es donde la interfaz coloca la etiqueta
# (tierra adentro, para no tapar las partículas).
ZONAS = [
    {"id": "campeche", "nombre": "Campeche", "ancla": (-90.20, 19.60)},
    {"id": "norte_yucatan", "nombre": "Costa norte de Yucatán", "ancla": (-89.30, 21.12)},
    {"id": "holbox", "nombre": "Holbox – Cabo Catoche", "ancla": (-87.35, 21.33)},
    {"id": "costa_mujeres", "nombre": "Costa Mujeres – Isla Blanca", "ancla": (-87.00, 21.34)},
    {"id": "cancun", "nombre": "Cancún – Isla Mujeres", "ancla": (-87.00, 21.10)},
    {"id": "puerto_morelos", "nombre": "Puerto Morelos", "ancla": (-87.10, 20.86)},
    {"id": "playa_del_carmen", "nombre": "Playa del Carmen", "ancla": (-87.32, 20.66)},
    {"id": "cozumel", "nombre": "Cozumel", "ancla": (-86.89, 20.43)},
    {"id": "akumal", "nombre": "Puerto Aventuras – Akumal", "ancla": (-87.52, 20.42)},
    {"id": "tulum", "nombre": "Tulum", "ancla": (-87.66, 20.20)},
    {"id": "sian_kaan", "nombre": "Sian Ka'an", "ancla": (-87.76, 19.65)},
    {"id": "mahahual", "nombre": "Mahahual (Costa Maya)", "ancla": (-87.96, 18.85)},
    {"id": "xcalak", "nombre": "Xcalak", "ancla": (-88.06, 18.36)},
    {"id": "belice", "nombre": "Belice", "ancla": (-88.48, 17.70)},
    {"id": "cuba", "nombre": "Cuba (occidente)", "ancla": (-84.15, 22.35)},
]
NOMBRE_ZONA = {z["id"]: z["nombre"] for z in ZONAS}

RESOLUCION_MASCARA = 0.004


def _arreglo(poligono) -> np.ndarray:
    return np.asarray(poligono, dtype=float)


@dataclass(frozen=True)
class MascaraTierra:
    lon0: float
    lat0: float
    paso: float
    tierra: np.ndarray  # bool [nlat, nlon]
    poligono_id: np.ndarray  # int8 [nlat, nlon]: índice en POLIGONOS o -1

    def indices(self, lon, lat):
        i = np.floor((np.asarray(lat) - self.lat0) / self.paso).astype(np.int64)
        j = np.floor((np.asarray(lon) - self.lon0) / self.paso).astype(np.int64)
        dentro = (i >= 0) & (i < self.tierra.shape[0]) & (j >= 0) & (j < self.tierra.shape[1])
        return np.clip(i, 0, self.tierra.shape[0] - 1), np.clip(j, 0, self.tierra.shape[1] - 1), dentro

    def en_tierra(self, lon, lat) -> np.ndarray:
        i, j, dentro = self.indices(lon, lat)
        return self.tierra[i, j] & dentro

    def poligono(self, lon, lat) -> np.ndarray:
        i, j, dentro = self.indices(lon, lat)
        return np.where(dentro, self.poligono_id[i, j], -1)


def _rasterizar(paso: float) -> MascaraTierra:
    """Rellena los polígonos por líneas de barrido (regla par-impar)."""
    lon0, lat0 = LON_MIN - 0.2, LAT_MIN - 0.2
    nlon = int(np.ceil((LON_MAX + 0.2 - lon0) / paso))
    nlat = int(np.ceil((LAT_MAX + 0.2 - lat0) / paso))
    xc = lon0 + (np.arange(nlon) + 0.5) * paso
    tierra = np.zeros((nlat, nlon), dtype=bool)
    ids = np.full((nlat, nlon), -1, dtype=np.int8)
    for k, poligono in enumerate(POLIGONOS.values()):
        p = _arreglo(poligono)
        x1, y1 = p[:, 0], p[:, 1]
        x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        for i in range(nlat):
            y = lat0 + (i + 0.5) * paso
            cruza = (y1 > y) != (y2 > y)
            if not cruza.any():
                continue
            xs = np.sort(x1[cruza] + (y - y1[cruza]) * (x2[cruza] - x1[cruza]) / (y2[cruza] - y1[cruza]))
            fila = np.zeros(nlon, dtype=bool)
            for a, b in zip(xs[0::2], xs[1::2]):
                fila |= (xc >= a) & (xc < b)
            tierra[i] |= fila
            ids[i][fila] = k
    return MascaraTierra(lon0, lat0, paso, tierra, ids)


@lru_cache(maxsize=1)
def mascara() -> MascaraTierra:
    return _rasterizar(RESOLUCION_MASCARA)


def en_tierra(lon, lat) -> np.ndarray:
    return mascara().en_tierra(lon, lat)


def _distancias_por_poligono_km(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Matriz [n, P] con la distancia (km) de cada punto a cada polígono de costa."""
    km_por_grado = np.pi * RADIO_TIERRA_M / 180.0 / 1000.0
    coslat = np.cos(np.radians(lat))[:, None]
    columnas = []
    for poligono in POLIGONOS.values():
        a = _arreglo(poligono)
        b = np.roll(a, -1, axis=0)
        ax = (a[None, :, 0] - lon[:, None]) * coslat
        ay = a[None, :, 1] - lat[:, None]
        dx = (b[None, :, 0] - a[None, :, 0]) * coslat
        dy = np.broadcast_to(b[None, :, 1] - a[None, :, 1], ax.shape)
        t = np.clip(-(ax * dx + ay * dy) / np.maximum(dx * dx + dy * dy, 1e-12), 0.0, 1.0)
        columnas.append(np.hypot(ax + t * dx, ay + t * dy).min(axis=1) * km_por_grado)
    return np.stack(columnas, axis=1)


def distancia_costa_km(lon, lat) -> np.ndarray:
    """Distancia (km) de cada punto al segmento de costa más cercano (proyección local)."""
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    d = _distancias_por_poligono_km(lon, lat).min(axis=1)
    d[en_tierra(lon, lat)] = 0.0
    return d


def zona_costera(lon, lat) -> np.ndarray:
    """Asigna cada punto (normalmente una partícula varada) a un tramo de costa de ZONAS."""
    x = np.atleast_1d(np.asarray(lon, dtype=float))
    y = np.atleast_1d(np.asarray(lat, dtype=float))
    if x.size == 0:
        return np.empty(0, dtype=object)
    nombres = np.array(list(POLIGONOS))
    cercano = nombres[_distancias_por_poligono_km(x, y).argmin(axis=1)]
    condiciones = [
        cercano == "cozumel",
        cercano == "cuba",
        cercano == "isla_mujeres",
        x < -90.3,
        (y >= 21.2) & (x < -87.55),
        (y >= 21.4) & (x < -86.95),
        y >= 21.2,
        y >= 21.0,
        y >= 20.75,
        y >= 20.55,
        y >= 20.30,
        y >= 20.05,
        y >= 19.20,
        y >= 18.50,
        y >= 18.10,
    ]
    opciones = [
        "cozumel", "cuba", "cancun", "campeche", "norte_yucatan", "holbox", "costa_mujeres",
        "cancun", "puerto_morelos", "playa_del_carmen", "akumal", "tulum", "sian_kaan",
        "mahahual", "xcalak",
    ]
    return np.select(condiciones, opciones, default="belice").astype(object)


def geojson() -> dict:
    """Costa del modelo y anclas de zonas, para dibujarlas en la interfaz."""
    features = []
    for nombre, poligono in POLIGONOS.items():
        anillo = [list(v) for v in poligono] + [list(poligono[0])]
        features.append({
            "type": "Feature",
            "properties": {"tipo": "costa", "nombre": nombre},
            "geometry": {"type": "Polygon", "coordinates": [anillo]},
        })
    for z in ZONAS:
        features.append({
            "type": "Feature",
            "properties": {"tipo": "zona", "id": z["id"], "nombre": z["nombre"]},
            "geometry": {"type": "Point", "coordinates": list(z["ancla"])},
        })
    return {"type": "FeatureCollection", "features": features}
