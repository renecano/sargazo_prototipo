"""Motor lagrangiano simplificado (estilo GNOME) para conglomerados de sargazo.

Para cada partícula y cada paso Δt = 1 h:

    X(t+Δt) = X(t) + [u_c(X,t) + α·u_w(X,t)]·Δt + √(2·K_h·Δt)·ξ,   ξ ~ N(0, 1)

- u_c: corriente superficial; u_w: viento a 10 m convertido a vector "hacia".
- El término determinista se integra con punto medio (RK2) en espacio y tiempo; con
  campos uniformes coincide exactamente con la solución analítica.
- El desplazamiento métrico se convierte a grados corrigiendo la longitud por cos(lat).
- Costa: si el segmento recorrido en el paso toca tierra, la partícula queda VARADA en
  el último punto en mar del segmento (búsqueda binaria) y ya no se mueve.
- Dominio: si sale del recuadro de la malla queda FUERA DEL DOMINIO y se congela en el borde.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np

from src.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, PASO_SEGUNDOS, VERSION_MODELO
from src.model import costa
from src.model.conversiones import metros_a_grados

A_FLOTE, VARADA, FUERA = 0, 1, 2
FRACCIONES_SEGMENTO = (0.25, 0.5, 0.75, 1.0)
ITERACIONES_BISECCION = 10
MAX_REINTENTOS_INICIO = 50


class PuntoInvalido(ValueError):
    """El punto de liberación está en tierra o fuera del dominio."""


@dataclass(frozen=True)
class Parametros:
    lon: float
    lat: float
    radio_km: float = 5.0
    particulas: int = 2000
    alpha_pct: float = 1.0
    kh_m2s: float = 10.0
    horizonte_h: int = 120
    semilla: int = 2026

    def a_dict(self) -> dict:
        return asdict(self)


@dataclass
class Resultado:
    parametros: Parametros
    lon: np.ndarray            # [H+1, N]
    lat: np.ndarray            # [H+1, N]
    estado: np.ndarray         # [N] estado final: A_FLOTE, VARADA, FUERA
    hora_varada: np.ndarray    # [N] hora en que vara (−1 si no)
    hora_fuera: np.ndarray     # [N] hora en que sale del dominio (−1 si no)
    reubicadas_inicio: int
    bitacora: list[str] = field(default_factory=list)
    duracion_s: float = 0.0
    version_modelo: str = VERSION_MODELO

    @property
    def horas(self) -> int:
        return self.lon.shape[0] - 1

    def estado_en(self, h: int) -> np.ndarray:
        """Estado de cada partícula en la hora h (para series temporales y la animación)."""
        e = np.full(self.estado.shape, A_FLOTE, dtype=np.int8)
        e[(self.hora_varada >= 0) & (self.hora_varada <= h)] = VARADA
        e[(self.hora_fuera >= 0) & (self.hora_fuera <= h)] = FUERA
        return e


Dominio = tuple[float, float, float, float]
FuncionTierra = Callable[[np.ndarray, np.ndarray], np.ndarray]
Progreso = Callable[[int, int, str], None]


def _fuera(lon, lat, dominio: Dominio):
    lon_min, lon_max, lat_min, lat_max = dominio
    return (lon < lon_min) | (lon > lon_max) | (lat < lat_min) | (lat > lat_max)


def validar_punto(lon: float, lat: float, en_tierra: FuncionTierra = costa.en_tierra,
                  dominio: Dominio = (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)) -> None:
    if _fuera(np.array([lon]), np.array([lat]), dominio)[0]:
        raise PuntoInvalido(
            f"El punto ({lat:.3f}, {lon:.3f}) está fuera del dominio de la malla "
            f"(lat {dominio[2]}…{dominio[3]}, lon {dominio[0]}…{dominio[1]})."
        )
    if en_tierra(np.array([lon]), np.array([lat]))[0]:
        raise PuntoInvalido(
            f"El punto ({lat:.3f}, {lon:.3f}) está en tierra según la costa aproximada del modelo. "
            "Elige un punto en el mar."
        )


def posiciones_iniciales(p: Parametros, rng: np.random.Generator, en_tierra: FuncionTierra):
    """Partículas uniformes en un disco de radio `radio_km`; las que caen en tierra se re-sortean."""
    def sortear(n):
        r = p.radio_km * 1000.0 * np.sqrt(rng.random(n))
        th = 2 * np.pi * rng.random(n)
        dlon, dlat = metros_a_grados(r * np.cos(th), r * np.sin(th), p.lat)
        return p.lon + dlon, p.lat + dlat

    lon, lat = sortear(p.particulas)
    malas = en_tierra(lon, lat)
    reubicadas = int(malas.sum())
    for _ in range(MAX_REINTENTOS_INICIO):
        if not malas.any():
            break
        lon[malas], lat[malas] = sortear(int(malas.sum()))
        malas = en_tierra(lon, lat)
    lon[malas], lat[malas] = p.lon, p.lat
    return lon, lat, reubicadas


def _deriva(campos, lon, lat, t, alpha):
    uc, vc, uw, vw = campos.velocidades(lon, lat, t)
    return uc + alpha * uw, vc + alpha * vw


def simular(campos, p: Parametros, en_tierra: FuncionTierra = costa.en_tierra,
            dominio: Dominio = (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX),
            progreso: Progreso | None = None) -> Resultado:
    t0 = time.perf_counter()
    validar_punto(p.lon, p.lat, en_tierra, dominio)
    rng = np.random.default_rng(p.semilla)
    n, horas = p.particulas, p.horizonte_h
    alpha = p.alpha_pct / 100.0
    dt = PASO_SEGUNDOS
    sigma = np.sqrt(2.0 * p.kh_m2s * dt)

    lon = np.empty((horas + 1, n))
    lat = np.empty((horas + 1, n))
    lon[0], lat[0], reubicadas = posiciones_iniciales(p, rng, en_tierra)
    estado = np.zeros(n, dtype=np.int8)
    hora_varada = np.full(n, -1, dtype=np.int16)
    hora_fuera = np.full(n, -1, dtype=np.int16)
    bitacora = [
        f"Modelo {VERSION_MODELO}; semilla {p.semilla}; α = {p.alpha_pct:g} %; K_h = {p.kh_m2s:g} m²/s; Δt = 1 h.",
        f"{n} partículas en un radio de {p.radio_km:g} km alrededor de ({p.lat:.3f}, {p.lon:.3f})"
        + (f"; {reubicadas} se re-sortearon por caer en tierra." if reubicadas else "."),
    ]

    for k in range(horas):
        lon[k + 1], lat[k + 1] = lon[k], lat[k]
        activas = np.flatnonzero(estado == A_FLOTE)
        if activas.size:
            x, y = lon[k, activas], lat[k, activas]
            u1, v1 = _deriva(campos, x, y, k, alpha)
            dlon, dlat = metros_a_grados(u1 * dt / 2, v1 * dt / 2, y)
            u2, v2 = _deriva(campos, x + dlon, y + dlat, k + 0.5, alpha)
            ruido = rng.standard_normal((2, activas.size))
            dx = u2 * dt + sigma * ruido[0]
            dy = v2 * dt + sigma * ruido[1]
            dlon, dlat = metros_a_grados(dx, dy, y)
            nx, ny = x + dlon, y + dlat

            # Costa: primera fracción del segmento que toca tierra.
            f_tierra = np.full(activas.size, np.inf)
            for f in reversed(FRACCIONES_SEGMENTO):
                toca = en_tierra(x + f * dlon, y + f * dlat)
                f_tierra[toca] = f
            varan = np.isfinite(f_tierra)
            if varan.any():
                lo = np.where(f_tierra[varan] > FRACCIONES_SEGMENTO[0], f_tierra[varan] - 0.25, 0.0)
                hi = f_tierra[varan]
                xv, yv, dxv, dyv = x[varan], y[varan], dlon[varan], dlat[varan]
                for _ in range(ITERACIONES_BISECCION):
                    mid = 0.5 * (lo + hi)
                    tierra = en_tierra(xv + mid * dxv, yv + mid * dyv)
                    hi = np.where(tierra, mid, hi)
                    lo = np.where(tierra, lo, mid)
                nx[varan] = xv + lo * dxv
                ny[varan] = yv + lo * dyv
                idx = activas[varan]
                estado[idx] = VARADA
                hora_varada[idx] = k + 1

            # Dominio: las que salen se congelan en el borde.
            salen = ~varan & _fuera(nx, ny, dominio)
            if salen.any():
                nx[salen] = np.clip(nx[salen], dominio[0], dominio[1])
                ny[salen] = np.clip(ny[salen], dominio[2], dominio[3])
                idx = activas[salen]
                estado[idx] = FUERA
                hora_fuera[idx] = k + 1

            lon[k + 1, activas], lat[k + 1, activas] = nx, ny

        if (k + 1) % 24 == 0 or k + 1 == horas:
            bitacora.append(
                f"+{k + 1} h: {100 * np.mean(estado == A_FLOTE):.1f} % a flote, "
                f"{100 * np.mean(estado == VARADA):.1f} % varadas, "
                f"{100 * np.mean(estado == FUERA):.1f} % fuera del dominio."
            )
        if progreso:
            progreso(k + 1, horas, f"Hora +{k + 1} de {horas}")

    duracion = time.perf_counter() - t0
    bitacora.append(f"Cálculo terminado en {duracion:.2f} s.")
    return Resultado(p, lon, lat, estado, hora_varada, hora_fuera, reubicadas, bitacora, duracion)
