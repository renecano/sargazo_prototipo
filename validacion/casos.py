"""Selección automática y reproducible de casos.

Un día t0 es candidato si (en este orden; el primer criterio que falla es el motivo del
descarte):
  1. hay imagen AFAI ese día;
  2. tiene al menos MIN_PIXELES_SARGAZO píxeles con sargazo en el mar útil;
  3. al menos MIN_CLARO_T0 del mar útil está sin nube;
  4. hay imagen a +3, +5 y +7 días;
  5. en cada una, al menos MIN_CLARO_DESTINO del mar útil está sin nube;
  6. y al menos MIN_CLARO_ZONA de la zona a ≤ 50 km del sargazo de t0 está sin nube
     (si no, no se puede ver a dónde fue).
Entre los candidatos se eligen casos que no compartan imágenes (t0 separados por más de 7
días), de mayor a menor calidad (la peor fracción despejada de sus cuatro imágenes) y, a
igual calidad, el más antiguo. Calibración = t0 antes de CORTE_EVALUACION; evaluación = el resto.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import numpy as np
from scipy import ndimage

from validacion import afai
from validacion import config as cfg

MOTIVOS = {
    "sin_imagen": "Sin imagen AFAI ese día",
    "poco_sargazo": f"Menos de {cfg.MIN_PIXELES_SARGAZO} píxeles con sargazo en t0",
    "nube_t0": f"Menos de {cfg.MIN_CLARO_T0:.0%} del mar despejado en t0",
    "sin_destino": "Falta la imagen de +3, +5 o +7 días",
    "nube_destino": f"Menos de {cfg.MIN_CLARO_DESTINO:.0%} del mar despejado a +3, +5 o +7 días",
    "nube_zona": f"Menos de {cfg.MIN_CLARO_ZONA:.0%} despejado a ≤ {cfg.RADIO_ZONA_KM:.0f} km del sargazo a +3, +5 o +7 días",
    "traslape": "Comparte imágenes con un caso de mejor calidad (t0 a 7 días o menos)",
}


@dataclass
class Caso:
    id: str
    t0: date
    conjunto: str                     # "calibracion" | "evaluacion" | "semar"
    sargazo_t0: int
    claro: dict = field(default_factory=dict)       # {0: f, 3: f, 5: f, 7: f}
    claro_zona: dict = field(default_factory=dict)  # {3: f, 5: f, 7: f}
    calidad: float = 0.0
    cumple_criterios: bool = True

    def fila(self) -> dict:
        d = asdict(self)
        d["t0"] = self.t0.isoformat()
        for k in (0, *cfg.HORIZONTES_D):
            d[f"claro_{k}d"] = round(self.claro.get(k, float("nan")), 3)
        for k in cfg.HORIZONTES_D:
            d[f"claro_zona_{k}d"] = round(self.claro_zona.get(k, float("nan")), 3)
        d.pop("claro")
        d.pop("claro_zona")
        d["calidad"] = round(self.calidad, 3)
        return d


def zona_alrededor(sargazo: np.ndarray, km_px: tuple[float, float], radio_km: float = cfg.RADIO_ZONA_KM) -> np.ndarray:
    if not sargazo.any():
        return np.zeros_like(sargazo)
    d = ndimage.distance_transform_edt(~sargazo, sampling=(km_px[1], km_px[0]))
    return d <= radio_km


def evaluar_dia(t0: date, por_fecha: dict, detecciones, mascaras, km_px) -> tuple[str | None, Caso | None]:
    """(motivo de descarte o None, caso candidato)."""
    fila = por_fecha.get(t0)
    if fila is None:
        return "sin_imagen", None
    if fila["sargazo"] < cfg.MIN_PIXELES_SARGAZO:
        return "poco_sargazo", None
    if fila["claro"] < cfg.MIN_CLARO_T0:
        return "nube_t0", None
    destinos = [por_fecha.get(t0 + timedelta(days=k)) for k in cfg.HORIZONTES_D]
    if any(d is None for d in destinos):
        return "sin_destino", None
    if any(d["claro"] < cfg.MIN_CLARO_DESTINO for d in destinos):
        return "nube_destino", None
    _, sarg0 = detecciones.dia(t0)
    zona = zona_alrededor(sarg0, km_px) & mascaras.mar_util
    n_zona = max(int(zona.sum()), 1)
    claro_zona = {}
    for k in cfg.HORIZONTES_D:
        valido, _ = detecciones.dia(t0 + timedelta(days=k))
        claro_zona[k] = float((valido & zona).sum()) / n_zona
    if any(v < cfg.MIN_CLARO_ZONA for v in claro_zona.values()):
        return "nube_zona", None
    claro = {0: fila["claro"], **{k: d["claro"] for k, d in zip(cfg.HORIZONTES_D, destinos)}}
    calidad = min(min(claro.values()), min(claro_zona.values()))
    conjunto = "calibracion" if t0 < cfg.CORTE_EVALUACION else "evaluacion"
    return None, Caso(f"C{t0.strftime('%Y%m%d')}", t0, conjunto, fila["sargazo"], claro, claro_zona, calidad)


@dataclass
class Seleccion:
    casos: list[Caso]
    candidatos: int
    dias_revisados: int
    descartes: dict           # motivo → número de días
    caso_semar: Caso | None
    motivo_semar: str | None


def seleccionar(filas: list[dict], detecciones, mascaras) -> Seleccion:
    por_fecha = {f["fecha"]: f for f in filas}
    km_px = afai.km_por_pixel(mascaras.lons, mascaras.lats)
    ultimo_t0 = cfg.BUSQUEDA_HASTA - timedelta(days=max(cfg.HORIZONTES_D))
    descartes = {m: 0 for m in MOTIVOS}
    candidatos = []
    d, revisados = cfg.BUSQUEDA_DESDE, 0
    while d <= ultimo_t0:
        revisados += 1
        motivo, caso = evaluar_dia(d, por_fecha, detecciones, mascaras, km_px)
        if motivo:
            descartes[motivo] += 1
        else:
            candidatos.append(caso)
        d += timedelta(days=1)
    elegidos: list[Caso] = []
    separacion = max(cfg.HORIZONTES_D)
    for c in sorted(candidatos, key=lambda c: (-c.calidad, c.t0)):
        if all(abs((c.t0 - e.t0).days) > separacion for e in elegidos):
            elegidos.append(c)
        else:
            descartes["traslape"] += 1
    elegidos.sort(key=lambda c: c.t0)

    # Caso de la fecha del dirmarea.txt de SEMAR: se evalúa aunque no cumpla los criterios.
    motivo_semar, caso_semar = evaluar_dia(cfg.FECHA_DIRMAREA_SEMAR, por_fecha, detecciones, mascaras, km_px)
    if caso_semar is None and cfg.FECHA_DIRMAREA_SEMAR in por_fecha:
        f = por_fecha[cfg.FECHA_DIRMAREA_SEMAR]
        caso_semar = Caso("SEMAR20261001", cfg.FECHA_DIRMAREA_SEMAR, "semar", f["sargazo"], {0: f["claro"]})
        for k in cfg.HORIZONTES_D:
            destino = por_fecha.get(cfg.FECHA_DIRMAREA_SEMAR + timedelta(days=k))
            if destino:
                caso_semar.claro[k] = destino["claro"]
        caso_semar.cumple_criterios = False
    elif caso_semar is not None:
        caso_semar.id, caso_semar.conjunto = "SEMAR20261001", "semar"
    return Seleccion(elegidos, len(candidatos), revisados, descartes, caso_semar, motivo_semar)
