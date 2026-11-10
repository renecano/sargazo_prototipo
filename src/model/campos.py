"""Deriva de Stokes de la ola de viento interpolada en la posición y el tiempo de cada partícula.

Tres reglas, las mismas que usa la interfaz para el hover y el oleaje animado
(src/view/js/datos.js) y que el README documenta en «Interpolación»:

1. Espacio. Se toma cada valor del archivo como el valor EN su nodo (LON, LAT). Los nodos
   caen en −92.08, −91.92… (múltiplos de 0.16° más 0.08°) porque la malla de SEMAR empieza
   en −98°; no es un desfase del modelo. Comparado con la costa real, el relleno del archivo
   coincide al 96.8 % sin desplazar la malla y entre 95.8 y 97.4 % desplazándola ±0.08°: no
   hay evidencia de que los valores estén en esquinas de celda, pero tampoco se descarta
   (pregunta abierta para SEMAR). Entre nodos, bilineal: la altura directamente y la
   dirección por sus componentes seno y coseno (350° y 10° dan 0°, no 180°). Los nodos sin
   dato no entran en el promedio y los pesos se renormalizan. Fuera de la malla se usa el
   nodo del borde.
2. Franja costera. La malla de 0.16° deja sin dato celdas enteras que sí tienen mar:
   5 288 km² del dominio (1.4 % del mar), entre ellos la franja frente a Playa del Carmen,
   Akumal y Sian Ka'an. Una partícula que entraba ahí se quedaba sin deriva. Ahora cada
   nodo sin dato vecino de nodos con dato toma su promedio, hasta NODOS_EXTRAPOLACION nodos
   tierra adentro; quedan sin ola 279 km², al fondo de la Bahía de Chetumal, donde la
   deriva es cero.
3. Tiempo. Lineal entre bloques (cada 3 h) de altura, seno y coseno; antes del primer
   bloque y después del último se usa el más cercano.

Si las direcciones que se promedian se cancelan (resultante < R_MINIMA) la dirección no está
definida y la deriva es cero, en lugar de inventar un rumbo.
"""
from __future__ import annotations

import numpy as np

from src.config import COEF_STOKES
from src.ingestion.lector import ConjuntoDatos

NODOS_EXTRAPOLACION = 2      # nodos (0.16° c/u) que la ola se extiende hacia la costa
R_MINIMA = 1e-6              # resultante mínima de (seno, coseno) para que haya dirección
_VECINOS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


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


def extender_a_la_costa(altura: np.ndarray, seno: np.ndarray, coseno: np.ndarray,
                        pasadas: int = NODOS_EXTRAPOLACION):
    """Rellena los nodos sin dato vecinos de nodos con dato con el promedio de estos.

    Arreglos [bloque, lat, lon]. Devuelve (altura, seno, coseno, extrapolado); `extrapolado`
    marca los nodos rellenados. La dirección se promedia por seno y coseno y se normaliza.
    """
    h, s, c = altura.copy(), seno.copy(), coseno.copy()
    extrapolado = np.zeros(h.shape, dtype=bool)
    ny, nx = h.shape[-2:]
    margen = ((0, 0), (1, 1), (1, 1))
    for _ in range(pasadas):
        valido = np.isfinite(h)
        vp = np.pad(valido, margen)
        hp, sp, cp = (np.pad(np.where(valido, a, 0.0), margen) for a in (h, s, c))
        n = np.zeros(h.shape)
        sh, ss, sc = np.zeros(h.shape), np.zeros(h.shape), np.zeros(h.shape)
        for di, dj in _VECINOS:
            corte = (slice(None), slice(1 + di, 1 + di + ny), slice(1 + dj, 1 + dj + nx))
            n += vp[corte]
            sh += hp[corte]
            ss += sp[corte]
            sc += cp[corte]
        nuevo = ~valido & (n > 0)
        if not nuevo.any():
            break
        r = np.hypot(ss, sc)
        con_rumbo = r > R_MINIMA * np.maximum(n, 1)
        h[nuevo] = sh[nuevo] / n[nuevo]
        s[nuevo] = np.where(con_rumbo, ss / np.maximum(r, 1e-300), 0.0)[nuevo]
        c[nuevo] = np.where(con_rumbo, sc / np.maximum(r, 1e-300), 0.0)[nuevo]
        extrapolado |= nuevo
    return h, s, c, extrapolado


