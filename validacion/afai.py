"""AFAI diario de USF desde NOAA AOML ERDDAP: descarga, lectura y detección de sargazo.

- Descarga: un archivo NetCDF por mes, solo del recuadro del modelo, guardado en la caché
  local data/validacion/afai/ (no se sube a git). Cada mes se guarda comprimido (.npz).
- Lectura: el NetCDF-3 que entrega ERDDAP se lee con scipy (sin dependencias de netCDF4).
- Detección (Wang & Hu, 2016): ΔAFAI = AFAI − fondo; el fondo es la mediana en una ventana de
  51 × 51 píxeles sin los candidatos (ΔAFAI preliminar > Ts); hay sargazo si ΔAFAI > T0.
  Diferencias con el artículo, documentadas en docs/validacion.md: no se ajusta la superficie
  polinómica de 4.º grado (el fondo sale de dos pasadas de mediana), la nube ya viene
  enmascarada por AOML (NaN) y no hay máscara de sombra de nube (no hay bandas de reflectancia).
"""
from __future__ import annotations

import calendar
import io
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy import ndimage
from scipy.io import netcdf_file

from validacion import config as cfg

EPOCA = datetime(1970, 1, 1, tzinfo=timezone.utc)


def url_afai(desde: date, hasta: date, dataset: str = cfg.DATASET_AFAI_1D, recuadro=cfg.RECUADRO,
             formato: str = "nc") -> str:
    """URL griddap de ERDDAP para AFAI[tiempo][lat][lon] en el recuadro y las fechas dadas."""
    lon_min, lon_max, lat_min, lat_max = recuadro
    return (f"{cfg.ERDDAP}/{dataset}.{formato}?{cfg.VARIABLE_AFAI}"
            f"%5B({desde.isoformat()}T12:00:00Z):1:({hasta.isoformat()}T12:00:00Z)%5D"
            f"%5B({lat_min}):1:({lat_max})%5D%5B({lon_min}):1:({lon_max})%5D")


