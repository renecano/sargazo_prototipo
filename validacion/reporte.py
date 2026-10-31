"""Tablas, figuras, reporte y página /validacion a partir de los resultados por caso.

Nada de este módulo escribe un número a mano: toda cifra del reporte (docs/validacion.md),
de la página /validacion y del bloque del README sale de los resultados que guarda
validacion/ejecutar.py.
"""
from __future__ import annotations

import csv
import html
import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402

from src.config import VERSION_APP, VERSION_MODELO  # noqa: E402
from validacion import config as cfg  # noqa: E402
from validacion import metricas  # noqa: E402

# Paleta (rol → color). Tinta y papel de la interfaz «carta náutica»; series de la paleta
# categórica validada de la guía de visualización (azul, naranja) y gris para la referencia.
TINTA, TINTA_2, PAPEL = "#1d3557", "#52514e", "#fbf6ea"
GRIS_REF = "#8a8780"
AZUL, NARANJA = "#2a78d6", "#eb6834"
NUBE, TIERRA = "#dcd6c8", "#e9dcbf"
AZULES = ListedColormap(["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"])

NOMBRES = {
    "E0": "E0 Persistencia", "E1": "E1 Solo browniano", "E2": "E2 PMS v0.3", "E3": "E3 PMS calibrado",
    "E4": "E4 Corriente + browniano", "E5-1": "E5 Corriente + viento 1 % + ola",
    "E5-2": "E5 Corriente + viento 2 % + ola", "E5-3": "E5 Corriente + viento 3 % + ola",
    "E2-SEMAR": "E2 con el dirmarea.txt de SEMAR",
}
ORDEN = ["E0", "E1", "E2", "E3", "E4", "E5-1", "E5-2", "E5-3"]


def _fuente() -> str:
    """Primera fuente disponible (IBM Plex Sans como la interfaz; si no, la del sistema)."""
    from matplotlib import font_manager
    disponibles = {f.name for f in font_manager.fontManager.ttflist}
    return next((f for f in ("IBM Plex Sans", "Segoe UI", "DejaVu Sans") if f in disponibles), "sans-serif")


def _estilo():
    plt.rcParams.update({
        "font.family": _fuente(), "font.size": 9,
        "axes.edgecolor": TINTA_2, "axes.labelcolor": TINTA, "xtick.color": TINTA_2, "ytick.color": TINTA_2,
        "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": TINTA,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e4e0d6",
        "grid.linewidth": 0.6, "figure.facecolor": "white", "savefig.facecolor": "white", "savefig.dpi": 110,
    })


def _f(v, d=2):
    return "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{d}f}"


def _escribir_csv(ruta: Path, filas: list[dict]):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = []
    for f in filas:
        for k in f:
            if k not in campos:
                campos.append(k)
    with ruta.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        for f in filas:
            w.writerow({k: (round(v, 4) if isinstance(v, float) and np.isfinite(v) else ("" if isinstance(v, float) else v))
                        for k, v in f.items()})


# ---------------------------------------------------------------------------
# Agregados
# ---------------------------------------------------------------------------
def _valor(f, k):
    v = f.get(k)
    return float("nan") if v is None else float(v)


