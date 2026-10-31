"""Campos de velocidad para los experimentos de validación.

- CamposEncadenados: el producto pronostica 120 h con un dirmarea.txt; para llegar a +7 días
  se encadenan dos archivos en el formato de SEMAR (fecha base t y t + 5 días), cada uno
  leído con el validador y el modelo del producto (CamposOleaje). Ninguno se modifica.
- CamposVectoriales: corriente (SMOC) o viento (ERA5) como (u, v) en la malla de 0.16°,
  interpolados en espacio como el oleaje (bilineal, ignorando nodos sin dato) y linealmente
  en el tiempo.
- CamposSuma: suma ponderada de varios campos (E5: corriente + α·viento + ola).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from src.model.campos import _bilineal
from src.model.conversiones import desde_a_vector


class CamposEncadenados:
    """Varios campos con su hora de inicio (h desde el inicio del primero)."""

    def __init__(self, tramos: list[tuple[float, object]]):
        self.tramos = sorted(tramos, key=lambda t: t[0])

    def _tramo(self, t: float):
        elegido = self.tramos[0]
        for inicio, campos in self.tramos:
            if t >= inicio:
                elegido = (inicio, campos)
        return elegido

    def velocidades(self, lon, lat, t_horas: float):
        inicio, campos = self._tramo(float(t_horas))
        return campos.velocidades(lon, lat, float(t_horas) - inicio)

    def ola(self, lon, lat, t_horas: float):
        inicio, campos = self._tramo(float(t_horas))
        return campos.ola(lon, lat, float(t_horas) - inicio)


@dataclass
class CamposVectoriales:
    """(u, v) en m/s sobre una malla regular: arreglos [tiempo, lat, lon] (lat ascendente)."""
    lon0: float
    lat0: float
    dlon: float
    dlat: float
    horas: np.ndarray       # horas desde el inicio de los campos
    u: np.ndarray
    v: np.ndarray

    def velocidades(self, lon, lat, t_horas: float):
        fi = (np.asarray(lat, dtype=float) - self.lat0) / self.dlat
        fj = (np.asarray(lon, dtype=float) - self.lon0) / self.dlon
        t = float(t_horas)
        if t <= self.horas[0]:
            k0 = k1 = 0
            w = 0.0
        elif t >= self.horas[-1]:
            k0 = k1 = self.horas.size - 1
            w = 0.0
        else:
            k1 = int(np.searchsorted(self.horas, t))
            k0 = k1 - 1
            w = (t - self.horas[k0]) / (self.horas[k1] - self.horas[k0])
        (u, v), _ = _bilineal((self.u[k0], self.v[k0]), fi, fj)
        if w > 0:
            (u1, v1), _ = _bilineal((self.u[k1], self.v[k1]), fi, fj)
            u, v = (1 - w) * u + w * u1, (1 - w) * v + w * v1
        return np.nan_to_num(u), np.nan_to_num(v)


class CamposSuma:
    def __init__(self, componentes: list[tuple[float, object]]):
        self.componentes = componentes

    def velocidades(self, lon, lat, t_horas: float):
        u = np.zeros(np.shape(lon))
        v = np.zeros(np.shape(lon))
        for factor, campos in self.componentes:
            if factor == 0:
                continue
            cu, cv = campos.velocidades(lon, lat, t_horas)
            u += factor * cu
            v += factor * cv
        return u, v


def vectoriales_desde_serie(serie, ii, jj, paso: int, destino: np.ndarray, lons: np.ndarray, lats: np.ndarray,
                            inicio: datetime, horas: int, convencion: str) -> CamposVectoriales:
    """Convierte una serie de Open-Meteo (velocidad y dirección) a (u, v) horarios en la malla
    fina, desde `inicio` y durante `horas` + 1 horas.

    convencion: "hacia" (corriente: dirección a donde va) o "desde" (viento: de donde sopla).
    """
    from validacion.dirmarea import a_malla_fina
    vel_var, dir_var = list(serie.valores)[:2]
    us, vs = [], []
    for h in range(horas + 1):
        k = serie.indice_hora(inicio + timedelta(hours=h))
        vel, dire = serie.valores[vel_var][k], serie.valores[dir_var][k]
        if convencion == "hacia":
            rad = np.radians(dire)
            u, v = vel * np.sin(rad), vel * np.cos(rad)
        else:
            u, v = desde_a_vector(vel, dire)
        fu, fv = a_malla_fina(np.stack([u, v]), ii, jj, paso, destino)
        us.append(fu)
        vs.append(fv)
    return CamposVectoriales(float(lons[0]), float(lats[0]), float(lons[1] - lons[0]), float(lats[1] - lats[0]),
                             np.arange(horas + 1, dtype=float), np.array(us), np.array(vs))


def utc(fecha, hora: int = 0) -> datetime:
    return datetime(fecha.year, fecha.month, fecha.day, hora, tzinfo=timezone.utc)
