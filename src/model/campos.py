"""Interpolación de los campos ambientales en la posición y el tiempo de cada partícula."""
from __future__ import annotations

import numpy as np

from src.ingestion.lector import ConjuntoDatos


def _bilineal(campo: np.ndarray, fi: np.ndarray, fj: np.ndarray) -> np.ndarray:
    """Interpolación bilineal de `campo` [ny, nx] en índices fraccionarios (fila fi, columna fj)."""
    ny, nx = campo.shape
    i0 = np.clip(np.floor(fi).astype(np.int64), 0, ny - 2)
    j0 = np.clip(np.floor(fj).astype(np.int64), 0, nx - 2)
    wi = np.clip(fi - i0, 0.0, 1.0)
    wj = np.clip(fj - j0, 0.0, 1.0)
    return ((1 - wi) * (1 - wj) * campo[i0, j0] + (1 - wi) * wj * campo[i0, j0 + 1]
            + wi * (1 - wj) * campo[i0 + 1, j0] + wi * wj * campo[i0 + 1, j0 + 1])


class CamposMalla:
    """Viento horario y corriente (estacionaria) sobre la malla regular de 0.16°.

    - Espacio: bilineal entre los 4 nodos que rodean a la partícula.
    - Tiempo: lineal entre archivos horarios consecutivos; después de la última hora se
      mantiene el último campo.
    """

    def __init__(self, conjunto: ConjuntoDatos):
        self.lon0 = float(conjunto.lons[0])
        self.lat0 = float(conjunto.lats[0])
        self.dlon = float(conjunto.lons[1] - conjunto.lons[0])
        self.dlat = float(conjunto.lats[1] - conjunto.lats[0])
        self.viento_u = conjunto.viento_u.astype(np.float64)
        self.viento_v = conjunto.viento_v.astype(np.float64)
        self.corriente_u = conjunto.corriente_u.astype(np.float64)
        self.corriente_v = conjunto.corriente_v.astype(np.float64)
        self.horas = self.viento_u.shape[0]

    def velocidades(self, lon, lat, t_horas: float):
        """Devuelve (uc, vc, uw, vw) en m/s: corriente y viento "hacia", en cada posición."""
        fi = (np.asarray(lat) - self.lat0) / self.dlat
        fj = (np.asarray(lon) - self.lon0) / self.dlon
        uc = _bilineal(self.corriente_u, fi, fj)
        vc = _bilineal(self.corriente_v, fi, fj)
        t = min(max(float(t_horas), 0.0), self.horas - 1.0)
        k0 = int(np.floor(t))
        k1 = min(k0 + 1, self.horas - 1)
        w = t - k0
        uw = (1 - w) * _bilineal(self.viento_u[k0], fi, fj) + w * _bilineal(self.viento_u[k1], fi, fj)
        vw = (1 - w) * _bilineal(self.viento_v[k0], fi, fj) + w * _bilineal(self.viento_v[k1], fi, fj)
        return uc, vc, uw, vw


class CamposUniformes:
    """Corriente y viento constantes en espacio y tiempo (para pruebas analíticas)."""

    def __init__(self, uc=0.0, vc=0.0, uw=0.0, vw=0.0):
        self.valores = (float(uc), float(vc), float(uw), float(vw))

    def velocidades(self, lon, lat, t_horas: float):
        forma = np.shape(lon)
        return tuple(np.full(forma, v) for v in self.valores)