def resumen_fss(filas: list[dict], conjuntos=("evaluacion", "calibracion", "todos")) -> list[dict]:
    salida = []
    for conj in conjuntos:
        sel = [f for f in filas if f.get("disponible") and (conj == "todos" and f["conjunto"] != "semar"
                                                            or f["conjunto"] == conj)]
        casos = sorted({f["caso"] for f in sel})
        for exp in ORDEN:
            for k in cfg.HORIZONTES_D:
                for e in cfg.ESCALAS_FSS_KM:
                    clave = f"fss_{e}km"
                    por_caso = {f["caso"]: _valor(f, clave) for f in sel if f["experimento"] == exp and f["horizonte_d"] == k}
                    base = {f["caso"]: _valor(f, clave) for f in sel if f["experimento"] == "E0" and f["horizonte_d"] == k}
                    if not por_caso:
                        continue
                    v = np.array([por_caso[c] for c in casos if c in por_caso])
                    m, lo, hi, n = metricas.bootstrap_media(v, cfg.REMUESTREOS_BOOTSTRAP, cfg.NIVEL_CONFIANZA)
                    dif = np.array([por_caso[c] - base[c] for c in casos if c in por_caso and c in base])
                    dm, dlo, dhi, _ = metricas.bootstrap_media(dif, cfg.REMUESTREOS_BOOTSTRAP, cfg.NIVEL_CONFIANZA)
                    dif = dif[np.isfinite(dif)]
                    util = [_valor(f, "fss_util") for f in sel if f["experimento"] == exp and f["horizonte_d"] == k]
                    salida.append({"conjunto": conj, "experimento": exp, "horizonte_d": k, "escala_km": e, "casos": n,
                                   "fss_medio": m, "ic_inf": lo, "ic_sup": hi,
                                   "dif_vs_E0": dm, "dif_ic_inf": dlo, "dif_ic_sup": dhi,
                                   "casos_mejor_que_E0": int((dif > 0).sum()), "casos_comparados": int(dif.size),
                                   "fss_util_medio": float(np.nanmean(util)) if util else float("nan")})
    return salida


def resumen_mensual(dias: list[dict]) -> list[dict]:
    """Por mes: imágenes, mediana de la fracción despejada y de la fracción de píxeles
    despejados con sargazo. El mes más bajo acota el piso de ruido de la detección."""
    meses: dict = {}
    for d in dias:
        meses.setdefault((d["fecha"].year, d["fecha"].month), []).append(d)
    salida = []
    for (a, m), g in sorted(meses.items()):
        frac = [x["sargazo"] / x["validos"] for x in g if x["validos"] >= 1000]
        salida.append({"mes": f"{a:04d}-{m:02d}", "imagenes": len(g),
                       "claro_mediano": float(np.median([x["claro"] for x in g])),
                       "fraccion_sargazo_mediana": float(np.median(frac)) if frac else float("nan")})
    return salida


def resumen_centroide(filas: list[dict]) -> list[dict]:
    salida = []
    for conj in ("evaluacion", "todos"):
        sel = [f for f in filas if f.get("disponible") and (conj == "todos" and f["conjunto"] != "semar"
                                                            or f["conjunto"] == conj)]
        for exp in ORDEN:
            for k in cfg.HORIZONTES_D:
                g = [f for f in sel if f["experimento"] == exp and f["horizonte_d"] == k]
                if not g:
                    continue
                err = np.array([_valor(f, "error_centroide_km") for f in g])
                base = {f["caso"]: _valor(f, "error_centroide_km") for f in sel
                        if f["experimento"] == "E0" and f["horizonte_d"] == k}
                dif = np.array([_valor(f, "error_centroide_km") - base.get(f["caso"], np.nan) for f in g])
                m, lo, hi, n = metricas.bootstrap_media(err, cfg.REMUESTREOS_BOOTSTRAP, cfg.NIVEL_CONFIANZA)
                dm, dlo, dhi, _ = metricas.bootstrap_media(dif, cfg.REMUESTREOS_BOOTSTRAP, cfg.NIVEL_CONFIANZA)
                ang = np.array([_valor(f, "error_direccion") for f in g])
                ang = ang[np.isfinite(ang)]
                salida.append({"conjunto": conj, "experimento": exp, "horizonte_d": k, "casos": n,
                               "error_centroide_km": m, "ic_inf": lo, "ic_sup": hi, "dif_vs_E0_km": dm,
                               "dif_ic_inf": dlo, "dif_ic_sup": dhi,
                               "error_direccion_mediano": float(np.median(ang)) if ang.size else float("nan"),
                               "casos_con_direccion": int(ang.size),
                               "masa_varada": float(np.nanmean([_valor(f, "masa_varada") for f in g])),
                               "masa_fuera": float(np.nanmean([_valor(f, "masa_fuera") for f in g]))})
    return salida


