"""Experimentos E0–E5 por caso y sus métricas.

  E0  Persistencia: el sargazo de t0 se queda donde está (referencia mínima).
  E1  Solo browniano: γ = 0, K_h = 10 m²/s.
  E2  PMS v0.3 tal cual: γ = 1, K_h = 10 m²/s, ola de dirmarea.txt real.
  E3  PMS con γ y K_h calibrados SOLO con los casos de calibración.
  E4  Experimental: corriente superficial total de SMOC (euleriana + marea + Stokes) + browniano.
  E5  Experimental: corriente de SMOC sin Stokes (euleriana + marea) + α·viento a 10 m
      (α = 1, 2 y 3 %) + ola del modelo (γ = 1): la deriva por oleaje se cuenta una sola vez.

Todos usan las mismas partículas iniciales (sembradas en proporción a los píxeles con
sargazo en t0), la misma semilla y el mismo integrador del producto (src.model.simulacion.integrar).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from src.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from src.ingestion.validador import validar_conjunto
from src.model import costa
from src.model.campos import CamposOleaje
from src.model.simulacion import A_FLOTE, VARADA, integrar
from validacion import afai, metricas
from validacion import config as cfg
from validacion import copernicus
from validacion.campos import CamposEncadenados, CamposSuma, CamposVectoriales, utc, vectoriales_desde_serie
from validacion.dirmarea import (
    escribir, horas_bloques, mascara_semar, nodos_descarga, oleaje_desde_rejilla, plantilla, recuadro_modelo,
)
from validacion.openmeteo import VIENTO, CuotaAgotada, descargar_serie

DOMINIO = (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)
HORAS = 24 * max(cfg.HORIZONTES_D)
# Se descarga t0 … t0 + 10 días: el segundo dirmarea.txt (fecha base t0 + 5 d) necesita sus
# 120 h completas aunque la simulación termine en t0 + 7 d 18 UTC.
DIAS_DESCARGA = 10
MIN_PIXELES_COSTA = 3                              # evento de costa: ≥ 3 píxeles (o su equivalente simulado)
MIN_OBSERVABLE_COSTA = 0.30                        # tramo evaluable si ≥ 30 % de su banda está despejada


@dataclass(frozen=True)
class Experimento:
    id: str
    nombre: str
    gamma: float = 0.0            # factor de la ola (deriva de Stokes del producto)
    kh: float = cfg.KH_V03
    corriente: float = 0.0        # factor de la corriente
    viento: float = 0.0           # fracción del viento a 10 m
    mover: bool = True


def experimentos(gamma_cal: float | None, kh_cal: float | None) -> list[Experimento]:
    """Lista de experimentos. Sin calibración completa (gamma_cal None) E3 queda pendiente y no
    se corre: nunca se usan parámetros de una calibración parcial."""
    lista = [
        Experimento("E0", "Persistencia", mover=False),
        Experimento("E1", "Solo browniano", gamma=0.0),
        Experimento("E2", "PMS v0.3 (γ = 1, K_h = 10)", gamma=cfg.GAMMA_V03, kh=cfg.KH_V03),
    ]
    if gamma_cal is not None:
        lista.append(Experimento("E3", f"PMS calibrado (γ = {gamma_cal:g}, K_h = {kh_cal:g})",
                                 gamma=gamma_cal, kh=kh_cal))
    lista.append(Experimento("E4", "Corriente SMOC total + browniano", corriente=1.0))
    for a in cfg.FACTORES_VIENTO:
        lista.append(Experimento(f"E5-{a * 100:.0f}", f"Corriente sin Stokes + viento {a * 100:.0f} % + ola",
                                 gamma=1.0, corriente=1.0, viento=a))
    return lista


# ---------------------------------------------------------------------------
# Forzamientos
# ---------------------------------------------------------------------------
@dataclass
class Forzamientos:
    oleaje: object                        # CamposEncadenados de dos dirmarea.txt (o el de SEMAR)
    corriente_total: object | None        # SMOC utotal/vtotal: euleriana + marea + Stokes (E4)
    corriente_sin_stokes: object | None   # SMOC uo + utide (E5: la ola va aparte)
    viento: object | None
    resumen: dict
    con_extra: bool = True

    @property
    def corriente(self):
        return self.corriente_total


def _campos_rejilla(rej, u: np.ndarray, v: np.ndarray, inicio) -> CamposVectoriales:
    """(u, v) [tiempo, lat, lon] de una rejilla de Copernicus como campos del integrador, a su
    resolución nativa, con el tiempo en horas desde `inicio`."""
    horas = np.array([(t - inicio).total_seconds() / 3600.0 for t in rej.tiempos])
    return CamposVectoriales(float(rej.lons[0]), float(rej.lats[0]), float(rej.lons[1] - rej.lons[0]),
                             float(rej.lats[1] - rej.lats[0]), horas, u.astype(np.float64), v.astype(np.float64))


def _verificar_stokes(rej, destino, base, desde) -> dict:
    """Compara la deriva de Stokes del producto de oleaje (VSDX/VSDY, espectro completo) con la
    fórmula del modelo (ola de viento con T supuesto = 4·√H y con el T real VTM01_WW) en los
    nodos del modelo, cada 3 h de t0 a t0 + 7 d."""
    from src.config import COEF_PERIODO, COEF_STOKES, GRAVEDAD
    di, dj = np.nonzero(destino)
    x, y = base.lons[dj], base.lats[di]
    cocientes, cocientes_t, angulos, periodos = [], [], [], []
    for k, t in enumerate(rej.tiempos):
        if t > desde + timedelta(days=max(cfg.HORIZONTES_D)):
            break
        h, d, tm, sx, sy = copernicus.a_puntos(
            [rej.valores[v][k] for v in ("VHM0_WW", "VMDR_WW", "VTM01_WW", "VSDX", "VSDY")], rej.lons, rej.lats, x, y)
        ok = np.isfinite(h) & np.isfinite(sx) & np.isfinite(tm) & (h > 0.1) & (tm > 0.5)
        if not ok.any():
            continue
        producto = np.hypot(sx[ok], sy[ok])
        cocientes.append(producto / (COEF_STOKES * np.sqrt(h[ok])))
        cocientes_t.append(producto / (2 * np.pi ** 3 * h[ok] ** 2 / (GRAVEDAD * tm[ok] ** 3)))
        periodos.append(tm[ok] / (COEF_PERIODO * np.sqrt(h[ok])))
        # Dirección de la deriva del producto vs. la del modelo (hacia donde va la ola de viento).
        hacia = np.radians(d[ok] + 180.0)
        dif = np.degrees(np.arctan2(sx[ok], sy[ok]) - np.arctan2(np.sin(hacia), np.cos(hacia)))
        angulos.append(np.abs((dif + 180) % 360 - 180))
    if not cocientes:
        return {}
    c, ct, a, pr = (np.concatenate(z) for z in (cocientes, cocientes_t, angulos, periodos))
    return {"producto_entre_formula_T_supuesto_mediana": round(float(np.median(c)), 3),
            "producto_entre_formula_T_real_mediana": round(float(np.median(ct)), 3),
            "dif_direccion_mediana": round(float(np.median(a)), 1),
            "T_real_entre_T_supuesto_mediana": round(float(np.median(pr)), 3)}


def preparar_forzamientos(caso, cache: Path = cfg.DIR_CACHE, registrar=print, con_extra: bool = True) -> Forzamientos:
    """Ola de viento real de Copernicus Marine escrita en dos dirmarea.txt encadenados (validados
    por el producto) y, si se pide, corriente SMOC (Copernicus Marine) y viento ERA5 (Open-Meteo)."""
    base = plantilla()
    mar = mascara_semar(base)
    destino = mar & recuadro_modelo(base)
    desde = utc(caso.t0)
    hasta = utc(caso.t0 + timedelta(days=DIAS_DESCARGA))
    ds_ola = copernicus.elegir_oleaje(desde, hasta, cache)
    rej = copernicus.descargar(ds_ola, copernicus.VARS_OLEAJE, desde, hasta, cache, registrar)
    dir_caso = cache / "casos" / caso.id
    tramos = []
    resumen = {"fuentes": {"oleaje": ds_ola, "oleaje_resolucion_grados": round(rej.resolucion, 4)}, "oleaje": {}}
    for inicio_d in (0, 5):
        fecha_base = caso.t0 + timedelta(days=inicio_d)
        alt, direc = oleaje_desde_rejilla(rej, destino, fecha_base, base)
        carpeta = dir_caso / f"dirmarea_{fecha_base.isoformat()}"
        escribir(carpeta / "dirmarea.txt", fecha_base, horas_bloques(), alt, direc, base)
        reporte, conjunto = validar_conjunto(carpeta)
        if not reporte.valido:
            errores = [h.detalle for v in reporte.verificaciones for h in v.hallazgos if h.nivel == "error"]
            raise RuntimeError(f"El dirmarea.txt generado para {caso.id} no pasó el validador: {errores}")
        tramos.append((24.0 * inicio_d, CamposOleaje(conjunto)))
        resumen["oleaje"][fecha_base.isoformat()] = {
            "altura_media_m": round(float(np.nanmean(alt)), 3), "altura_max_m": round(float(np.nanmax(alt)), 3)}
    resumen["stokes_y_periodo"] = _verificar_stokes(rej, destino, base, desde)
    oleaje = CamposEncadenados(tramos)
    del rej

    total = sin_stokes = viento = None
    if con_extra:
        try:
            ds_cor = copernicus.elegir_corriente(desde, hasta, cache)
            rc = copernicus.descargar(ds_cor, copernicus.VARS_CORRIENTE, desde, hasta, cache, registrar)
            total = _campos_rejilla(rc, rc.valores["utotal"], rc.valores["vtotal"], desde)
            sin_stokes = _campos_rejilla(rc, rc.valores["uo"] + rc.valores["utide"],
                                         rc.valores["vo"] + rc.valores["vtide"], desde)
            rapidez = np.hypot(rc.valores["utotal"], rc.valores["vtotal"])
            resumen["fuentes"]["corriente"] = ds_cor
            resumen["corriente"] = {"media_ms": round(float(np.nanmean(rapidez)), 3),
                                    "p95_ms": round(float(np.nanpercentile(rapidez, 95)), 3)}
            del rc, rapidez
        except copernicus.SinCobertura as e:
            resumen["corriente"] = f"sin datos: {e}"
        try:
            gi, gj, glon, glat = nodos_descarga(base, VIENTO.paso, mar)
            # El histórico de ERA5 tiene unos días de retraso: no se piden fechas futuras.
            fin = min(caso.t0 + timedelta(days=DIAS_DESCARGA), date.today() - timedelta(days=1))
            if fin < caso.t0 + timedelta(days=8):
                resumen["viento"] = f"sin datos: ERA5 aún no cubre hasta {caso.t0 + timedelta(days=8)}"
            else:
                sv = descargar_serie(VIENTO, glon, glat, caso.t0, fin, cache, registrar)
                if np.isnan(sv.valores["wind_speed_10m"][: 24 * 8]).all(axis=1).any():
                    resumen["viento"] = "sin datos para todo el periodo"
                else:
                    viento = vectoriales_desde_serie(sv, gi, gj, VIENTO.paso, destino, base.lons, base.lats,
                                                     desde, 24 * 8 - 1, "desde")
                    resumen["fuentes"]["viento"] = "Open-Meteo era5"
                    r = np.hypot(viento.u, viento.v)
                    resumen["viento"] = {"media_ms": round(float(np.nanmean(r)), 3),
                                         "p95_ms": round(float(np.nanpercentile(r, 95)), 3)}
        except CuotaAgotada as e:
            resumen["viento"] = f"no descargado: {e}"
            registrar(f"  {caso.id}: {e}")
    return Forzamientos(oleaje, total, sin_stokes, viento, resumen, con_extra)


def campos_de(exp: Experimento, f: Forzamientos):
    """Campos (u, v) del experimento y el γ con el que los multiplica el integrador.

    E4 usa la corriente total de SMOC (ya trae Stokes y marea). E5 usa la corriente sin Stokes
    (euleriana + marea) más el viento y la ola del modelo, para no contar la deriva por oleaje
    dos veces."""
    if exp.corriente == 0 and exp.viento == 0:
        return f.oleaje, exp.gamma
    corriente = f.corriente_sin_stokes if exp.viento else f.corriente_total
    if corriente is None or (exp.viento and f.viento is None):
        return None, None
    comp = [(exp.corriente, corriente)]
    if exp.viento:
        comp.append((exp.viento, f.viento))
    if exp.gamma:
        comp.append((exp.gamma, f.oleaje))
    return CamposSuma(comp), 1.0


# ---------------------------------------------------------------------------
# Siembra y campos simulados
# ---------------------------------------------------------------------------
@dataclass
class Siembra:
    lon: np.ndarray
    lat: np.ndarray
    peso: np.ndarray        # 1 / partículas del píxel de origen: cada píxel con sargazo pesa 1
    pixeles: int


def sembrar(sargazo: np.ndarray, lons: np.ndarray, lats: np.ndarray, n: int = cfg.PARTICULAS,
            semilla: int = cfg.SEMILLA) -> Siembra:
    """Reparte n partículas (al menos una por píxel) entre los píxeles con sargazo, al azar
    dentro de cada píxel; las que caen en la tierra del modelo van al centro del píxel."""
    rng = np.random.default_rng(semilla)
    pi, pj = np.nonzero(sargazo)
    p = pi.size
    n = max(n, p)
    por_pixel = np.full(p, n // p)
    por_pixel[rng.permutation(p)[: n - por_pixel.sum()]] += 1
    i = np.repeat(pi, por_pixel)
    j = np.repeat(pj, por_pixel)
    dlon, dlat = float(lons[1] - lons[0]), float(lats[1] - lats[0])
    lon = lons[j] + (rng.random(n) - 0.5) * dlon
    lat = lats[i] + (rng.random(n) - 0.5) * dlat
    tierra = costa.en_tierra(lon, lat)
    lon[tierra], lat[tierra] = lons[j[tierra]], lats[i[tierra]]
    return Siembra(lon, lat, 1.0 / np.repeat(por_pixel, por_pixel), p)


def a_pixeles(lon, lat, peso, lons, lats) -> np.ndarray:
    """Suma de pesos por píxel AFAI, recortada a 1 (fracción del píxel con sargazo)."""
    dlon, dlat = float(lons[1] - lons[0]), float(lats[1] - lats[0])
    i = np.rint((lat - lats[0]) / dlat).astype(np.int64)
    j = np.rint((lon - lons[0]) / dlon).astype(np.int64)
    ok = (i >= 0) & (i < lats.size) & (j >= 0) & (j < lons.size)
    campo = np.zeros((lats.size, lons.size))
    np.add.at(campo, (i[ok], j[ok]), peso[ok])
    return np.minimum(campo, 1.0)


@dataclass
class Corrida:
    """Posiciones y estados a cada horizonte (h = 24·k)."""
    lon: dict
    lat: dict
    estado: dict


def correr(exp: Experimento, siembra: Siembra, f: Forzamientos) -> Corrida | None:
    horizontes = [24 * k for k in cfg.HORIZONTES_D]
    if not exp.mover:
        e = np.full(siembra.lon.size, A_FLOTE, dtype=np.int8)
        return Corrida({h: siembra.lon for h in horizontes}, {h: siembra.lat for h in horizontes},
                       {h: e for h in horizontes})
    campos, gamma = campos_de(exp, f)
    if campos is None:
        return None
    rng = np.random.default_rng(cfg.SEMILLA)
    tr = integrar(campos, siembra.lon, siembra.lat, HORAS, gamma, exp.kh, rng, dominio=DOMINIO,
                  t_inicio_h=float(cfg.HORA_IMAGEN_UTC))
    estados = {}
    for h in horizontes:
        e = np.full(siembra.lon.size, A_FLOTE, dtype=np.int8)
        e[(tr.hora_varada >= 0) & (tr.hora_varada <= h)] = VARADA
        e[(tr.hora_fuera >= 0) & (tr.hora_fuera <= h)] = 2
        estados[h] = e
    return Corrida({h: tr.lon[h] for h in horizontes}, {h: tr.lat[h] for h in horizontes}, estados)


def desplazamiento_modelo(exp: Experimento, f: Forzamientos, lon, lat, t_inicio_h: float, horas: int = 24):
    """Desplazamiento determinista (K_h = 0) de puntos sueltos durante `horas`."""
    if not exp.mover:
        return np.zeros(np.size(lon)), np.zeros(np.size(lon))
    campos, gamma = campos_de(exp, f)
    if campos is None:
        return None
    tr = integrar(campos, np.asarray(lon, float), np.asarray(lat, float), horas, gamma, 0.0,
                  np.random.default_rng(0), dominio=DOMINIO, t_inicio_h=t_inicio_h)
    return tr.lon[-1], tr.lat[-1]


# ---------------------------------------------------------------------------
# Métricas de un caso
# ---------------------------------------------------------------------------
class Contexto:
    """Rejilla AFAI, máscaras y tramos de costa de cada píxel (se calcula una vez)."""

    def __init__(self, mascaras):
        self.m = mascaras
        self.lons, self.lats = mascaras.lons, mascaras.lats
        self.glon, self.glat = np.meshgrid(self.lons, self.lats)
        self.km_px = afai.km_por_pixel(self.lons, self.lats)
        self.regiones = afai.regiones_producto(self.lons, self.lats)
        self.km_lado = float(np.sqrt(self.km_px[0] * self.km_px[1]))
        self.ventanas = {e: metricas.ventana_impar(e, self.km_lado) for e in cfg.ESCALAS_FSS_KM}
        util = mascaras.mar_util
        d = np.full(util.shape, np.inf)
        d[util] = costa.distancia_costa_km(self.glon[util], self.glat[util])
        self.banda = util & (d <= cfg.BANDA_COSTA_KM)
        self.zona_px = np.full(util.shape, "", dtype=object)
        self.zona_px[self.banda] = costa.zona_costera(self.glon[self.banda], self.glat[self.banda])
        self.zonas = [z["id"] for z in costa.ZONAS]


def metricas_horizonte(ctx: Contexto, corrida: Corrida, siembra: Siembra, h: int, obs_valido, obs_sargazo,
                       e0_campo: np.ndarray) -> tuple[dict, np.ndarray]:
    flota = corrida.estado[h] == A_FLOTE
    campo = a_pixeles(corrida.lon[h][flota], corrida.lat[h][flota], siembra.peso[flota], ctx.lons, ctx.lats)
    obs = obs_sargazo.astype(float)
    fila = {f"fss_{e}km": metricas.fss(obs, campo, obs_valido, n) for e, n in ctx.ventanas.items()}
    fila["fss_util"] = metricas.fss_uniforme(obs, obs_valido)
    c_obs = metricas.centroide(obs, obs_valido, ctx.glon, ctx.glat)
    c_sim = metricas.centroide(campo, obs_valido, ctx.glon, ctx.glat)
    c_e0 = metricas.centroide(e0_campo, obs_valido, ctx.glon, ctx.glat)
    fila["error_centroide_km"] = metricas.distancia_km(c_obs, c_sim) if c_obs and c_sim else float("nan")
    if c_obs and c_sim and c_e0:
        v_obs, v_sim = metricas.vector_km(c_e0, c_obs), metricas.vector_km(c_e0, c_sim)
        fila["desplazamiento_obs_km"] = float(np.hypot(*v_obs))
        fila["rumbo_obs"] = metricas.rumbo(v_obs)
        fila["desplazamiento_sim_km"] = float(np.hypot(*v_sim))
        fila["error_direccion"] = (metricas.diferencia_angular(v_obs, v_sim)
                                   if np.hypot(*v_obs) >= 5 and np.hypot(*v_sim) >= 1 else float("nan"))
    peso_total = siembra.peso.sum()
    for nombre, cod in (("a_flote", A_FLOTE), ("varada", VARADA), ("fuera", 2)):
        fila[f"masa_{nombre}"] = float(siembra.peso[corrida.estado[h] == cod].sum() / peso_total)
    return fila, campo


def costa_horizonte(ctx: Contexto, corrida: Corrida, siembra: Siembra, h: int, obs_valido, obs_sargazo) -> list[dict]:
    """Por tramo: ¿hay sargazo pegado a la costa en la observación y en la simulación?"""
    filas = []
    est = corrida.estado[h]
    lon, lat, peso = corrida.lon[h], corrida.lat[h], siembra.peso
    sim = {z: 0.0 for z in ctx.zonas}
    flota = est == A_FLOTE
    if flota.any():
        dlon, dlat = float(ctx.lons[1] - ctx.lons[0]), float(ctx.lats[1] - ctx.lats[0])
        i = np.clip(np.rint((lat[flota] - ctx.lats[0]) / dlat).astype(int), 0, ctx.lats.size - 1)
        j = np.clip(np.rint((lon[flota] - ctx.lons[0]) / dlon).astype(int), 0, ctx.lons.size - 1)
        en_banda = ctx.banda[i, j]
        for z, w in zip(ctx.zona_px[i[en_banda], j[en_banda]], peso[flota][en_banda]):
            sim[z] += w
    varadas = est == VARADA
    if varadas.any():
        for z, w in zip(costa.zona_costera(lon[varadas], lat[varadas]), peso[varadas]):
            sim[z] += w
    for z in ctx.zonas:
        en_z = ctx.banda & (ctx.zona_px == z)
        total = int(en_z.sum())
        if total == 0:
            continue
        despejado = float((en_z & obs_valido).sum()) / total
        filas.append({"zona": z, "observable": despejado >= MIN_OBSERVABLE_COSTA,
                      "observado": int((en_z & obs_valido & obs_sargazo).sum()) >= MIN_PIXELES_COSTA,
                      "pronosticado": sim[z] >= MIN_PIXELES_COSTA, "despejado": round(despejado, 3)})
    return filas


def mcc_caso(ctx: Contexto, caso, archivo_afai: afai.ArchivoAfai) -> list[dict]:
    """Vectores MCC entre imágenes de días consecutivos t0 … t0 + 7."""
    vectores = []
    previo = None
    for k in range(max(cfg.HORIZONTES_D) + 1):
        fecha = caso.t0 + timedelta(days=k)
        a = archivo_afai.dia(fecha)
        actual = None if a is None else (fecha, afai.detectar(a, ctx.m.mar_util, regiones=ctx.regiones))
        if previo is not None and actual is not None and (actual[0] - previo[0]).days == 1:
            da, db = previo[1], actual[1]
            campo_a = np.clip(np.nan_to_num(da.delta), 0, 1e-3)
            campo_b = np.clip(np.nan_to_num(db.delta), 0, 1e-3)
            for v in metricas.mcc(campo_a, da.valido, da.sargazo, campo_b, db.valido, cfg.MCC_PLANTILLA_PX,
                                  cfg.MCC_BUSQUEDA_PX, cfg.MCC_MIN_SARGAZO, cfg.MCC_MIN_VALIDOS,
                                  cfg.MCC_MIN_CORRELACION):
                vectores.append({"dia": (previo[0] - caso.t0).days, "lon": float(ctx.lons[v.j]),
                                 "lat": float(ctx.lats[v.i]), "este_km": v.dj * ctx.km_px[0],
                                 "norte_km": v.di * ctx.km_px[1], "correlacion": v.correlacion})
        previo = actual
    return vectores


def ruta_resultado(caso, cache: Path = cfg.DIR_CACHE) -> Path:
    return cache / "casos" / caso.id / "resultado.json"
