"""Deriva de Stokes de la ola de viento interpolada en la posición y el tiempo de cada partícula."""
from __future__ import annotations

import numpy as np

from src.config import COEF_STOKES
from src.ingestion.lector import ConjuntoDatos


def magnitud_stokes(altura) -> np.ndarray:
    """|u_s| en m/s para γ = 1: 2π³·H² / (g·T³) con el período supuesto T = 4.0·√H.

    Se simplifica a COEF_STOKES·√H (≈ 0.0988·√H); H ≤ 0 o sin dato → 0.
    """
    h = np.nan_to_num(np.asarray(altura, dtype=float), nan=0.0)
    return COEF_STOKES * np.sqrt(np.maximum(h, 0.0))


def deriva_hacia(altura, direccion_desde):
    """(u, v) de la deriva de Stokes (γ = 1) HACIA donde viaja la ola: dirección desde + 180°."""
    mag = magnitud_stokes(altura)
    hacia = np.radians(np.asarray(direccion_desde, dtype=float) + 180.0)
    return mag * np.sin(hacia), mag * np.cos(hacia)


def _bilineal(campos: tuple[np.ndarray, ...], fi: np.ndarray, fj: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Interpolación bilineal de varios campos [ny, nx] que comparten máscara, en índices
    fraccionarios. Los nodos sin dato (NaN, tierra) se descartan y los pesos se
    renormalizan. Devuelve los campos interpolados y la suma de pesos válidos."""
    ny, nx = campos[0].shape
    i0 = np.clip(np.floor(fi).astype(np.int64), 0, ny - 2)
    j0 = np.clip(np.floor(fj).astype(np.int64), 0, nx - 2)
    wi = np.clip(fi - i0, 0.0, 1.0)
    wj = np.clip(fj - j0, 0.0, 1.0)
    sumas = [np.zeros(np.shape(fi)) for _ in campos]
    pesos = np.zeros(np.shape(fi))
    for i, j, w in ((i0, j0, (1 - wi) * (1 - wj)), (i0, j0 + 1, (1 - wi) * wj),
                    (i0 + 1, j0, wi * (1 - wj)), (i0 + 1, j0 + 1, wi * wj)):
        valido = np.isfinite(campos[0][i, j])
        wv = np.where(valido, w, 0.0)
        pesos += wv
        for s, c in zip(sumas, campos):
            s += wv * np.where(valido, c[i, j], 0.0)
    salida = tuple(np.where(pesos > 1e-12, s / np.maximum(pesos, 1e-12), np.nan) for s in sumas)
    return salida, pesos


class CamposOleaje:
    """Oleaje de SEMAR (altura y dirección «desde») sobre la malla nativa de 0.16°.

    - Espacio: la altura se interpola de forma bilineal ignorando los nodos sin dato; la
      dirección, por sus componentes seno y coseno (350° y 10° dan 0°, no 180°).
    - Tiempo: lineal entre bloques (cada 3 h). Fuera del rango se usa el bloque más cercano.
      Con los datos de muestra los 41 bloques son idénticos y el resultado no cambia, pero el
      modelo ya funciona cuando lleguen bloques distintos.
    - Devuelve la deriva de Stokes para γ = 1; la simulación la multiplica por γ.
    """

    def __init__(self, conjunto: ConjuntoDatos):
        self.lon0 = float(conjunto.lons[0])
        self.lat0 = float(conjunto.lats[0])
        self.dlon = float(conjunto.lons[1] - conjunto.lons[0])
        self.dlat = float(conjunto.lats[1] - conjunto.lats[0])
        self.horas = np.asarray(conjunto.horas, dtype=float) - float(conjunto.horas[0])
        self.altura = conjunto.altura.astype(np.float64)
        rad = np.radians(conjunto.direccion.astype(np.float64))
        self.seno, self.coseno = np.sin(rad), np.cos(rad)

    def _indices_tiempo(self, t_horas: float):
        if self.horas.size == 1 or t_horas <= self.horas[0]:
            return 0, 0, 0.0
        if t_horas >= self.horas[-1]:
            k = self.horas.size - 1
            return k, k, 0.0
        k1 = int(np.searchsorted(self.horas, t_horas))
        k0 = k1 - 1
        return k0, k1, float((t_horas - self.horas[k0]) / (self.horas[k1] - self.horas[k0]))

    def ola(self, lon, lat, t_horas: float):
        """(altura m, dirección «desde» °) interpoladas; NaN si no hay ningún vecino con dato."""
        fi = (np.asarray(lat, dtype=float) - self.lat0) / self.dlat
        fj = (np.asarray(lon, dtype=float) - self.lon0) / self.dlon
        k0, k1, w = self._indices_tiempo(float(t_horas))
        (h, s, c), _ = _bilineal((self.altura[k0], self.seno[k0], self.coseno[k0]), fi, fj)
        if w > 0:
            (h1, s1, c1), _ = _bilineal((self.altura[k1], self.seno[k1], self.coseno[k1]), fi, fj)
            h, s, c = (1 - w) * h + w * h1, (1 - w) * s + w * s1, (1 - w) * c + w * c1
        return h, np.mod(np.degrees(np.arctan2(s, c)), 360.0)

    def velocidades(self, lon, lat, t_horas: float):
        """(u, v) de la deriva de Stokes en m/s (γ = 1); 0 donde no hay ola (tierra)."""
        h, d = self.ola(lon, lat, t_horas)
        u, v = deriva_hacia(h, np.nan_to_num(d))
        return np.where(np.isfinite(h), u, 0.0), np.where(np.isfinite(h), v, 0.0)


class OleajeUniforme:
    """Ola constante en espacio y tiempo (para pruebas analíticas)."""

    def __init__(self, altura: float = 0.0, direccion_desde: float = 0.0):
        self.altura, self.direccion = float(altura), float(direccion_desde)

    def ola(self, lon, lat, t_horas: float):
        forma = np.shape(lon)
        return np.full(forma, self.altura), np.full(forma, self.direccion)

    def velocidades(self, lon, lat, t_horas: float):
        u, v = deriva_hacia(self.altura, self.direccion)
        forma = np.shape(lon)
        return np.full(forma, float(u)), np.full(forma, float(v))