def resumen_mcc(vectores: list[dict]) -> list[dict]:
    salida = []
    for conj in ("evaluacion", "todos"):
        sel = [v for v in vectores if v.get("disponible") and (conj == "todos" and v["conjunto"] != "semar"
                                                               or v["conjunto"] == conj)]
        for exp in ORDEN:
            g = [v for v in sel if v["experimento"] == exp]
            if not g:
                continue
            obs = np.array([[v["este_km"], v["norte_km"]] for v in g])
            sim = np.array([[v["este_sim_km"], v["norte_sim_km"]] for v in g])
            l = np.hypot(obs[:, 0], obs[:, 1])
            ls = np.hypot(sim[:, 0], sim[:, 1])
            d = np.hypot(*(obs - sim).T)
            dia = 86.4  # km por día a 1 m/s
            ang = np.array([metricas.diferencia_angular(o, s) for o, s in zip(obs, sim)])
            ang = ang[(l / dia >= 0.05) & (ls / dia >= 0.01)]
            por_caso = {}
            for v, dk, lk in zip(g, d, l):
                a = por_caso.setdefault(v["caso"], [0.0, 0.0])
                a[0] += dk
                a[1] += lk
            lw = np.array([metricas.liu_weisberg(np.array([a[0]]), np.array([a[1]])) for a in por_caso.values()])
            m, lo, hi, n = metricas.bootstrap_media(lw, cfg.REMUESTREOS_BOOTSTRAP, cfg.NIVEL_CONFIANZA)
            salida.append({"conjunto": conj, "experimento": exp, "vectores": len(g), "casos": n,
                           "rapidez_obs_ms": float(l.mean() / dia), "rapidez_sim_ms": float(ls.mean() / dia),
                           "error_vector_ms": float(np.sqrt((d ** 2).mean()) / dia),
                           "error_direccion_mediano": float(np.median(ang)) if ang.size else float("nan"),
                           "liu_weisberg": m, "lw_ic_inf": lo, "lw_ic_sup": hi})
    return salida


def resumen_costa(filas: list[dict]) -> list[dict]:
    salida = []
    for conj in ("evaluacion", "todos"):
        sel = [f for f in filas if f["observable"] and (conj == "todos" and f["conjunto"] != "semar"
                                                       or f["conjunto"] == conj)]
        for exp in ORDEN:
            for k in cfg.HORIZONTES_D:
                c = metricas.Contingencia()
                for f in sel:
                    if f["experimento"] == exp and f["horizonte_d"] == k:
                        c.sumar(bool(f["pronosticado"]), bool(f["observado"]))
                if c.aciertos + c.fallos + c.falsas_alarmas + c.negativos == 0:
                    continue
                salida.append({"conjunto": conj, "experimento": exp, "horizonte_d": k, "aciertos": c.aciertos,
                               "fallos": c.fallos, "falsas_alarmas": c.falsas_alarmas, "negativos": c.negativos,
                               "pod": c.pod, "far": c.far, "csi": c.csi})
    return salida


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------
def figura_fss(resumen: list[dict], ruta: Path, conjunto="evaluacion"):
    _estilo()
    exps = [e for e in ORDEN if any(r["experimento"] == e and r["conjunto"] == conjunto for r in resumen)]
    fig, ejes = plt.subplots(len(cfg.ESCALAS_FSS_KM), len(cfg.HORIZONTES_D), figsize=(10, 7.5), sharey=True, sharex=True)
    for fi, escala in enumerate(cfg.ESCALAS_FSS_KM):
        for ci, k in enumerate(cfg.HORIZONTES_D):
            ax = ejes[fi, ci]
            rs = {r["experimento"]: r for r in resumen if r["conjunto"] == conjunto and r["horizonte_d"] == k
                  and r["escala_km"] == escala}
            e0 = rs.get("E0")
            if e0:
                ax.axvline(e0["fss_medio"], color=GRIS_REF, lw=1.2, ls="--", zorder=1)
            for y, e in enumerate(exps):
                r = rs.get(e)
                if not r or not np.isfinite(r["fss_medio"]):
                    continue
                color = GRIS_REF if e == "E0" else (NARANJA if e == "E2" else AZUL)
                ax.plot([r["ic_inf"], r["ic_sup"]], [y, y], color=color, lw=2, solid_capstyle="round", zorder=2)
                ax.plot(r["fss_medio"], y, "o", ms=6, color=color, mec="white", mew=1.5, zorder=3)
            ax.set_yticks(range(len(exps)))
            ax.set_yticklabels([NOMBRES[e] for e in exps])
            ax.invert_yaxis()
            ax.grid(axis="y", visible=False)
            if fi == 0:
                ax.set_title(f"+{k} días")
            if ci == 0:
                ax.set_ylabel(f"vecindad {escala} km", rotation=90)
            if fi == len(cfg.ESCALAS_FSS_KM) - 1:
                ax.set_xlabel("FSS medio (IC 95 %)")
    n = max((r["casos"] for r in resumen if r["conjunto"] == conjunto), default=0)
    fig.suptitle(f"FSS por experimento y horizonte — {n} casos de evaluación (línea gris: persistencia E0)",
                 color=TINTA, fontsize=11, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)


