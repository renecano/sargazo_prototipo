"""Orquestación de la validación: casos → calibración → experimentos → agregados.

Cada paso guarda su resultado en la caché (data/validacion/) y se reanuda si se corta (por
ejemplo, si Open-Meteo agota la cuota diaria). Los resultados finales (CSV, JSON y PNG) se
escriben en docs/validacion/ con validacion/reporte.py.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from validacion import afai, casos, experimentos, inventario, metricas
from validacion import config as cfg
from validacion.experimentos import Contexto, Experimento


def _json(obj):
    if isinstance(obj, (np.floating,)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(type(obj))


def _limpiar(o):
    """NaN → None para escribir JSON estándar."""
    if isinstance(o, dict):
        return {k: _limpiar(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_limpiar(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(_limpiar(datos), ensure_ascii=False, indent=1, default=_json), encoding="utf-8")


# ---------------------------------------------------------------------------
# Calibración de E3 (solo casos de calibración)
# ---------------------------------------------------------------------------
def calibrar_caso(caso, ctx: Contexto, det, forz, cache: Path, registrar) -> list[dict]:
    ruta = cache / "casos" / caso.id / "calibracion.json"
    if ruta.is_file():
        return json.loads(ruta.read_text(encoding="utf-8"))
    _, sarg0 = det.dia(caso.t0)
    siembra = experimentos.sembrar(sarg0, ctx.lons, ctx.lats)
    obs = {h: det.dia(caso.t0 + timedelta(days=h // 24)) for h in (24 * k for k in cfg.HORIZONTES_D)}
    n = ctx.ventanas[cfg.ESCALA_CALIBRACION_KM]
    filas = []
    for g in cfg.REJILLA_GAMMA:
        for kh in cfg.REJILLA_KH:
            exp = Experimento("cal", "cal", gamma=g, kh=kh)
            corr = experimentos.correr(exp, siembra, forz)
            fila = {"caso": caso.id, "gamma": g, "kh": kh}
            for h, (valido, sargazo) in obs.items():
                flota = corr.estado[h] == 0
                campo = experimentos.a_pixeles(corr.lon[h][flota], corr.lat[h][flota], siembra.peso[flota],
                                               ctx.lons, ctx.lats)
                fila[f"fss_{h // 24}d"] = metricas.fss(sargazo.astype(float), campo, valido, n)
            filas.append(fila)
    guardar_json(ruta, filas)
    return json.loads(ruta.read_text(encoding="utf-8"))


def elegir_calibracion(filas: list[dict]) -> tuple[float, float, list[dict]]:
    """γ y K_h con el mayor FSS medio (escala de calibración, tres horizontes, casos de
    calibración). Empate → el más cercano a la v0.3 (γ = 1, K_h = 10)."""
    tabla = []
    for g in cfg.REJILLA_GAMMA:
        for kh in cfg.REJILLA_KH:
            v = [f[f"fss_{k}d"] for f in filas if f["gamma"] == g and f["kh"] == kh for k in cfg.HORIZONTES_D]
            v = [x for x in v if x is not None and np.isfinite(x)]
            tabla.append({"gamma": g, "kh": kh, "fss_medio": float(np.mean(v)) if v else float("nan"), "n": len(v)})
    validas = [t for t in tabla if np.isfinite(t["fss_medio"])]
    mejor = max(validas, key=lambda t: (round(t["fss_medio"], 6), -abs(t["gamma"] - 1) - abs(np.log10(t["kh"] / 10))))
    return mejor["gamma"], mejor["kh"], tabla


# ---------------------------------------------------------------------------
# Experimentos de un caso
# ---------------------------------------------------------------------------
def _disponibles(forz) -> dict:
    return {"oleaje": True, "corriente": forz.corriente is not None, "viento": forz.viento is not None}


def procesar_caso(caso, ctx: Contexto, det, archivo_afai, forz, lista: list[Experimento], cache: Path,
                  registrar, extra_semar=None) -> dict:
    ruta = experimentos.ruta_resultado(caso, cache)
    firma = [asdict(e) for e in lista]
    if ruta.is_file():
        previo = json.loads(ruta.read_text(encoding="utf-8"))
        # Se reutiliza si los experimentos y los forzamientos disponibles son los mismos.
        if previo.get("experimentos") == firma and previo.get("disponibles") == _disponibles(forz):
            return previo
    t = time.perf_counter()
    _, sarg0 = det.dia(caso.t0)
    siembra = experimentos.sembrar(sarg0, ctx.lons, ctx.lats)
    obs = {24 * k: det.dia(caso.t0 + timedelta(days=k)) for k in cfg.HORIZONTES_D}
    e0 = experimentos.correr(lista[0], siembra, forz)
    filas, filas_costa, campos_fig = [], [], {}
    vectores = experimentos.mcc_caso(ctx, caso, archivo_afai)
    filas_mcc = []
    corridas = {}
    for exp in lista + ([extra_semar[0]] if extra_semar else []):
        f_exp = extra_semar[1] if extra_semar and exp is extra_semar[0] else forz
        corr = e0 if not exp.mover else experimentos.correr(exp, siembra, f_exp)
        corridas[exp.id] = corr
        for h, (valido, sargazo) in obs.items():
            base = {"caso": caso.id, "t0": caso.t0.isoformat(), "conjunto": caso.conjunto, "experimento": exp.id,
                    "horizonte_d": h // 24}
            if corr is None:
                filas.append({**base, "disponible": False})
                continue
            flota = e0.estado[h] == 0
            campo_e0 = experimentos.a_pixeles(e0.lon[h][flota], e0.lat[h][flota], siembra.peso[flota],
                                              ctx.lons, ctx.lats)
            fila, campo = experimentos.metricas_horizonte(ctx, corr, siembra, h, valido, sargazo, campo_e0)
            filas.append({**base, "disponible": True, **fila})
            for c in experimentos.costa_horizonte(ctx, corr, siembra, h, valido, sargazo):
                filas_costa.append({**base, **c})
            if exp.id in ("E0", "E2", "E3", "E4") or (extra_semar and exp is extra_semar[0]):
                campos_fig[f"{exp.id}_{h // 24}"] = campo
        # MCC: desplazamiento del modelo en 24 h desde cada plantilla.
        if vectores:
            for dia in sorted({v["dia"] for v in vectores}):
                vs = [v for v in vectores if v["dia"] == dia]
                lon = np.array([v["lon"] for v in vs])
                lat = np.array([v["lat"] for v in vs])
                fin = experimentos.desplazamiento_modelo(exp, f_exp, lon, lat, cfg.HORA_IMAGEN_UTC + 24.0 * dia)
                for v, k in zip(vs, range(len(vs))):
                    fila = {"caso": caso.id, "conjunto": caso.conjunto, "experimento": exp.id, **v}
                    if fin is None:
                        fila["disponible"] = False
                    else:
                        d = metricas.vector_km((lon[k], lat[k]), (fin[0][k], fin[1][k]))
                        fila.update({"disponible": True, "este_sim_km": float(d[0]), "norte_sim_km": float(d[1])})
                    filas_mcc.append(fila)
    resultado = {
        "caso": {**caso.fila()},
        "experimentos": firma,
        "forzamientos": forz.resumen,
        "forzamientos_completos": forz.corriente is not None and forz.viento is not None,
        "disponibles": _disponibles(forz),
        "particulas": int(siembra.lon.size), "pixeles_t0": siembra.pixeles,
        "filas": filas, "costa": filas_costa, "mcc": filas_mcc,
        "duracion_s": round(time.perf_counter() - t, 1),
    }
    guardar_json(ruta, resultado)
    np.savez_compressed(ruta.with_name("campos.npz"), **{k: v.astype(np.float32) for k, v in campos_fig.items()},
                        sargazo_t0=sarg0, **{f"obs_{h // 24}": o[1] for h, o in obs.items()},
                        **{f"valido_{h // 24}": o[0] for h, o in obs.items()})
    registrar(f"  {caso.id} ({caso.conjunto}): {len(filas)} filas, {len(filas_mcc)} vectores MCC "
              f"en {resultado['duracion_s']} s")
    return resultado


def comparar_semar(cache: Path, registrar) -> dict:
    """¿Coincide el dirmarea.txt de SEMAR con el oleaje real (MFWAM) del 01/10/2026?"""
    from src.config import DIR_SEMAR
    from validacion.dirmarea import mascara_semar, nodos_descarga, plantilla, recuadro_modelo
    from validacion.openmeteo import OLEAJE, descargar_serie
    from src.ingestion.validador import validar_conjunto
    from src.model.campos import CamposOleaje
    base = plantilla()
    mar = mascara_semar(base)
    ii, jj, lons, lats = nodos_descarga(base, OLEAJE.paso, mar)
    f = cfg.FECHA_DIRMAREA_SEMAR
    serie = descargar_serie(OLEAJE, lons, lats, f, f + timedelta(days=experimentos.DIAS_DESCARGA), cache, registrar)
    _, conj = validar_conjunto(DIR_SEMAR)
    semar = CamposOleaje(conj)
    dentro = recuadro_modelo(base)[ii, jj]
    filas = []
    for h in (0, 24, 48, 72, 96, 120):
        k = serie.tiempos.index(experimentos.utc(f) + timedelta(hours=h))
        hs, ds = semar.ola(lons[dentro], lats[dentro], h)
        hr = serie.valores["wind_wave_height"][k][dentro]
        dr = serie.valores["wind_wave_direction"][k][dentro]
        ok = np.isfinite(hs) & np.isfinite(hr) & np.isfinite(dr)
        dif_dir = np.abs((ds[ok] - dr[ok] + 180) % 360 - 180)
        filas.append({"hora": h, "nodos": int(ok.sum()),
                      "altura_semar_media_m": float(hs[ok].mean()), "altura_real_media_m": float(hr[ok].mean()),
                      "sesgo_altura_m": float((hs[ok] - hr[ok]).mean()),
                      "rmse_altura_m": float(np.sqrt(((hs[ok] - hr[ok]) ** 2).mean())),
                      "correlacion_altura": float(np.corrcoef(hs[ok], hr[ok])[0, 1]) if ok.sum() > 2 else float("nan"),
                      "dif_direccion_mediana": float(np.median(dif_dir)),
                      "dif_direccion_p90": float(np.percentile(dif_dir, 90)),
                      "direccion_semar_media": float(np.degrees(np.arctan2(np.sin(np.radians(ds[ok])).mean(),
                                                                            np.cos(np.radians(ds[ok])).mean())) % 360),
                      "direccion_real_media": float(np.degrees(np.arctan2(np.sin(np.radians(dr[ok])).mean(),
                                                                           np.cos(np.radians(dr[ok])).mean())) % 360)})
    return {"fecha": f.isoformat(), "fuente_real": "Open-Meteo meteofrance_wave (MFWAM), ola de viento",
            "comparacion": filas}


def cargar_resultado(caso, cache: Path = cfg.DIR_CACHE) -> dict | None:
    ruta = experimentos.ruta_resultado(caso, cache)
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None
