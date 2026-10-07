"""Métricas de resumen de una simulación, pensadas para comunicar probabilidad, no certeza."""
from __future__ import annotations

import numpy as np

from src.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from src.model import costa
from src.model.conversiones import distancia_km, nombre_rumbo
from src.model.simulacion import A_FLOTE, FUERA, VARADA, Resultado

HORAS_REPORTE = (24, 48, 72, 96, 120)
MIN_FRACCION_CENTROIDE = 0.01


def etiqueta_probabilidad(p: float) -> str:
    if p >= 0.30:
        return "Alta"
    if p >= 0.10:
        return "Media"
    if p >= 0.02:
        return "Baja"
    return "Muy baja"


def centroide_y_radio(r: Resultado):
    """Por hora: centroide de las partículas a flote y radio P90 (km) a su alrededor."""
    n = r.lon.shape[1]
    centroide, radio = [], []
    for h in range(r.horas + 1):
        flotan = r.estado_en(h) == A_FLOTE
        if flotan.sum() < max(1, MIN_FRACCION_CENTROIDE * n):
            centroide.append(None)
            radio.append(None)
            continue
        x, y = r.lon[h, flotan], r.lat[h, flotan]
        cx, cy = float(x.mean()), float(y.mean())
        centroide.append((cx, cy))
        radio.append(float(np.percentile(distancia_km(cx, cy, x, y), 90)))
    return centroide, radio


def resumir(r: Resultado) -> dict:
    n = r.lon.shape[1]
    centroide, radio = centroide_y_radio(r)
    validos = [(h, c) for h, c in enumerate(centroide) if c is not None]

    recorrida = 0.0
    for (_, a), (_, b) in zip(validos, validos[1:]):
        recorrida += float(distancia_km(a[0], a[1], b[0], b[1]))
    p = r.parametros
    ultimo_h, ultimo = validos[-1] if validos else (0, (p.lon, p.lat))
    neto = float(distancia_km(p.lon, p.lat, ultimo[0], ultimo[1]))
    dx = (ultimo[0] - p.lon) * np.cos(np.radians(p.lat))
    dy = ultimo[1] - p.lat
    rumbo = float(np.degrees(np.arctan2(dx, dy)) % 360)

    varadas = r.estado == VARADA
    zonas = costa.zona_costera(r.lon[-1, varadas], r.lat[-1, varadas]) if varadas.any() else np.empty(0, dtype=object)
    horas_v = r.hora_varada[varadas]
    arribos = []
    for z in costa.ZONAS:
        en_zona = zonas == z["id"]
        cuenta = int(en_zona.sum())
        if not cuenta:
            continue
        prob = cuenta / n
        arribos.append({
            "zona": z["id"],
            "nombre": z["nombre"],
            "particulas": cuenta,
            "probabilidad": round(prob, 4),
            "etiqueta": etiqueta_probabilidad(prob),
            "primer_arribo_h": int(horas_v[en_zona].min()),
            "arribo_mediano_h": int(np.median(horas_v[en_zona])),
            "ancla": list(z["ancla"]),
        })
    arribos.sort(key=lambda a: -a["probabilidad"])

    fuera = r.estado == FUERA
    bordes = {}
    if fuera.any():
        x, y = r.lon[-1, fuera], r.lat[-1, fuera]
        lon_min, lon_max, lat_min, lat_max = LON_MIN, LON_MAX, LAT_MIN, LAT_MAX
        for nombre, sel in (("norte", np.isclose(y, lat_max)), ("sur", np.isclose(y, lat_min)),
                            ("este", np.isclose(x, lon_max)), ("oeste", np.isclose(x, lon_min))):
            if sel.any():
                bordes[nombre] = int(sel.sum())

    serie_varadas, serie_fuera = [], []
    for h in range(r.horas + 1):
        e = r.estado_en(h)
        serie_varadas.append(round(float(np.mean(e == VARADA)), 4))
        serie_fuera.append(round(float(np.mean(e == FUERA)), 4))

    advertencias = [
        "Pronóstico probabilístico: los porcentajes son fracciones de partículas simuladas, "
        "no certezas de arribo a una playa específica.",
        "Parámetros preliminares sin calibrar (α y K_h).",
    ]
    if fuera.any():
        advertencias.append(
            f"{100 * fuera.mean():.0f} % de las partículas salió del dominio "
            f"({', '.join(f'{k}: {v}' for k, v in bordes.items())}); su destino posterior no se simula."
        )
    if p.horizonte_h > 48:
        advertencias.append("Más allá de 48 h (horizonte de los boletines de SEMAR) la incertidumbre crece notablemente.")

    return {
        "particulas": n,
        "a_flote_pct": round(100 * float(np.mean(r.estado == A_FLOTE)), 1),
        "varadas_pct": round(100 * float(varadas.mean()), 1),
        "fuera_pct": round(100 * float(fuera.mean()), 1),
        "salidas_por_borde": bordes,
        "reubicadas_inicio": r.reubicadas_inicio,
        "distancia_centroide_km": round(recorrida, 1),
        "desplazamiento_neto_km": round(neto, 1),
        "rumbo_neto_grados": round(rumbo, 0),
        "rumbo_neto": nombre_rumbo(rumbo),
        "centroide_hasta_h": ultimo_h,
        "radio_p90_km": {str(h): (round(radio[h], 1) if radio[h] is not None else None)
                         for h in HORAS_REPORTE if h <= r.horas},
        "arribos": arribos,
        "advertencias": advertencias,
        "series": {
            "centroide": [None if c is None else [round(c[0], 4), round(c[1], 4)] for c in centroide],
            "radio_p90_km": [None if v is None else round(v, 2) for v in radio],
            "varadas": serie_varadas,
            "fuera": serie_fuera,
        },
    }