def figura_caso(npz: Path, caso: dict, filas: list[dict], lons, lats, tierra, ruta: Path,
                columnas=("E0", "E2", "E3", "E4")):
    _estilo()
    with np.load(npz) as z:
        datos = {k: z[k] for k in z.files}
    columnas = [c for c in columnas if f"{c}_{cfg.HORIZONTES_D[0]}" in datos]
    if "E2-SEMAR_3" in datos:
        columnas = ["E0", "E2-SEMAR", "E2", "E4"]
        columnas = [c for c in columnas if f"{c}_{cfg.HORIZONTES_D[0]}" in datos]
    ext = [lons[0], lons[-1], lats[0], lats[-1]]
    fig, ejes = plt.subplots(len(cfg.HORIZONTES_D), len(columnas) + 1, figsize=(2.6 * (len(columnas) + 1), 7.2))
    fss = {(f["experimento"], f["horizonte_d"]): f.get("fss_25km") for f in filas if f.get("disponible")}
    for fi, k in enumerate(cfg.HORIZONTES_D):
        valido, obs = datos[f"valido_{k}"], datos[f"obs_{k}"]
        fondo = np.where(tierra, 2, np.where(valido, 0, 1)).astype(float)
        for ci, col in enumerate(["obs", *columnas]):
            ax = ejes[fi, ci]
            ax.imshow(fondo, origin="lower", extent=ext, cmap=ListedColormap(["white", NUBE, TIERRA]), vmin=0, vmax=2,
                      interpolation="nearest")
            if col == "obs":
                ax.imshow(np.where(datos["sargazo_t0"] & ~obs, 1.0, np.nan), origin="lower", extent=ext,
                          cmap=ListedColormap([GRIS_REF]), interpolation="nearest", alpha=0.5)
                ax.imshow(np.where(obs, 1.0, np.nan), origin="lower", extent=ext, cmap=ListedColormap([NARANJA]),
                          interpolation="nearest")
                titulo = f"Observado +{k} d" if fi else f"Observado +{k} d\n(gris: t0)"
            else:
                campo = datos[f"{col}_{k}"].astype(float)
                ax.imshow(np.where(campo > 0, campo, np.nan), origin="lower", extent=ext, cmap=AZULES, vmin=0, vmax=1,
                          interpolation="nearest")
                ax.contour(obs.astype(float), levels=[0.5], origin="lower", extent=ext, colors=[NARANJA],
                           linewidths=0.5)
                titulo = f"{col} · FSS₂₅ {_f(fss.get((col, k)))}"
            ax.set_title(titulo, fontsize=8.5)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.grid(False)
    fig.suptitle(f"{caso['id']} · t0 = {caso['t0']} ({caso['conjunto']}) — naranja: sargazo observado; "
                 "azul: simulado; gris claro: nube", color=TINTA, fontsize=10, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(ruta, dpi=90)
    plt.close(fig)


def figura_mcc(vectores: list[dict], ruta: Path, exps=("E2", "E3", "E4", "E5-1")):
    _estilo()
    exps = [e for e in exps if any(v["experimento"] == e and v.get("disponible") for v in vectores)]
    if not exps:
        return False
    fig, ejes = plt.subplots(1, len(exps), figsize=(3.2 * len(exps), 3.4), sharex=True, sharey=True)
    ejes = np.atleast_1d(ejes)
    dia = 86.4
    lim = 0.0
    for ax, e in zip(ejes, exps):
        g = [v for v in vectores if v["experimento"] == e and v.get("disponible")]
        o = np.array([np.hypot(v["este_km"], v["norte_km"]) / dia for v in g])
        s = np.array([np.hypot(v["este_sim_km"], v["norte_sim_km"]) / dia for v in g])
        lim = max(lim, float(np.max(np.r_[o, s])) if o.size else 0)
        ax.plot(o, s, "o", ms=4, color=NARANJA if e == "E2" else AZUL, alpha=0.6, mec="white", mew=0.5)
        ax.set_title(f"{NOMBRES[e]}\n({len(g)} vectores)", fontsize=8.5)
        ax.set_xlabel("rapidez observada (MCC), m/s")
    lim = max(lim * 1.05, 0.2)
    for ax in ejes:
        ax.plot([0, lim], [0, lim], color=GRIS_REF, lw=1, ls="--")
        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
    ejes[0].set_ylabel("rapidez del modelo, m/s")
    fig.suptitle("Desplazamiento observado (MCC entre imágenes de días consecutivos) vs. modelo en los mismos puntos",
                 color=TINTA, fontsize=10, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)
    return True


def figura_inventario(dias: list[dict], casos: list[dict], ruta: Path):
    _estilo()
    fechas = [d["fecha"] for d in dias]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 4.6), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    a1.plot(fechas, [d["sargazo"] for d in dias], color=AZUL, lw=0.6)
    a1.axhline(cfg.MIN_PIXELES_SARGAZO, color=GRIS_REF, lw=1, ls="--")
    for c in casos:
        t0 = date.fromisoformat(c["t0"]) if isinstance(c["t0"], str) else c["t0"]
        a1.axvline(t0, color=NARANJA if c["conjunto"] == "evaluacion" else TINTA, lw=0.8, alpha=0.7)
    a1.set_yscale("symlog", linthresh=100)
    a1.set_ylim(0, max(d["sargazo"] for d in dias) * 1.3)
    a1.set_ylabel("píxeles con sargazo")
    a1.set_title("Inventario AFAI 2022–2026 en el recuadro del modelo · líneas: casos (azul oscuro calibración, "
                 "naranja evaluación)", loc="left")
    a2.plot(fechas, [100 * d["claro"] for d in dias], color=TINTA_2, lw=0.5)
    a2.axhline(100 * cfg.MIN_CLARO_T0, color=GRIS_REF, lw=1, ls="--")
    a2.set_ylabel("% del mar sin nube")
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)


