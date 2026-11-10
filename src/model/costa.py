"""Costa del modelo: máscara de tierra de ~105 m derivada de OpenStreetMap, tramos y localidades.

La tierra del modelo es una máscara de 0.001° (1 bit por celda) construida por
scripts/construir_costa.py a partir de la línea de costa de OpenStreetMap, que es la misma
que dibuja el mapa base. La interfaz descarga esta misma máscara para dibujar la costa,
validar el punto de liberación y animar, de modo que «varado» en el modelo y «costa» en el
mapa son la misma cosa.

Límites: la máscara no resuelve canales ni bocas de menos de ~200 m (las lagunas que solo
comunican por ahí cuentan como tierra) y no distingue playa, manglar, arrecife ni muelle.
Fuera de la malla de la máscara todo cuenta como mar; el dominio del modelo queda dentro.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

DIR_DATOS_MODELO = Path(__file__).resolve().parent / "datos"
ARCHIVO_COSTA = DIR_DATOS_MODELO / "costa.npz"
ARCHIVO_PROCEDENCIA = DIR_DATOS_MODELO / "costa.json"
ARCHIVO_LOCALIDADES = DIR_DATOS_MODELO / "localidades.json"

# Malla de la máscara: el dominio del modelo (−92.08…−84.08, 16.92…23.00) más 0.12° de margen.
MALLA_COSTA = {"lon0": -92.20, "lat0": 16.80, "paso": 0.001, "nx": 8240, "ny": 6320}
# Máscara gruesa solo para dibujar la tierra fuera del dominio (Natural Earth 10 m).
CONTEXTO = {"lon0": -102.0, "lat0": 10.0, "paso": 0.01, "nx": 2800, "ny": 2000}

# Tramos de costa con nombre para la tabla de arribos. Los límites son una convención de
# PMS (no una división oficial): se evalúan en este orden y gana el primero que se cumple.
# «limites» es el texto que se muestra en la documentación y en el detalle de la interfaz.
ZONAS = [
    {"id": "cuba", "nombre": "Cuba (occidente)", "limites": "al este de 85.30° O"},
    {"id": "banco_campeche", "nombre": "Arrecifes del Banco de Campeche",
     "limites": "Alacranes y Cayo Arenas (al norte de 21.90° N y al oeste de 89.00° O) y Cayos Arcas"},
    {"id": "chinchorro", "nombre": "Banco Chinchorro", "limites": "18.30–18.85° N, al este de 87.52° O"},
    {"id": "cozumel", "nombre": "Cozumel", "limites": "20.24–20.62° N, al este de 87.06° O"},
    {"id": "isla_mujeres", "nombre": "Isla Mujeres", "limites": "21.19–21.28° N, al este de 86.765° O"},
    {"id": "contoy", "nombre": "Isla Contoy", "limites": "21.43–21.56° N, al este de 86.83° O"},
    {"id": "campeche", "nombre": "Campeche", "limites": "al oeste de 90.30° O y al sur de 20.60° N"},
    {"id": "yucatan", "nombre": "Costa de Yucatán", "limites": "al oeste de 87.53° O y al norte de 20.60° N"},
    {"id": "holbox", "nombre": "Holbox – Cabo Catoche", "limites": "al norte de 21.40° N, entre 87.53° y 86.95° O"},
    {"id": "costa_mujeres", "nombre": "Costa Mujeres – Isla Blanca", "limites": "al norte de 21.20° N"},
    {"id": "cancun", "nombre": "Cancún", "limites": "21.00–21.20° N"},
    {"id": "puerto_morelos", "nombre": "Puerto Morelos", "limites": "20.75–21.00° N"},
    {"id": "playa_del_carmen", "nombre": "Playa del Carmen", "limites": "20.55–20.75° N"},
    {"id": "akumal", "nombre": "Puerto Aventuras – Akumal", "limites": "20.30–20.55° N"},
    {"id": "tulum", "nombre": "Tulum", "limites": "20.05–20.30° N"},
    {"id": "sian_kaan", "nombre": "Sian Ka'an", "limites": "19.20–20.05° N"},
    {"id": "bahia_chetumal", "nombre": "Bahía de Chetumal", "limites": "18.17–19.00° N, al oeste de 87.86° O (ribera interior)"},
    {"id": "mahahual", "nombre": "Mahahual (Costa Maya)", "limites": "18.50–19.20° N"},
    {"id": "xcalak", "nombre": "Xcalak", "limites": "18.17–18.50° N"},
    {"id": "belice", "nombre": "Belice", "limites": "al sur de 18.17° N"},
]
NOMBRE_ZONA = {z["id"]: z["nombre"] for z in ZONAS}


def _reglas(x: np.ndarray, y: np.ndarray) -> list[np.ndarray]:
    """Una condición por tramo, en el orden de ZONAS (la última, Belice, es el resto)."""
    return [
        x > -85.30,
        ((y > 21.90) & (x < -89.00)) | ((x < -91.70) & (y > 19.90) & (y < 20.50)),
        (y > 18.30) & (y < 18.85) & (x > -87.52),
        (x > -87.06) & (y > 20.24) & (y < 20.62),
        (x > -86.765) & (y > 21.19) & (y < 21.28),
        (x > -86.83) & (y > 21.43) & (y < 21.56),
        (x < -90.30) & (y < 20.60),
        (x < -87.53) & (y >= 20.60),
        (y >= 21.40) & (x < -86.95),
        y >= 21.20,
        y >= 21.00,
        y >= 20.75,
        y >= 20.55,
        y >= 20.30,
        y >= 20.05,
        y >= 19.20,
        (y >= 18.17) & (y < 19.00) & (x < -87.86),
        y >= 18.50,
        y >= 18.17,
    ]


def zona_costera(lon, lat) -> np.ndarray:
    """Asigna cada punto (normalmente una partícula varada) a un tramo de costa de ZONAS."""
    x = np.atleast_1d(np.asarray(lon, dtype=float))
    y = np.atleast_1d(np.asarray(lat, dtype=float))
    if x.size == 0:
        return np.empty(0, dtype=object)
    ids = [z["id"] for z in ZONAS]
    return np.select(_reglas(x, y), ids[:-1], default=ids[-1]).astype(object)


@dataclass(frozen=True)
class MascaraTierra:
    """Máscara de tierra empaquetada: 1 bit por celda, filas de sur a norte, bit alto al oeste."""
    lon0: float
    lat0: float
    paso: float
    nx: int
    ny: int
    bits: np.ndarray  # uint8 [ny, nx / 8]

    def en_tierra(self, lon, lat) -> np.ndarray:
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        i = np.floor((lat - self.lat0) / self.paso).astype(np.int64)
        j = np.floor((lon - self.lon0) / self.paso).astype(np.int64)
        dentro = (i >= 0) & (i < self.ny) & (j >= 0) & (j < self.nx)
        i = np.clip(i, 0, self.ny - 1)
        j = np.clip(j, 0, self.nx - 1)
        return (((self.bits[i, j >> 3] >> (7 - (j & 7))) & 1) == 1) & dentro

    def a_bool(self) -> np.ndarray:
        """Máscara desempaquetada [ny, nx] (52 MB): solo para la validación y las pruebas."""
        return np.unpackbits(self.bits, axis=1, count=self.nx).astype(bool)

    def centros(self) -> tuple[np.ndarray, np.ndarray]:
        return (self.lon0 + (np.arange(self.nx) + 0.5) * self.paso,
                self.lat0 + (np.arange(self.ny) + 0.5) * self.paso)


@lru_cache(maxsize=1)
def _archivo() -> dict[str, np.ndarray]:
    if not ARCHIVO_COSTA.is_file():
        raise FileNotFoundError(
            f"Falta {ARCHIVO_COSTA}: genera la costa del modelo con  python scripts/construir_costa.py")
    with np.load(ARCHIVO_COSTA) as z:
        return {k: np.ascontiguousarray(z[k]) for k in ("tierra", "contexto")}


@lru_cache(maxsize=1)
def mascara() -> MascaraTierra:
    m = MALLA_COSTA
    bits = _archivo()["tierra"]
    if bits.shape != (m["ny"], m["nx"] // 8):
        raise ValueError(f"costa.npz no corresponde a la malla del código: {bits.shape}")
    return MascaraTierra(m["lon0"], m["lat0"], m["paso"], m["nx"], m["ny"], bits)


@lru_cache(maxsize=1)
def mascara_contexto() -> MascaraTierra:
    m = CONTEXTO
    return MascaraTierra(m["lon0"], m["lat0"], m["paso"], m["nx"], m["ny"], _archivo()["contexto"])


def en_tierra(lon, lat) -> np.ndarray:
    return mascara().en_tierra(lon, lat)


@lru_cache(maxsize=1)
def celdas_de_costa() -> tuple[np.ndarray, np.ndarray]:
    """(lon, lat) del centro de cada celda de tierra que toca el mar (vecindad de 4)."""
    m = mascara()
    t = m.a_bool()
    borde = np.zeros_like(t)
    borde[1:] |= t[1:] & ~t[:-1]
    borde[:-1] |= t[:-1] & ~t[1:]
    borde[:, 1:] |= t[:, 1:] & ~t[:, :-1]
    borde[:, :-1] |= t[:, :-1] & ~t[:, 1:]
    i, j = np.nonzero(borde)
    return m.lon0 + (j + 0.5) * m.paso, m.lat0 + (i + 0.5) * m.paso


@lru_cache(maxsize=1)
def _arbol_costa():
    from scipy.spatial import cKDTree   # solo la validación y las pruebas: no es dependencia de la app

    lon, lat = celdas_de_costa()
    return cKDTree(np.column_stack([lon * np.cos(np.radians(20.0)), lat]))


def distancia_costa_km(lon, lat) -> np.ndarray:
    """Distancia (km) de cada punto a la costa del modelo; 0 en tierra.

    Proyección local con cos(20°) (error < 2 % en el dominio). Necesita scipy: la usan la
    validación y las pruebas, no la aplicación.
    """
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    d, _ = _arbol_costa().query(np.column_stack([lon * np.cos(np.radians(20.0)), lat]))
    d = d * 111.195
    d[en_tierra(lon, lat)] = 0.0
    return d


@lru_cache(maxsize=1)
def procedencia() -> dict:
    return json.loads(ARCHIVO_PROCEDENCIA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def localidades() -> list[dict]:
    return json.loads(ARCHIVO_LOCALIDADES.read_text(encoding="utf-8"))


def descripcion() -> dict:
    """Lo que la interfaz necesita para usar la misma costa que el modelo."""
    p = procedencia()
    return {
        "malla": dict(MALLA_COSTA),
        "contexto": dict(CONTEXTO),
        "codificacion": "1 bit por celda, filas de sur a norte, bit más significativo al oeste; 1 = tierra",
        "mascara_url": "/api/costa/tierra.bin",
        "contexto_url": "/api/costa/contexto.bin",
        "sha256": p["costa"]["sha256_bits"],
        "zonas": [dict(z) for z in ZONAS],
        "fuentes": {
            "costa": {k: p["costa"][k] for k in ("fuente", "licencia", "atribucion", "datos_al")},
            "contexto": {k: p["contexto"][k] for k in ("fuente", "licencia", "atribucion")},
            "localidades": {k: p["localidades"][k] for k in ("fuente", "licencia", "atribucion", "datos_al", "criterio")},
        },
    }
