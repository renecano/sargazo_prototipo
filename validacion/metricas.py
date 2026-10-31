"""Métricas de la validación: FSS, centroide, MCC, Liu-Weisberg, llegada a costa y bootstrap.

Todas trabajan sobre la rejilla AFAI (~1.6 km) y respetan la máscara de observación: un
píxel con nube en la imagen de destino no cuenta ni para lo observado ni para lo simulado.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from src.config import RADIO_TIERRA_M

KM_GRADO = np.pi * RADIO_TIERRA_M / 180.0 / 1000.0


# ---------------------------------------------------------------------------
# Fractions Skill Score (Roberts & Lean, 2008, Mon. Wea. Rev. 136:78-97)
# ---------------------------------------------------------------------------
def ventana_impar(escala_km: float, km_pixel: float) -> int:
    """Lado (píxeles, impar) de la ventana cuadrada más cercana a `escala_km`."""
    n = escala_km / km_pixel
    return int(2 * max(round((n - 1) / 2), 0) + 1)


def suma_ventana(a: np.ndarray, n: int) -> np.ndarray:
    """Suma en una ventana cuadrada de lado n (impar) centrada en cada píxel; fuera = 0."""
    r = n // 2
    p = np.pad(a.astype(np.float64), r + 1)
    c = p.cumsum(0).cumsum(1)
    ny, nx = a.shape
    i0 = np.arange(ny)
    j0 = np.arange(nx)
    lo_i, hi_i = i0, i0 + 2 * r + 1
    lo_j, hi_j = j0, j0 + 2 * r + 1
    return (c[np.ix_(hi_i, hi_j)] - c[np.ix_(lo_i, hi_j)] - c[np.ix_(hi_i, lo_j)] + c[np.ix_(lo_i, lo_j)])


def fss(observado: np.ndarray, simulado: np.ndarray, valido: np.ndarray, n: int) -> float:
    """FSS entre dos campos en [0, 1] con máscara de validez.

    Las fracciones en cada ventana se calculan solo con los píxeles válidos (O y M usan la
    misma máscara) y se evalúan en los píxeles válidos. NaN si ni lo observado ni lo
    simulado tienen eventos (FSS indefinido).
    """
    v = valido.astype(np.float64)
    nv = suma_ventana(v, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        fo = np.where(nv > 0, suma_ventana(observado * v, n) / nv, 0.0)
        fm = np.where(nv > 0, suma_ventana(simulado * v, n) / nv, 0.0)
    m = valido
    mse = np.mean((fo[m] - fm[m]) ** 2)
    ref = np.mean(fo[m] ** 2) + np.mean(fm[m] ** 2)
    return float(1.0 - mse / ref) if ref > 0 else float("nan")


def fss_uniforme(observado: np.ndarray, valido: np.ndarray) -> float:
    """FSS "útil" mínimo de Roberts & Lean: 0.5 + f0/2 (f0 = fracción observada)."""
    f0 = float(observado[valido].mean()) if valido.any() else 0.0
    return 0.5 + f0 / 2


# ---------------------------------------------------------------------------
# Centroide y dirección del desplazamiento
# ---------------------------------------------------------------------------
def centroide(campo: np.ndarray, valido: np.ndarray, glon: np.ndarray, glat: np.ndarray):
    w = np.where(valido, campo, 0.0)
    s = w.sum()
    if s <= 0:
        return None
    return float((w * glon).sum() / s), float((w * glat).sum() / s)


def vector_km(a, b) -> np.ndarray:
    """Desplazamiento (este, norte) en km de a = (lon, lat) a b."""
    lat_m = np.radians((a[1] + b[1]) / 2)
    return np.array([(b[0] - a[0]) * KM_GRADO * np.cos(lat_m), (b[1] - a[1]) * KM_GRADO])


def distancia_km(a, b) -> float:
    return float(np.hypot(*vector_km(a, b)))


def diferencia_angular(v1, v2) -> float:
    """Ángulo (0–180°) entre dos vectores."""
    a1 = np.degrees(np.arctan2(v1[0], v1[1]))
    a2 = np.degrees(np.arctan2(v2[0], v2[1]))
    return float(abs((a1 - a2 + 180.0) % 360.0 - 180.0))


def rumbo(v) -> float:
    """Rumbo (0–360°, 0 = norte, horario) de un vector (este, norte)."""
    return float(np.degrees(np.arctan2(v[0], v[1])) % 360.0)


# ---------------------------------------------------------------------------
# MCC: correlación cruzada máxima normalizada con máscara (Padfield, 2012, IEEE TIP 21:2706)
# ---------------------------------------------------------------------------
def ncc_enmascarada(plantilla: np.ndarray, mascara_p: np.ndarray, imagen: np.ndarray, mascara_i: np.ndarray,
                    min_traslape: int) -> np.ndarray:
    """Correlación normalizada de la plantilla en cada desplazamiento "válido" dentro de la
    imagen (la imagen es la zona de búsqueda, mayor que la plantilla). Solo usa píxeles
    válidos en ambas; NaN donde el traslape es menor que `min_traslape`."""
    t = np.where(mascara_p, plantilla, 0.0)
    mt = mascara_p.astype(np.float64)
    im = np.where(mascara_i, imagen, 0.0)
    mi = mascara_i.astype(np.float64)

    def corr(a, b):
        return signal.correlate(a, b, mode="valid", method="fft")

    traslape = np.round(corr(mi, mt))
    suma_i = corr(im, mt)
    suma_i2 = corr(im * im, mt)
    suma_t = corr(mi, t)
    suma_t2 = corr(mi, t * t)
    cruzada = corr(im, t)
    with np.errstate(invalid="ignore", divide="ignore"):
        num = cruzada - suma_i * suma_t / traslape
        den = (suma_i2 - suma_i ** 2 / traslape) * (suma_t2 - suma_t ** 2 / traslape)
        r = num / np.sqrt(np.maximum(den, 0.0))
    r[(traslape < min_traslape) | ~np.isfinite(r) | (den <= 1e-30)] = np.nan
    return r


def _subpixel(r: np.ndarray, i: int, j: int) -> tuple[float, float]:
    """Ajuste parabólico del máximo en cada eje."""
    def par(a, b, c):
        d = a - 2 * b + c
        return 0.0 if not np.isfinite(d) or d >= 0 else 0.5 * (a - c) / d
    di = par(r[i - 1, j], r[i, j], r[i + 1, j]) if 0 < i < r.shape[0] - 1 else 0.0
    dj = par(r[i, j - 1], r[i, j], r[i, j + 1]) if 0 < j < r.shape[1] - 1 else 0.0
    return float(np.clip(di, -0.5, 0.5)), float(np.clip(dj, -0.5, 0.5))


@dataclass
class VectorMCC:
    i: int                  # centro de la plantilla (fila, columna) en la imagen del día d
    j: int
    di: float               # desplazamiento en píxeles (filas = norte, columnas = este)
    dj: float
    correlacion: float


def mcc(campo_a: np.ndarray, valido_a: np.ndarray, sargazo_a: np.ndarray, campo_b: np.ndarray,
        valido_b: np.ndarray, plantilla_px: int, busqueda_px: int, min_sargazo: int, min_validos: float,
        min_correlacion: float, razon_pico: float = 0.9) -> list[VectorMCC]:
    """Vectores de desplazamiento de la imagen A a la B por máxima correlación cruzada.

    Plantillas de `plantilla_px` sin traslape sobre A, con al menos `min_sargazo` píxeles con
    sargazo y `min_validos` de fracción válida; se buscan en B hasta ± `busqueda_px`. Se
    acepta el máximo si la correlación ≥ `min_correlacion` y no está en el borde de la
    búsqueda (un máximo en el borde puede estar fuera de ella).
    """
    p, r = plantilla_px, busqueda_px
    h = p // 2
    ny, nx = campo_a.shape
    vectores = []
    for ci in range(h, ny - h, p):
        for cj in range(h, nx - h, p):
            sa = sargazo_a[ci - h:ci + h + 1, cj - h:cj + h + 1]
            va = valido_a[ci - h:ci + h + 1, cj - h:cj + h + 1]
            if sa.sum() < min_sargazo or va.mean() < min_validos:
                continue
            i0, i1 = ci - h - r, ci + h + r + 1
            j0, j1 = cj - h - r, cj + h + r + 1
            if i0 < 0 or j0 < 0 or i1 > ny or j1 > nx:
                continue
            zona_v = valido_b[i0:i1, j0:j1]
            if zona_v.mean() < min_validos:
                continue
            corr = ncc_enmascarada(campo_a[ci - h:ci + h + 1, cj - h:cj + h + 1], va,
                                   campo_b[i0:i1, j0:j1], zona_v, int(min_validos * p * p))
            if not np.isfinite(corr).any():
                continue
            k = int(np.nanargmax(corr))
            bi, bj = np.unravel_index(k, corr.shape)
            mejor = float(corr[bi, bj])
            if mejor < min_correlacion or bi in (0, corr.shape[0] - 1) or bj in (0, corr.shape[1] - 1):
                continue
            # Pico ambiguo (criterio de razón de picos de PIV): si otro máximo, a más de 2 px
            # del primero, alcanza el 90 % de su correlación, el desplazamiento no es confiable.
            resto = corr.copy()
            resto[max(bi - 2, 0):bi + 3, max(bj - 2, 0):bj + 3] = np.nan
            if np.isfinite(resto).any() and np.nanmax(resto) >= razon_pico * mejor:
                continue
            si, sj = _subpixel(np.nan_to_num(corr, nan=-1.0), bi, bj)
            vectores.append(VectorMCC(ci, cj, bi + si - r, bj + sj - r, mejor))
    return vectores


def liu_weisberg(separaciones_km: np.ndarray, longitudes_km: np.ndarray, n: float = 1.0) -> float:
    """Skill score de Liu & Weisberg (2011, JGR 116:C09013): s = Σd / Σl; SS = 1 − s/n si
    s ≤ n, si no 0. Con trayectorias de un solo tramo (24 h), d es la distancia entre la
    posición final observada y la simulada, y l la longitud del tramo observado."""
    total_l = float(np.sum(longitudes_km))
    if total_l <= 0:
        return float("nan")
    s = float(np.sum(separaciones_km)) / total_l
    return max(0.0, 1.0 - s / n)


# ---------------------------------------------------------------------------
# Llegada a costa
# ---------------------------------------------------------------------------
@dataclass
class Contingencia:
    aciertos: int = 0
    fallos: int = 0          # observado y no pronosticado
    falsas_alarmas: int = 0
    negativos: int = 0

    def sumar(self, pronostico: bool, observado: bool):
        if pronostico and observado:
            self.aciertos += 1
        elif observado:
            self.fallos += 1
        elif pronostico:
            self.falsas_alarmas += 1
        else:
            self.negativos += 1

    @property
    def pod(self):
        d = self.aciertos + self.fallos
        return self.aciertos / d if d else float("nan")

    @property
    def far(self):
        d = self.aciertos + self.falsas_alarmas
        return self.falsas_alarmas / d if d else float("nan")

    @property
    def csi(self):
        d = self.aciertos + self.fallos + self.falsas_alarmas
        return self.aciertos / d if d else float("nan")


# ---------------------------------------------------------------------------
# Bootstrap por caso
# ---------------------------------------------------------------------------
def bootstrap_media(valores: np.ndarray, remuestreos: int, nivel: float, semilla: int = 2026):
    """Media e intervalo de confianza percentil remuestreando casos (ignora NaN).

    valores: [caso]. Devuelve (media, inferior, superior, casos_validos)."""
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return float("nan"), float("nan"), float("nan"), 0
    rng = np.random.default_rng(semilla)
    medias = v[rng.integers(0, v.size, size=(remuestreos, v.size))].mean(axis=1)
    a = (1 - nivel) / 2
    return float(v.mean()), float(np.quantile(medias, a)), float(np.quantile(medias, 1 - a)), int(v.size)
