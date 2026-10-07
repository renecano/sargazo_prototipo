"""Conversiones de unidades y de convenciones de dirección.

Convenciones usadas en todo PMS:
- Meteorológica ("desde"): WindsfcDir es la dirección DESDE la que sopla el viento,
  en grados desde el norte geográfico, sentido horario. Viento del norte = 0°.
- Oceanográfica ("hacia"): un vector (u, v) apunta HACIA donde se desplaza el agua o
  la partícula; u positivo al este, v positivo al norte.
"""
from __future__ import annotations

import numpy as np

from src.config import RADIO_TIERRA_M

NUDO_A_MS = 0.514444  # 1 nudo = 0.514444 m/s


def nudos_a_ms(nudos):
    return np.asarray(nudos, dtype=float) * NUDO_A_MS


def ms_a_nudos(ms):
    return np.asarray(ms, dtype=float) / NUDO_A_MS


def desde_a_vector(velocidad, direccion_desde_grados):
    """Velocidad y dirección meteorológica "desde" → componentes (u, v) "hacia".

    Un viento del norte (0°) empuja hacia el sur: u = 0, v = -velocidad.
    """
    theta = np.radians(np.asarray(direccion_desde_grados, dtype=float))
    vel = np.asarray(velocidad, dtype=float)
    return -vel * np.sin(theta), -vel * np.cos(theta)


def vector_a_desde(u, v):
    """Componentes (u, v) "hacia" → (velocidad, dirección "desde" en [0, 360))."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    return np.hypot(u, v), np.mod(np.degrees(np.arctan2(-u, -v)), 360.0)


def vector_a_hacia(u, v):
    """Componentes (u, v) → (velocidad, rumbo "hacia" en [0, 360))."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    return np.hypot(u, v), np.mod(np.degrees(np.arctan2(u, v)), 360.0)


def diferencia_angular(a, b):
    """Diferencia angular mínima |a − b| en grados, en [0, 180]."""
    d = np.mod(np.asarray(a, dtype=float) - np.asarray(b, dtype=float) + 180.0, 360.0) - 180.0
    return np.abs(d)


def normalizar_longitud(lon):
    """Lleva longitudes en 0–360 al rango −180–180 (oeste negativo)."""
    return np.mod(np.asarray(lon, dtype=float) + 180.0, 360.0) - 180.0


def metros_a_grados(dx_m, dy_m, lat_grados):
    """Desplazamiento métrico (este, norte) → (Δlon, Δlat) en grados.

    La longitud se corrige por cos(lat): un grado de longitud mide menos hacia los polos.
    """
    dlat = np.degrees(np.asarray(dy_m, dtype=float) / RADIO_TIERRA_M)
    dlon = np.degrees(
        np.asarray(dx_m, dtype=float) / (RADIO_TIERRA_M * np.cos(np.radians(lat_grados)))
    )
    return dlon, dlat


def distancia_km(lon1, lat1, lon2, lat2):
    """Distancia de gran círculo (haversine) en km."""
    lon1, lat1, lon2, lat2 = (np.radians(np.asarray(a, dtype=float)) for a in (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * np.arcsin(np.sqrt(np.clip(a, 0, 1))) / 1000.0


def nombre_rumbo(grados) -> str:
    """Rumbo en grados → punto cardinal de 16 divisiones en español (N, NNE, NE…)."""
    puntos = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return puntos[int(np.floor((float(grados) % 360) / 22.5 + 0.5)) % 16]