def figura_mascaras(m, ruta: Path):
    from validacion.inventario import franja_costura
    _estilo()
    ext = [m.lons[0], m.lons[-1], m.lats[0], m.lats[-1]]
    franja = franja_costura(m.lons, m.lats) & m.mar_modelo & ~m.persistente
    cat = np.where(~m.mar_modelo, 3, np.where(m.persistente, 2, np.where(franja, 4, np.where(m.mar_util, 0, 1))))
    fig, ax = plt.subplots(figsize=(7.2, 5.6))
    ax.imshow(cat, origin="lower", extent=ext, interpolation="nearest",
              cmap=ListedColormap(["#cde2fb", NUBE, NARANJA, TIERRA, "#6250d6"]), vmin=0, vmax=4)

    def n(x):
        return f"{int(x):,}".replace(",", " ")
    ax.set_title(f"Máscaras: azul = mar evaluado ({n(m.mar_util.sum())} píxeles); naranja = brillante persistente "
                 f"({n(m.persistente.sum())});\nvioleta = franja junto a la costura del producto ({n(franja.sum())}); "
                 "gris = casi nunca observado; arena = tierra", loc="left", fontsize=9)
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)


def figura_calibracion(tabla: list[dict], gamma: float, kh: float, ruta: Path):
    _estilo()
    gs, ks = list(cfg.REJILLA_GAMMA), list(cfg.REJILLA_KH)
    z = np.full((len(ks), len(gs)), np.nan)
    for t in tabla:
        z[ks.index(t["kh"]), gs.index(t["gamma"])] = t["fss_medio"]
    fig, ax = plt.subplots(figsize=(6, 3.2))
    im = ax.imshow(z, cmap=AZULES, aspect="auto", origin="lower")
    for i in range(len(ks)):
        for j in range(len(gs)):
            ax.text(j, i, _f(z[i, j], 3), ha="center", va="center", fontsize=8,
                    color="white" if np.isfinite(z[i, j]) and z[i, j] > np.nanmean(z) else TINTA)
    ax.set_xticks(range(len(gs)), [f"{g:g}" for g in gs])
    ax.set_yticks(range(len(ks)), [f"{k:g}" for k in ks])
    ax.set_xlabel("γ (factor de la deriva de Stokes)")
    ax.set_ylabel("K_h (m²/s)")
    ax.grid(False)
    ax.set_title(f"Calibración (solo casos de calibración): FSS {cfg.ESCALA_CALIBRACION_KM} km medio · "
                 f"elegido γ = {gamma:g}, K_h = {kh:g}", loc="left", fontsize=9)
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Tabla principal y conclusiones
# ---------------------------------------------------------------------------
def tabla_principal(resumen: list[dict], conjunto="evaluacion", escala=25) -> list[dict]:
    filas = []
    for e in ORDEN:
        fila = {"experimento": e, "nombre": NOMBRES[e]}
        for k in cfg.HORIZONTES_D:
            r = next((r for r in resumen if r["conjunto"] == conjunto and r["experimento"] == e
                      and r["horizonte_d"] == k and r["escala_km"] == escala), None)
            fila[k] = r
        if any(fila[k] for k in cfg.HORIZONTES_D):
            filas.append(fila)
    return filas