def _bilineal(campos: tuple[np.ndarray, ...], fi: np.ndarray, fj: np.ndarray) -> tuple[tuple[np.ndarray, ...], np.ndarray]:
    """Interpolación bilineal de varios campos [ny, nx] que comparten máscara, en índices
    fraccionarios. Los nodos sin dato (NaN) se descartan y los pesos se renormalizan; fuera
    de la malla se usa el borde. Sin ningún vecino con dato devuelve NaN. Devuelve los campos
    interpolados y la suma de pesos válidos (la usa la validación)."""
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
    return tuple(np.where(pesos > 1e-12, s / np.maximum(pesos, 1e-12), np.nan) for s in sumas), pesos


class CamposOleaje:
    """Oleaje de SEMAR (altura y dirección «desde») sobre la malla nativa de 0.16°.

    Devuelve la deriva de Stokes para γ = 1; la simulación la multiplica por γ. Las reglas
    de interpolación están en la cabecera del módulo.
    """

    def __init__(self, conjunto: ConjuntoDatos, nodos_extrapolacion: int = NODOS_EXTRAPOLACION):
        self.lon0 = float(conjunto.lons[0])
        self.lat0 = float(conjunto.lats[0])
        self.dlon = float(conjunto.lons[1] - conjunto.lons[0])
        self.dlat = float(conjunto.lats[1] - conjunto.lats[0])
        self.horas = np.asarray(conjunto.horas, dtype=float) - float(conjunto.horas[0])
        rad = np.radians(conjunto.direccion.astype(np.float64))
        self.altura, self.seno, self.coseno, self.extrapolado = extender_a_la_costa(
            conjunto.altura.astype(np.float64), np.sin(rad), np.cos(rad), nodos_extrapolacion)

    def _indices_tiempo(self, t_horas: float):
        if self.horas.size == 1 or t_horas <= self.horas[0]:
            return 0, 0, 0.0
        if t_horas >= self.horas[-1]:
            k = self.horas.size - 1
            return k, k, 0.0
        k1 = int(np.searchsorted(self.horas, t_horas))
        k0 = k1 - 1
        return k0, k1, float((t_horas - self.horas[k0]) / (self.horas[k1] - self.horas[k0]))

    def _interpolar(self, lon, lat, t_horas: float):
        """(altura, seno, coseno) en cada punto; NaN donde no hay ningún nodo con dato."""
        fi = (np.asarray(lat, dtype=float) - self.lat0) / self.dlat
        fj = (np.asarray(lon, dtype=float) - self.lon0) / self.dlon
        k0, k1, w = self._indices_tiempo(float(t_horas))
        a, _ = _bilineal((self.altura[k0], self.seno[k0], self.coseno[k0]), fi, fj)
        if w <= 0:
            return a
        b, _ = _bilineal((self.altura[k1], self.seno[k1], self.coseno[k1]), fi, fj)
        ambos, solo_a = np.isfinite(a[0]) & np.isfinite(b[0]), np.isfinite(a[0])
        return tuple(np.where(ambos, (1 - w) * x + w * y, np.where(solo_a, x, y)) for x, y in zip(a, b))

    def ola(self, lon, lat, t_horas: float):
        """(altura m, dirección «desde» °) interpoladas; NaN si no hay nodo con dato o si las
        direcciones se cancelan."""
        h, s, c = self._interpolar(lon, lat, t_horas)
        direccion = np.mod(np.degrees(np.arctan2(s, c)), 360.0)
        return h, np.where(np.hypot(s, c) > R_MINIMA, direccion, np.nan)

    def velocidades(self, lon, lat, t_horas: float):
        """(u, v) de la deriva de Stokes en m/s (γ = 1); 0 donde no hay ola o no hay rumbo."""
        h, s, c = self._interpolar(lon, lat, t_horas)
        r = np.hypot(s, c)
        ok = np.isfinite(h) & (r > R_MINIMA)
        mag = magnitud_stokes(h) / np.where(ok, r, 1.0)
        # «Hacia» = «desde» + 180°: sen(θ + 180°) = −sen θ y cos(θ + 180°) = −cos θ.
        return np.where(ok, -mag * s, 0.0), np.where(ok, -mag * c, 0.0)


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