def descargar(url: str, intentos: int = 4, espera_s: float = 20.0, tiempo_max_s: float = 600.0) -> bytes:
    """GET con reintentos; ERDDAP a veces corta descargas grandes."""
    ultimo = None
    for k in range(intentos):
        try:
            with urllib.request.urlopen(url, timeout=tiempo_max_s) as r:
                return r.read()
        except Exception as e:   # noqa: BLE001 — se reintenta y al final se reporta la causa
            ultimo = e
            time.sleep(espera_s * (k + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {ultimo}")


@dataclass
class Rejilla:
    """AFAI en [día, lat, lon] (lat ascendente); NaN = sin observación (nube, brillo solar, tierra)."""
    fechas: list[date]
    lons: np.ndarray
    lats: np.ndarray
    afai: np.ndarray

    def dia(self, fecha: date) -> np.ndarray | None:
        try:
            return self.afai[self.fechas.index(fecha)]
        except ValueError:
            return None


def leer_nc_erddap(contenido: bytes | Path) -> Rejilla:
    """Lee el NetCDF-3 de ERDDAP (variables time, latitude, longitude, AFAI)."""
    fuente = io.BytesIO(contenido) if isinstance(contenido, (bytes, bytearray)) else str(contenido)
    with netcdf_file(fuente, "r", mmap=False) as f:
        t = np.asarray(f.variables["time"].data, dtype=float).copy()
        lats = np.asarray(f.variables["latitude"].data, dtype=float).copy()
        lons = np.asarray(f.variables["longitude"].data, dtype=float).copy()
        a = np.asarray(f.variables[cfg.VARIABLE_AFAI].data, dtype=np.float32).copy()
        relleno = getattr(f.variables[cfg.VARIABLE_AFAI], "_FillValue", None)
    if relleno is not None and np.isfinite(relleno):
        a[a == np.float32(relleno)] = np.nan
    if a.ndim == 2:
        a = a[None]
    if lats[0] > lats[-1]:
        lats, a = lats[::-1], a[:, ::-1]
    fechas = [(EPOCA + timedelta(seconds=float(s))).date() for s in t]
    return Rejilla(fechas, lons, lats, a)


def _ruta_mes(anio: int, mes: int, cache: Path) -> Path:
    return cache / "afai" / f"afai_1d_{anio:04d}-{mes:02d}.npz"


def mes_afai(anio: int, mes: int, cache: Path = cfg.DIR_CACHE, registrar=print) -> Rejilla:
    """AFAI diario de un mes; usa la caché local o lo descarga una sola vez."""
    ruta = _ruta_mes(anio, mes, cache)
    if not ruta.is_file():
        desde = date(anio, mes, 1)
        # ERDDAP responde 404 si se piden días posteriores a la última imagen disponible.
        hasta = min(date(anio, mes, calendar.monthrange(anio, mes)[1]), cfg.BUSQUEDA_HASTA)
        t0 = time.perf_counter()
        rej = leer_nc_erddap(descargar(url_afai(desde, hasta)))
        # ERDDAP ajusta los extremos al tiempo disponible más cercano: se descartan los días
        # que no son del mes pedido (pasa cuando faltan imágenes al inicio o al final).
        dentro = [i for i, f in enumerate(rej.fechas) if f.year == anio and f.month == mes]
        rej = Rejilla([rej.fechas[i] for i in dentro], rej.lons, rej.lats, rej.afai[dentro])
        ruta.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(ruta, fechas=np.array([f.isoformat() for f in rej.fechas]),
                            lons=rej.lons, lats=rej.lats, afai=rej.afai)
        registrar(f"  AFAI {anio}-{mes:02d}: {len(rej.fechas)} imágenes en {time.perf_counter() - t0:.0f} s")
    with np.load(ruta) as z:
        return Rejilla([date.fromisoformat(s) for s in z["fechas"]], z["lons"], z["lats"], z["afai"])


class ArchivoAfai:
    """Acceso por fecha a la caché mensual (mantiene en memoria los meses recientes)."""

    def __init__(self, cache: Path = cfg.DIR_CACHE, registrar=print, max_meses: int = 3):
        self.cache, self.registrar, self.max_meses = cache, registrar, max_meses
        self._meses: dict[tuple[int, int], Rejilla] = {}

    def _mes(self, anio: int, mes: int) -> Rejilla:
        clave = (anio, mes)
        if clave not in self._meses:
            if len(self._meses) >= self.max_meses:
                self._meses.pop(next(iter(self._meses)))
            self._meses[clave] = mes_afai(anio, mes, self.cache, self.registrar)
        return self._meses[clave]

    def rejilla(self) -> tuple[np.ndarray, np.ndarray]:
        r = self._mes(cfg.BUSQUEDA_DESDE.year, cfg.BUSQUEDA_DESDE.month)
        return r.lons, r.lats

    def dia(self, fecha: date) -> np.ndarray | None:
        return self._mes(fecha.year, fecha.month).dia(fecha)

    def fechas_mes(self, anio: int, mes: int) -> list[date]:
        return list(self._mes(anio, mes).fechas)


# ---------------------------------------------------------------------------
# Detección
# ---------------------------------------------------------------------------
def _mediana_movil(valores: np.ndarray, ventana: int = cfg.VENTANA_FONDO, paso: int = cfg.PASO_FONDO,
                   min_validos: float = cfg.MIN_VALIDOS_FONDO) -> np.ndarray:
    """Mediana (ignorando NaN) en una ventana cuadrada, evaluada cada `paso` píxeles e
    interpolada de forma bilineal al resto; donde no hay suficientes datos se rellena con
    el centro válido más cercano."""
    ny, nx = valores.shape
    r = ventana // 2
    rel = np.pad(valores, r, constant_values=np.nan)
    ci = np.arange(0, ny, paso)
    cj = np.arange(0, nx, paso)
    if ci[-1] != ny - 1:
        ci = np.append(ci, ny - 1)
    if cj[-1] != nx - 1:
        cj = np.append(cj, nx - 1)
    vistas = sliding_window_view(rel, (ventana, ventana))[np.ix_(ci, cj)]
    planas = vistas.reshape(ci.size, cj.size, -1)
    n_validos = np.isfinite(planas).sum(axis=2)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(planas, axis=2)
    med[n_validos < min_validos * ventana * ventana] = np.nan
    if not np.isfinite(med).any():
        return np.full(valores.shape, np.nan)
    faltan = ~np.isfinite(med)
    if faltan.any():
        idx = ndimage.distance_transform_edt(faltan, return_distances=False, return_indices=True)
        med = med[tuple(idx)]
    # Interpolación bilineal de los centros a todos los píxeles.
    fi = np.interp(np.arange(ny), ci, np.arange(ci.size))
    fj = np.interp(np.arange(nx), cj, np.arange(cj.size))
    gi, gj = np.meshgrid(fi, fj, indexing="ij")
    return ndimage.map_coordinates(med, [gi, gj], order=1, mode="nearest")


ESCALA_MAD = 1.4826          # MAD → desviación estándar para ruido gaussiano


@dataclass
class Deteccion:
    delta: np.ndarray      # ΔAFAI (NaN = sin observación útil)
    valido: np.ndarray     # bool: píxel de mar útil observado (sin nube ni borde de nube)
    sargazo: np.ndarray    # bool: ΔAFAI > T0 en un píxel válido


def detectar(afai: np.ndarray, mar_util: np.ndarray, t0: float = cfg.UMBRAL_T0, ts: float = cfg.UMBRAL_TS,
             borde_nube_px: int = cfg.BORDE_NUBE_PX, k_sigma: float = cfg.K_SIGMA) -> Deteccion:
    """Detección de sargazo en una imagen AFAI.

    mar_util: bool, píxeles de mar donde tiene sentido buscar (sin tierra del modelo ni
    píxeles brillantes persistentes). Lo que no es mar útil nunca cuenta como válido.
    """
    a = np.where(mar_util, afai, np.nan).astype(np.float64)
    observado = np.isfinite(a)
    # Píxeles junto a una nube (mar útil sin dato) se descartan por efecto de adyacencia.
    nube = mar_util & ~observado
    if borde_nube_px > 0 and nube.any():
        cerca = ndimage.binary_dilation(nube, iterations=borde_nube_px)
        a[cerca] = np.nan
    valido = np.isfinite(a)
    if not valido.any():
        vacio = np.zeros(a.shape, dtype=bool)
        return Deteccion(np.full(a.shape, np.nan), vacio, vacio)
    fondo1 = _mediana_movil(a)
    candidatos = (a - fondo1) > ts
    fondo2 = _mediana_movil(np.where(candidatos, np.nan, a))
    delta = a - fondo2
    # Ruido local robusto (1.4826·MAD de ΔAFAI sin los candidatos, en la misma ventana). En el
    # producto de AOML el ruido del Caribe (~2×10⁻⁴) es del orden de T0: con T0 solo, en enero
    # (sin temporada) 11–18 % del Caribe abierto saldría con "sargazo". Se exige ΔAFAI > k·σ.
    sigma = ESCALA_MAD * _mediana_movil(np.abs(np.where(candidatos, np.nan, delta)))
    umbral = np.maximum(t0, k_sigma * sigma)
    return Deteccion(delta, valido, valido & (delta > umbral))


def mar_del_modelo(lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """bool [lat, lon]: centro del píxel en el mar según la costa del modelo."""
    from src.model import costa
    glon, glat = np.meshgrid(lons, lats)
    return ~costa.en_tierra(glon, glat)


def km_por_pixel(lons: np.ndarray, lats: np.ndarray) -> tuple[float, float]:
    """Tamaño medio del píxel (km) en x y en y, en la latitud media del recuadro."""
    from src.config import RADIO_TIERRA_M
    km_grado = np.pi * RADIO_TIERRA_M / 180.0 / 1000.0
    dlon = float(np.mean(np.diff(lons)))
    dlat = float(np.mean(np.diff(lats)))
    return dlon * km_grado * np.cos(np.radians(float(np.mean(lats)))), dlat * km_grado