def markdown_tabla(filas: list[dict], con_dif=True) -> str:
    cab = "| Experimento | " + " | ".join(f"+{k} d" for k in cfg.HORIZONTES_D) + " |"
    sep = "|---|" + "---|" * len(cfg.HORIZONTES_D)
    lineas = [cab, sep]
    for f in filas:
        celdas = []
        for k in cfg.HORIZONTES_D:
            r = f[k]
            if not r or not np.isfinite(r["fss_medio"]):
                celdas.append("—")
                continue
            txt = f"{r['fss_medio']:.3f} [{r['ic_inf']:.3f}–{r['ic_sup']:.3f}]"
            if con_dif and f["experimento"] != "E0" and np.isfinite(r["dif_vs_E0"]):
                txt += f"<br>Δ vs E0 {r['dif_vs_E0']:+.3f} [{r['dif_ic_inf']:+.3f}, {r['dif_ic_sup']:+.3f}]"
            celdas.append(txt)
        lineas.append(f"| {f['nombre']} | " + " | ".join(celdas) + " |")
    return "\n".join(lineas)


def veredicto(r: dict | None) -> str:
    """"mejor", "peor" o "indistinguible" frente a E0 según el IC 95 % de la diferencia."""
    if not r or not np.isfinite(r.get("dif_ic_inf", np.nan)):
        return "sin datos"
    if r.get("casos_comparados", 0) < cfg.MIN_CASOS_VEREDICTO:
        return "sin datos suficientes"
    if r["dif_ic_inf"] > 0:
        return "mejor"
    if r["dif_ic_sup"] < 0:
        return "peor"
    return "indistinguible"
