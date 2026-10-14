"""Interpolación de los campos ambientales en la posición y el tiempo de cada partícula."""
from __future__ import annotations

import numpy as np

from src.ingestion.lector import ConjuntoDatos


def _bilineal(campo: np.ndarray, fi: np.ndarray, fj: np.ndarray) -> np.ndarray:
    """Interpolación bilineal de `campo` [ny, nx] en índices fraccionarios (fila fi, columna fj).

    Los nodos sin dato (NaN, tierra en los datos de SEMAR) se descartan y los pesos de los
    demás se renormalizan. Si ninguno de los 4 vecinos tiene dato, el resultado es 0.
    """
    ny, nx = campo.shape
    i0 = np.clip(np.floor(fi).astype(np.int64), 0, ny - 2)
    j0 = np.clip(np.floor(fj).astype(np.int64), 0, nx - 2)
    wi = np.clip(fi - i0, 0.0, 1.0)
    wj = np.clip(fj - j0, 0.0, 1.0)
    suma = np.zeros(np.shape(fi))
    pesos = np.zeros(np.shape(fi))
    for i, j, w in ((i0, j0, (1 - wi) * (1 - wj)), (i0, j0 + 1, (1 - wi) * wj),
                    (i0 + 1, j0, wi * (1 - wj)), (i0 + 1, j0 + 1, wi * wj)):
        v = campo[i, j]
        valido = np.isfinite(v)
        suma += np.where(valido, w * np.where(valido, v, 0.0), 0.0)
        pesos += np.where(valido, w, 0.0)
    return np.where(pesos > 1e-12, suma / np.maximum(pesos, 1e-12), 0.0)


class CamposMalla:
    """Viento de SEMAR (1 o N tiempos) y corriente opcional sobre la malla de 0.16°.

    - Espacio: bilineal entre los 4 nodos que rodean a la partícula, ignorando nodos sin dato.
    - Tiempo: lineal entre los tiempos disponibles; con un solo tiempo el viento es
      estacionario (el caso de los datos actuales: solo t = 0). Fuera del rango se usa el
      tiempo más cercano. No hace falta cambiar el modelo cuando SEMAR entregue más horas.
    - Corriente: estacionaria; si el conjunto no trae corrientes, u_c = 0.
    """

    def __init__(self, conjunto: ConjuntoDatos):
        self.lon0 = float(conjunto.lons[0])
        self.lat0 = float(conjunto.lats[0])
        self.dlon = float(conjunto.lons[1] - conjunto.lons[0])
        self.dlat = float(conjunto.lats[1] - conjunto.lats[0])
        self.viento_u = conjunto.viento_u.astype(np.float64)
        self.viento_v = conjunto.viento_v.astype(np.float64)
        self.horas = conjunto.horas_viento.astype(np.float64)
        self.hay_corriente = conjunto.corriente_u is not None
        if self.hay_corriente:
            self.corriente_u = conjunto.corriente_u.astype(np.float64)
            self.corriente_v = conjunto.corriente_v.astype(np.float64)

    def _indices_tiempo(self, t_horas: float):
        if self.horas.size == 1 or t_horas <= self.horas[0]:
            return 0, 0, 0.0
        if t_horas >= self.horas[-1]:
            k = self.horas.size - 1
            return k, k, 0.0
        k1 = int(np.searchsorted(self.horas, t_horas))
        k0 = k1 - 1
        return k0, k1, float((t_horas - self.horas[k0]) / (self.horas[k1] - self.horas[k0]))

    def velocidades(self, lon, lat, t_horas: float):
        """Devuelve (uc, vc, uw, vw) en m/s: corriente y viento «hacia», en cada posición."""
        fi = (np.asarray(lat) - self.lat0) / self.dlat
        fj = (np.asarray(lon) - self.lon0) / self.dlon
        k0, k1, w = self._indices_tiempo(float(t_horas))
        uw = _bilineal(self.viento_u[k0], fi, fj)
        vw = _bilineal(self.viento_v[k0], fi, fj)
        if w > 0:
            uw = (1 - w) * uw + w * _bilineal(self.viento_u[k1], fi, fj)
            vw = (1 - w) * vw + w * _bilineal(self.viento_v[k1], fi, fj)
        if self.hay_corriente:
            uc = _bilineal(self.corriente_u, fi, fj)
            vc = _bilineal(self.corriente_v, fi, fj)
        else:
            uc = np.zeros(np.shape(fi))
            vc = np.zeros(np.shape(fi))
        return uc, vc, uw, vw


class CamposUniformes:
    """Corriente y viento constantes en espacio y tiempo (para pruebas analíticas)."""

    hay_corriente = True

    def __init__(self, uc=0.0, vc=0.0, uw=0.0, vw=0.0):
        self.valores = (float(uc), float(vc), float(uw), float(vw))
        self.hay_corriente = bool(uc or vc)

    def velocidades(self, lon, lat, t_horas: float):
        forma = np.shape(lon)
        return tuple(np.full(forma, v) for v in self.valores)
