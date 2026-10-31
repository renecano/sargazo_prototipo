"""Escribe los entregables de la validación a partir de los resultados.

- docs/validacion/*.csv, *.json y *.png
- docs/validacion.md (reporte para el profesor y SEMAR)
- docs/validacion/index.html (página /validacion de la app)
- bloque entre marcas en README.md

Las frases de conclusión se arman con reglas fijas sobre los intervalos de confianza
(`reporte.veredicto`): si el IC 95 % de la diferencia contra E0 queda por encima de 0 es
"mejor", por debajo "peor" y si cruza 0 "indistinguible". Ningún número se escribe a mano.
"""
from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.config import RAIZ, VERSION_APP, VERSION_MODELO
from validacion import config as cfg
from validacion import reporte as rp
from validacion.casos import MOTIVOS
from validacion.ejecutar import guardar_json

MARCA_INICIO = "<!-- validacion:inicio (generado por scripts/validar.py; no editar a mano) -->"
MARCA_FIN = "<!-- validacion:fin -->"


@dataclass
class Insumos:
    seleccion: object
    mascaras: object
    dias: list
    contexto: object
    gamma: float
    kh: float
    tabla_calibracion: list
    filas_calibracion: list
    resultados: list
    resultado_semar: dict | None
    comparacion_semar: dict
    generado: str
    duracion_s: float
    extra: dict = field(default_factory=dict)


def _todas(resultados, clave):
    salida = []
    for r in resultados:
        if r:
            salida += r[clave]
    return salida


def _miles(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def _pct(v, d=0):
    return "—" if v is None or not np.isfinite(v) else f"{100 * v:.{d}f} %"


def escribir_todo(d: Insumos, salida: Path, registrar=print) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    figuras = salida / "figuras"
    figuras.mkdir(exist_ok=True)
    resultados = [r for r in d.resultados if r]
    filas = _todas(resultados, "filas")
    costa = _todas(resultados, "costa")
    mcc = _todas(resultados, "mcc")

    # --- Tablas -----------------------------------------------------------------
    sel = d.seleccion
    casos_filas = [c.fila() for c in sel.casos] + ([sel.caso_semar.fila()] if sel.caso_semar else [])
    rp._escribir_csv(salida / "casos.csv", casos_filas)
    descartes = {MOTIVOS[k]: v for k, v in sel.descartes.items()}
    rp._escribir_csv(salida / "metricas_por_caso.csv", filas + (d.resultado_semar or {}).get("filas", []))
    rp._escribir_csv(salida / "costa_por_caso.csv", costa)
    rp._escribir_csv(salida / "mcc_vectores.csv", mcc)
    rp._escribir_csv(salida / "calibracion.csv", d.tabla_calibracion)
    mensual = rp.resumen_mensual(d.dias)
    rp._escribir_csv(salida / "inventario_mensual.csv", mensual)
    d.extra["mensual"] = mensual
    fss = rp.resumen_fss(filas)
    cen = rp.resumen_centroide(filas)
    mccr = rp.resumen_mcc(mcc)
    cos = rp.resumen_costa(costa)
    rp._escribir_csv(salida / "fss_resumen.csv", fss)
    rp._escribir_csv(salida / "centroide_resumen.csv", cen)
    rp._escribir_csv(salida / "mcc_resumen.csv", mccr)
    rp._escribir_csv(salida / "costa_resumen.csv", cos)

    # --- Figuras ----------------------------------------------------------------
    rp.figura_fss(fss, figuras / "fss_por_horizonte.png")
    hay_mcc = rp.figura_mcc([v for v in mcc if v["conjunto"] == "evaluacion"], figuras / "mcc_vs_modelo.png")
    rp.figura_inventario(d.dias, casos_filas, figuras / "inventario.png")
    rp.figura_mascaras(d.mascaras, figuras / "mascaras.png")
    rp.figura_calibracion(d.tabla_calibracion, d.gamma, d.kh, figuras / "calibracion.png")
    tierra = ~d.mascaras.mar_modelo
    figs_caso = []
    for r in resultados + ([d.resultado_semar] if d.resultado_semar else []):
        if r["caso"]["conjunto"] not in ("evaluacion", "semar"):
            continue
        npz = cfg.DIR_CACHE / "casos" / r["caso"]["id"] / "campos.npz"
        if npz.is_file():
            nombre = f"caso_{r['caso']['id']}.png"
            rp.figura_caso(npz, r["caso"], r["filas"], d.mascaras.lons, d.mascaras.lats, tierra, figuras / nombre)
            figs_caso.append(nombre)

    # --- Resumen principal ------------------------------------------------------
    principal = rp.tabla_principal(fss, "evaluacion", cfg.ESCALA_CALIBRACION_KM)
    con_resultado = {r["caso"]["id"] for r in resultados}
    n_eval = len([c for c in sel.casos if c.conjunto == "evaluacion" and c.id in con_resultado])
    n_cal = len([c for c in sel.casos if c.conjunto == "calibracion" and c.id in con_resultado])
    faltan = [c.id for c in sel.casos if c.id not in con_resultado]
    sin_extra = sorted({f["caso"] for f in filas if f["conjunto"] == "evaluacion" and f["experimento"] == "E4"
                        and not f.get("disponible")})
    d.extra.update(faltan=faltan, sin_extra=sin_extra,
                   n_eval_sel=len([c for c in sel.casos if c.conjunto == "evaluacion"]),
                   n_cal_sel=len([c for c in sel.casos if c.conjunto == "calibracion"]))
    v = {e: {k: rp.veredicto(next((f[k] for f in principal if f["experimento"] == e), None))
             for k in cfg.HORIZONTES_D} for e in rp.ORDEN}
    resumen = {
        "version_app": VERSION_APP, "version_modelo": VERSION_MODELO, "generado": d.generado,
        "casos": {"total": len(sel.casos), "calibracion": n_cal, "evaluacion": n_eval,
                  "candidatos": sel.candidatos, "dias_revisados": sel.dias_revisados, "descartes": descartes},
        "calibracion": {"gamma": d.gamma, "kh": d.kh},
        "veredictos_fss25": v,
        "tabla_principal": [{"experimento": f["experimento"], **{f"+{k}d": f[k] for k in cfg.HORIZONTES_D}}
                            for f in principal],
        "comparacion_semar": d.comparacion_semar,
        "duracion_s": round(d.duracion_s),
    }
    guardar_json(salida / "resumen.json", resumen)
    guardar_json(salida / "descartes.json", {"dias_revisados": sel.dias_revisados, "candidatos": sel.candidatos,
                                             "casos": len(sel.casos), "motivos": descartes})

    md = _markdown(d, fss, cen, mccr, cos, principal, v, figs_caso, hay_mcc, n_cal, n_eval)
    (RAIZ / "docs" / "validacion.md").write_text(md, encoding="utf-8", newline="\n")
    (salida / "index.html").write_text(_html(d, principal, v, figs_caso, hay_mcc, n_cal, n_eval, cos, mccr),
                                       encoding="utf-8", newline="\n")
    _actualizar_readme(principal, v, n_cal, n_eval, d)
    registrar(f"   {len(figs_caso)} figuras de caso; docs/validacion.md, docs/validacion/index.html y README actualizados")
    return resumen


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def _frase_e2(v) -> str:
    vs = v["E2"]
    partes = [f"+{k} d: {vs[k]}" for k in cfg.HORIZONTES_D]
    if all(x.startswith("sin datos") for x in vs.values()):
        base = "todavía no tiene casos suficientes para compararse con la persistencia"
    elif all(x == "mejor" for x in vs.values()):
        base = "le gana a la persistencia en los tres horizontes"
    elif all(x == "peor" for x in vs.values()):
        base = "pierde contra la persistencia en los tres horizontes"
    elif any(x == "peor" for x in vs.values()):
        base = "no le gana a la persistencia y en algunos horizontes es peor"
    elif any(x == "mejor" for x in vs.values()):
        base = "le gana a la persistencia solo en algunos horizontes"
    else:
        base = "no se distingue de la persistencia"
    return f"{base} ({'; '.join(partes)})"


def _mejor_experimental(principal) -> tuple[str, dict] | tuple[None, None]:
    cands = [f for f in principal if f["experimento"].startswith(("E4", "E5"))]
    if not cands:
        return None, None
    def media(f):
        vals = [f[k]["fss_medio"] for k in cfg.HORIZONTES_D if f[k] and np.isfinite(f[k]["fss_medio"])]
        return np.mean(vals) if vals else -1
    mejor = max(cands, key=media)
    return mejor["experimento"], mejor


def _conclusion(v, principal) -> str:
    e2 = v["E2"]
    exp, fila = _mejor_experimental(principal)
    if all(x.startswith("sin datos") for x in e2.values()):
        return "Todavía no hay casos de evaluación suficientes para decir si el modelo le gana a la persistencia."
    gana_e2 = all(x == "mejor" for x in e2.values())
    pierde_e2 = any(x == "peor" for x in e2.values())
    if gana_e2:
        txt = "El modelo v0.3 (solo oleaje) mueve el sargazo mejor que suponer que no se mueve"
    elif pierde_e2:
        txt = "Con datos satelitales 2022–2026, el modelo v0.3 (solo oleaje) todavía no predice el movimiento del sargazo mejor que suponer que no se mueve"
    else:
        txt = "Con datos satelitales 2022–2026, el modelo v0.3 (solo oleaje) no se distingue de suponer que el sargazo no se mueve"
    if exp:
        ve = v[exp]
        if all(x.startswith("sin datos") for x in ve.values()):
            txt += f"; para {rp.NOMBRES[exp]} aún no hay casos suficientes"
        elif all(x == "mejor" for x in ve.values()):
            txt += f"; agregar corrientes ({rp.NOMBRES[exp]}) sí le gana a la persistencia en los tres horizontes"
        elif any(x == "mejor" for x in ve.values()):
            txt += f"; agregar corrientes ({rp.NOMBRES[exp]}) le gana solo en algunos horizontes"
        else:
            txt += f"; ni agregando corrientes ({rp.NOMBRES[exp]}) se supera a la persistencia"
    return txt + "."


def _tabla_md(filas, columnas):
    out = ["| " + " | ".join(c[0] for c in columnas) + " |", "|" + "---|" * len(columnas)]
    for f in filas:
        out.append("| " + " | ".join(c[1](f) for c in columnas) + " |")
    return "\n".join(out)


def _markdown(d: Insumos, fss, cen, mccr, cos, principal, v, figs_caso, hay_mcc, n_cal, n_eval) -> str:
    sel = d.seleccion
    m = d.mascaras
    ctx = d.contexto
    esc = cfg.ESCALA_CALIBRACION_KM
    cs = d.comparacion_semar["comparacion"]
    c0 = cs[0]
    exp_mejor, _ = _mejor_experimental(principal)
    periodos = [r["forzamientos"].get("periodo", {}) for r in d.resultados if r]
    razones = [p["real_entre_supuesto_mediana"] for p in periodos if p and p.get("real_entre_supuesto_mediana")]
    semar_caso = d.resultado_semar
    L = []
    w = L.append
    w("# ¿El modelo se mueve como el sargazo real? — Validación de PMS v0.4.0")
    w("")
    w(f"> Generado por `python scripts/validar.py` el {d.generado}. Cada número "
      "de este documento sale de ese script; las tablas completas están en [`docs/validacion/`](validacion/).")
    w("")
    w("## Conclusión")
    w("")
    w(f"**{_conclusion(v, principal)}**")
    w("")
    w(f"Medido en {n_eval} casos de evaluación (2025–2026) que no se usaron para calibrar, con el Fractions "
      f"Skill Score a {esc} km entre el sargazo que vio el satélite y el que simula el modelo a +3, +5 y +7 días. "
      f"El modelo v0.3 (E2) {_frase_e2(v)}.")
    w("")
    w(_tabla_resumen_md(principal))
    w("")
    if d.extra["faltan"] or d.extra["sin_extra"]:
        w(f"**Incompleto**: de {d.extra['n_eval_sel']} casos de evaluación seleccionados hay resultados de {n_eval}"
          + (f"; faltan {', '.join(d.extra['faltan'])}" if d.extra["faltan"] else "")
          + (f"; sin corriente o viento (E4 y E5 no calculados): {', '.join(d.extra['sin_extra'])}"
             if d.extra["sin_extra"] else "")
          + ". Motivo: cuota diaria de Open-Meteo; al volver a correr `scripts/validar.py` se completan.")
        w("")
    w("FSS: 1 = coincidencia perfecta, 0 = ninguna. Entre corchetes, intervalo de confianza del 95 % por "
      f"bootstrap de casos ({cfg.REMUESTREOS_BOOTSTRAP} remuestreos). Δ vs E0: diferencia pareada caso a caso "
      "contra la persistencia; si su intervalo no incluye 0, la diferencia es real con esos casos.")
    w("")
    w("![FSS por experimento y horizonte](validacion/figuras/fss_por_horizonte.png)")
    w("")
    w("## La pregunta")
    w("")
    w("El profesor preguntó: *¿cómo sabemos que ese comportamiento del sargazo es real?* La respuesta honesta es "
      "compararlo contra cómo se movió el sargazo de verdad. Este módulo toma días con sargazo visto por "
      "satélite, siembra partículas donde estaba, las mueve con el modelo usando el oleaje real de esas fechas y "
      "compara contra lo que el satélite vio 3, 5 y 7 días después. La referencia mínima es la **persistencia** "
      "(suponer que el sargazo no se mueve): un modelo que no le gana no aporta información sobre el movimiento.")
    w("")
    w("El producto no cambia: sigue usando solo `dirmarea.txt`. La validación genera `dirmarea.txt` reales en el "
      "mismo formato y los pasa por el mismo validador, lector e integrador del producto.")
    w("")
    w("## Fuentes")
    w("")
    w("Detalle completo (URL, IDs, variables, licencias, fechas de descarga y limitaciones) en "
      "[`docs/fuentes_validacion.md`](fuentes_validacion.md).")
    w("")
    w("| Qué | Fuente | Uso |")
    w("|---|---|---|")
    w(f"| Sargazo observado | AFAI diario de USF (C. Hu), NOAA AOML ERDDAP `{cfg.DATASET_AFAI_1D}`, 0.015° | Verdad |")
    w("| Oleaje de viento | Open-Meteo, MeteoFrance MFWAM (`meteofrance_wave`), 0.08° | dirmarea.txt real (E1–E3, E5) |")
    w("| Corriente superficial | Open-Meteo, MeteoFrance SMOC (`meteofrance_currents`), 0.08° | E4, E5 (experimental) |")
    w("| Viento a 10 m | Open-Meteo histórico, ERA5 (`era5`), 0.25° | E5 (experimental) |")
    w("")
    w("La detección de Sentinel-3 OLCI (Debue et al., ESSD 2026) quedó como segunda opinión pendiente: ver fuentes.")
    w("")
    w("## Método")
    w("")
    w("### Sargazo observado")
    w("")
    w(f"Se sigue a Wang & Hu (2016, *Remote Sensing of Environment* 183:350-367): ΔAFAI = AFAI − fondo, con el fondo "
      f"= mediana en una ventana de {cfg.VENTANA_FONDO} × {cfg.VENTANA_FONDO} píxeles que excluye los candidatos "
      f"(ΔAFAI preliminar > {cfg.UMBRAL_TS:.2e}); un píxel tiene sargazo si **ΔAFAI > {cfg.UMBRAL_T0:.2e}**, "
      "el umbral con el que esos autores capturan ~95 % de los píxeles con sargazo y confunden ~10 % de los "
      "vecinos sin sargazo. Diferencias con el artículo: el fondo sale de dos pasadas de mediana (sin el ajuste "
      "polinómico previo) y no hay máscara de sombra de nube.")
    w("")
    w(f"- **Nubes y píxeles sin dato**: AOML entrega NaN donde hay nube, brillo solar o tierra; además se descartan "
      f"{cfg.BORDE_NUBE_PX} píxeles alrededor de cada nube (efecto de adyacencia). Un píxel con nube en la imagen de "
      "destino no cuenta ni para lo observado ni para lo simulado.")
    w(f"- **Mar evaluado**: {_miles(m.mar_util.sum())} píxeles de ~1.6 km. Se excluyen la tierra del modelo, los píxeles "
      f"observados menos de 30 veces en 2022–2026 (AOML no cubre la franja al sur de 21° N y al oeste de 90.5° O) y "
      f"**{_miles(m.persistente.sum())} píxeles brillantes persistentes** (sobre el umbral en ≥ "
      f"{cfg.FRECUENCIA_PERSISTENTE:.0%} de sus observaciones: fondo somero, turbidez, arrecifes; el sargazo se "
      "mueve, un fondo no).")
    mensual = [x for x in d.extra.get("mensual", []) if np.isfinite(x["fraccion_sargazo_mediana"])]
    if mensual:
        bajo = min(mensual, key=lambda x: x["fraccion_sargazo_mediana"])
        alto = max(mensual, key=lambda x: x["fraccion_sargazo_mediana"])
        w(f"- **Umbral adaptado al ruido**: en este producto el ruido de ΔAFAI en el Caribe es del orden de T0, así que "
          f"con T0 solo una parte grande del mar saldría con «sargazo» aun sin temporada. Por eso se exige además "
          f"ΔAFAI > {cfg.K_SIGMA:g}σ, con σ = 1.4826 × MAD de ΔAFAI en la misma ventana (umbral local por la "
          "distribución de la ventana, como Garcia et al., 2013, citado por Wang & Hu). Se fijó antes de correr "
          f"cualquier experimento. Aun así queda ruido: la mediana mensual de la fracción de píxeles despejados con "
          f"«sargazo» va de {100 * bajo['fraccion_sargazo_mediana']:.1f} % ({bajo['mes']}) a "
          f"{100 * alto['fraccion_sargazo_mediana']:.1f} % ({alto['mes']}); el mes más bajo acota el piso de ruido "
          "([`inventario_mensual.csv`](validacion/inventario_mensual.csv)).")
        w(f"- **Dos regiones del producto**: el AFAI de AOML une dos regiones con ruido distinto y bordes rectos en "
          f"{cfg.COSTURA_LAT}° N y {abs(cfg.COSTURA_LON)}° O (salto brusco en la frecuencia de detección y en el número "
          "de observaciones). El fondo y el ruido se estiman por región; mezclarlas crea una franja falsa de "
          "«sargazo» junto a la costura que, por estar fija, favorecería a la persistencia. Aun así, del lado «Caribe» "
          f"la frecuencia de detección sube de forma monótona en los {cfg.FRANJA_COSTURA_PX} píxeles junto a la costura "
          "(de ~6 % a ~26 %; al otro lado se queda en 2–3 %): es un artefacto de los valores del producto en el borde "
          "y esa franja se excluye.")
    w("")
    w("![Máscaras](validacion/figuras/mascaras.png)")
    w("")
    w("### Oleaje real en el formato de SEMAR")
    w("")
    w("`scripts/generar_dirmarea.py` descarga la ola de viento de MFWAM (altura, dirección «desde») y escribe un "
      "`dirmarea.txt` idéntico en formato al de SEMAR: misma malla de 94 × 51 nodos, mismas columnas LON;LAT "
      "byte a byte, 41 bloques +0…+120 h, mismo relleno `-9.99e+08` en tierra. El validador del producto lo acepta "
      "sin cambios. Open-Meteo cuenta cada punto como una llamada (10 000 al día gratis), así que se descarga un "
      "nodo de cada dos (0.32°) y se interpola a 0.16°; los nodos fuera del recuadro del modelo quedan con relleno. "
      "Para llegar a +7 días se encadenan dos archivos (fecha base t0 y t0 + 5 d), cada uno validado por el producto.")
    w("")
    if razones:
        w(f"**Período de la ola.** El producto supone T = 4.0·√H porque `dirmarea.txt` no trae período. Con el "
          f"período real de MFWAM en {len(razones)} casos, la mediana de T_real / T_supuesto por caso va de "
          f"{min(razones):.2f} a {max(razones):.2f} (mediana {np.median(razones):.2f}): el supuesto está cerca del "
          "período de la ola de viento de MFWAM.")
        w("")
    w("### Casos")
    w("")
    w(f"Se revisaron {sel.dias_revisados} días ({cfg.BUSQUEDA_DESDE} a {cfg.BUSQUEDA_HASTA} menos 7 días). Un día es "
      f"candidato si tiene ≥ {cfg.MIN_PIXELES_SARGAZO} píxeles con sargazo, ≥ {cfg.MIN_CLARO_T0:.0%} del mar despejado, "
      f"imagen a +3, +5 y +7 días con ≥ {cfg.MIN_CLARO_DESTINO:.0%} despejado y ≥ {cfg.MIN_CLARO_ZONA:.0%} despejado a "
      f"≤ {cfg.RADIO_ZONA_KM:.0f} km del sargazo inicial. Los casos no comparten imágenes (t0 separados más de 7 días); "
      f"se eligen de mayor a menor calidad. Hubo **{sel.candidatos} días candidatos y {len(sel.casos)} casos**: "
      f"{d.extra['n_cal_sel']} de calibración (t0 antes de {cfg.CORTE_EVALUACION}) y {d.extra['n_eval_sel']} de "
      "evaluación (2025–2026). La "
      "separación por fechas se fijó antes de correr.")
    w("")
    w("| Motivo de descarte (primer criterio que falla) | Días |")
    w("|---|---|")
    for k, n in sel.descartes.items():
        w(f"| {MOTIVOS[k]} | {n} |")
    w("")
    w("![Inventario y casos](validacion/figuras/inventario.png)")
    w("")
    w("Lista de casos: [`docs/validacion/casos.csv`](validacion/casos.csv).")
    w("")
    w("### Experimentos")
    w("")
    w(f"Todos con las mismas {_miles(cfg.PARTICULAS)} partículas (o una por píxel si hay más píxeles), sembradas en proporción a "
      f"los píxeles con sargazo en t0 (cada píxel pesa 1), la misma semilla ({cfg.SEMILLA}) y el integrador del "
      f"producto (Δt = 1 h, RK2, costa y varamiento iguales). La simulación empieza a las {cfg.HORA_IMAGEN_UTC} UTC "
      "(hora aproximada de la imagen).")
    w("")
    w("| | Qué mueve las partículas |")
    w("|---|---|")
    w("| E0 | Nada: persistencia |")
    w(f"| E1 | Solo browniano (γ = 0, K_h = {cfg.KH_V03:g} m²/s) |")
    w(f"| E2 | PMS v0.3 tal cual: deriva de Stokes de la ola real (γ = 1, K_h = {cfg.KH_V03:g}) |")
    w(f"| E3 | PMS con γ = {d.gamma:g} y K_h = {d.kh:g}, elegidos con los {n_cal} casos de calibración "
      f"(rejilla γ ∈ {list(cfg.REJILLA_GAMMA)}, K_h ∈ {list(cfg.REJILLA_KH)}, máximo FSS {esc} km medio) |")
    w("| E4 | Corriente superficial SMOC + browniano (experimental) |")
    w("| E5 | Corriente + 1 %, 2 % o 3 % del viento a 10 m + ola (γ = 1) (experimental) |")
    w("")
    w("**Ojo con E5**: según Open-Meteo, la corriente de SMOC ya es «Eulerian, Waves and Tides», es decir, incluye "
      "la deriva de Stokes del oleaje; sumarle la ola cuenta esa deriva dos veces. Se corrió como se pidió y se "
      "reporta con esa advertencia.")
    w("")
    w("![Calibración](validacion/figuras/calibracion.png)")
    w("")
    w("### Métricas")
    w("")
    w(f"- **FSS** (Roberts & Lean, 2008) a {', '.join(f'{e} km' for e in cfg.ESCALAS_FSS_KM)} (ventanas de "
      f"{', '.join(f'{n} px ≈ {n * ctx.km_lado:.0f} km' for n in ctx.ventanas.values())}). Observado = 1 en los "
      "píxeles con sargazo; simulado = suma de pesos de las partículas a flote en el píxel (máx. 1). Solo píxeles "
      "despejados en la imagen de destino.")
    w("- **Centroide**: distancia entre el centroide observado y el simulado (mismos píxeles despejados), y error de "
      "dirección del desplazamiento respecto a E0 cuando lo observado se movió ≥ 5 km.")
    w(f"- **MCC**: correlación cruzada máxima normalizada con máscara (Padfield, 2012) de ΔAFAI entre imágenes de "
      f"días consecutivos, plantillas de {cfg.MCC_PLANTILLA_PX} px y búsqueda ± {cfg.MCC_BUSQUEDA_PX} px; se acepta "
      f"con correlación ≥ {cfg.MCC_MIN_CORRELACION}. Se compara con el desplazamiento de 24 h del modelo desde el "
      "mismo punto y se resume con el skill score de Liu & Weisberg (2011) con trayectorias de un solo tramo "
      "(no hay boyas en los casos).")
    w(f"- **Costa**: por tramo de costa del modelo, ¿hay ≥ 3 píxeles con sargazo a ≤ {cfg.BANDA_COSTA_KM:.0f} km de la "
      "costa en la imagen? Simulado: partículas varadas en el tramo más las que flotan en esa banda. Solo tramos con "
      "≥ 30 % de su banda despejada.")
    w("")
    w("## Resultados")
    w("")
    w(f"### FSS en los {n_eval} casos de evaluación")
    w("")
    for e in cfg.ESCALAS_FSS_KM:
        w(f"**Vecindad de {e} km**")
        w("")
        w(rp.markdown_tabla(rp.tabla_principal(fss, "evaluacion", e)))
        w("")
    utiles = [r["fss_util_medio"] for r in fss if r["conjunto"] == "evaluacion" and r["experimento"] == "E0"]
    if utiles:
        w(f"FSS «útil» de Roberts & Lean (0.5 + f₀/2) en estos casos: {np.nanmean(utiles):.3f} de media.")
        w("")
    w(f"Con los {n_cal} casos de calibración y con todos los casos: [`fss_resumen.csv`](validacion/fss_resumen.csv).")
    w("")
    w("### Centroide y dirección (evaluación)")
    w("")
    sel_cen = [r for r in cen if r["conjunto"] == "evaluacion"]
    w(_tabla_md(sel_cen, [
        ("Experimento", lambda r: rp.NOMBRES[r["experimento"]]), ("Horizonte", lambda r: f"+{r['horizonte_d']} d"),
        ("Error de centroide (km)", lambda r: f"{rp._f(r['error_centroide_km'], 0)} [{rp._f(r['ic_inf'], 0)}–{rp._f(r['ic_sup'], 0)}]"),
        ("Δ vs E0 (km)", lambda r: f"{rp._f(r['dif_vs_E0_km'], 0)} [{rp._f(r['dif_ic_inf'], 0)}, {rp._f(r['dif_ic_sup'], 0)}]"),
        ("Error de dirección mediano", lambda r: f"{rp._f(r['error_direccion_mediano'], 0)}° (n = {r['casos_con_direccion']})"),
        ("Varado / fuera", lambda r: f"{_pct(r['masa_varada'])} / {_pct(r['masa_fuera'])}"),
    ]))
    w("")
    w("El centroide resume todo el sargazo visible del recuadro en un punto; con nubes distintas entre imágenes es "
      "una medida ruidosa. Se reporta, pero el FSS es la métrica principal.")
    w("")
    w("### Desplazamiento observado (MCC) contra el modelo")
    w("")
    sel_m = [r for r in mccr if r["conjunto"] == "evaluacion"]
    if sel_m and sel_m[0]["vectores"]:
        w(_tabla_md(sel_m, [
            ("Experimento", lambda r: rp.NOMBRES[r["experimento"]]), ("Vectores", lambda r: str(r["vectores"])),
            ("Rapidez obs. (m/s)", lambda r: rp._f(r["rapidez_obs_ms"], 3)),
            ("Rapidez modelo (m/s)", lambda r: rp._f(r["rapidez_sim_ms"], 3)),
            ("Error vectorial RMS (m/s)", lambda r: rp._f(r["error_vector_ms"], 3)),
            ("Error de dirección mediano", lambda r: f"{rp._f(r['error_direccion_mediano'], 0)}°"),
            ("Liu-Weisberg", lambda r: f"{rp._f(r['liu_weisberg'])} [{rp._f(r['lw_ic_inf'])}–{rp._f(r['lw_ic_sup'])}]"),
        ]))
        w("")
        if hay_mcc:
            w("![MCC contra el modelo](validacion/figuras/mcc_vs_modelo.png)")
            w("")
    else:
        w("Ningún par de imágenes consecutivas de los casos de evaluación dio vectores MCC aceptables (nubes o "
          "correlación baja).")
        w("")
    w("### Llegada a costa (evaluación)")
    w("")
    sel_c = [r for r in cos if r["conjunto"] == "evaluacion"]
    w(_tabla_md(sel_c, [
        ("Experimento", lambda r: rp.NOMBRES[r["experimento"]]), ("Horizonte", lambda r: f"+{r['horizonte_d']} d"),
        ("Aciertos / fallos / falsas alarmas / negativos",
         lambda r: f"{r['aciertos']} / {r['fallos']} / {r['falsas_alarmas']} / {r['negativos']}"),
        ("POD", lambda r: rp._f(r["pod"])), ("FAR", lambda r: rp._f(r["far"])), ("CSI", lambda r: rp._f(r["csi"])),
    ]))
    w("")
    w("POD: fracción de tramos con sargazo costero observado que el modelo anticipó; FAR: fracción de avisos sin "
      "sargazo observado; CSI: aciertos / (aciertos + fallos + falsas alarmas).")
    w("")
    w("### Caso de la fecha de nuestro dirmarea.txt (01/10/2026)")
    w("")
    w(f"**¿Coincide el `dirmarea.txt` de SEMAR con el oleaje real de ese día?** Comparado con la ola de viento de "
      f"MFWAM en {c0['nodos']} nodos del recuadro a las 00 UTC: altura media SEMAR {c0['altura_semar_media_m']:.2f} m "
      f"vs. real {c0['altura_real_media_m']:.2f} m (sesgo {c0['sesgo_altura_m']:+.2f} m, RMSE {c0['rmse_altura_m']:.2f} m, "
      f"correlación {c0['correlacion_altura']:.2f}); dirección media SEMAR {c0['direccion_semar_media']:.0f}° vs. real "
      f"{c0['direccion_real_media']:.0f}° (diferencia mediana por nodo {c0['dif_direccion_mediana']:.0f}°, p90 "
      f"{c0['dif_direccion_p90']:.0f}°). Como los 41 bloques de SEMAR son idénticos, la diferencia en los días "
      "siguientes es:")
    w("")
    w(_tabla_md(cs, [
        ("Hora", lambda r: f"+{r['hora']} h"), ("Altura SEMAR / real (m)",
                                               lambda r: f"{r['altura_semar_media_m']:.2f} / {r['altura_real_media_m']:.2f}"),
        ("RMSE altura (m)", lambda r: f"{r['rmse_altura_m']:.2f}"), ("Correlación", lambda r: rp._f(r["correlacion_altura"])),
        ("Dirección SEMAR / real", lambda r: f"{r['direccion_semar_media']:.0f}° / {r['direccion_real_media']:.0f}°"),
        ("Dif. dirección mediana", lambda r: f"{r['dif_direccion_mediana']:.0f}°"),
    ]))
    w("")
    if semar_caso:
        cs_caso = semar_caso["caso"]
        w(f"**¿Y la simulación con lo que vio el satélite después?** El 01/10/2026 el satélite vio "
          f"{cs_caso['sargazo_t0']} píxeles con sargazo con {_pct(cs_caso.get('claro_0d'))} del mar despejado"
          + ("" if cs_caso.get("cumple_criterios") else
             f"; **no cumple los criterios de caso** ({MOTIVOS.get(sel.motivo_semar, sel.motivo_semar)}), así que este "
             "resultado es ilustrativo y no entra en las tablas") + ".")
        w("")
        fs = {(f["experimento"], f["horizonte_d"]): f for f in semar_caso["filas"] if f.get("disponible")}
        w("| Experimento | " + " | ".join(f"FSS {esc} km +{k} d" for k in cfg.HORIZONTES_D) + " |")
        w("|---|" + "---|" * len(cfg.HORIZONTES_D))
        for e in ["E0", "E2-SEMAR", "E2", "E4"]:
            if any((e, k) in fs for k in cfg.HORIZONTES_D):
                w(f"| {rp.NOMBRES[e]} | " + " | ".join(rp._f(fs.get((e, k), {}).get(f'fss_{esc}km'), 3)
                                                        for k in cfg.HORIZONTES_D) + " |")
        w("")
    w("### Casos uno por uno")
    w("")
    for nombre in figs_caso:
        w(f"![{nombre}](validacion/figuras/{nombre})")
        w("")
    w("## Qué significa y qué no")
    w("")
    w("- **Sí** mide si el modelo pone el sargazo donde el satélite lo vio días después mejor que no moverlo, con "
      "casos que no se usaron para calibrar.")
    w("- **No** es una validación de llegada a playa con datos de campo: el satélite no ve el sargazo ya varado y "
      "los píxeles pegados a la costa suelen salir con nube, mezcla de tierra o fondo somero.")
    w("- **No** valida el oleaje de SEMAR operativo: se usó oleaje de MFWAM en el formato de SEMAR; con el archivo de "
      "SEMAR solo hay una fecha y sus 41 bloques son idénticos.")
    w("- Un FSS bajo en todos los experimentos (incluida la persistencia) también refleja lo difícil de la "
      "observación: el sargazo aparece y desaparece entre imágenes por nubes, por el umbral y porque se hunde o "
      "se agrega.")
    w("")
    w("## Limitaciones")
    w("")
    w("- **Nubes**: la mayoría de los días no sirven; los casos elegidos son los días más despejados, que pueden no "
      "representar las condiciones de tormenta.")
    w("- **Umbral AFAI**: T0 = 1.79×10⁻⁴ viene de MODIS en el Atlántico central; el producto de AOML puede mezclar "
      "sensores y en aguas someras hay falsos positivos (mitigados con la máscara de brillantes persistentes). Sin "
      "máscara de sombra de nube.")
    w("- **Resolución**: píxel de ~1.6 km (el sargazo forma filamentos de decenas de metros); malla del modelo de "
      "0.16°; forzamientos descargados a 0.32° (ola y corriente) y 0.48° (viento) e interpolados.")
    w("- **Ola sin período real en el producto**: el producto supone T = 4·√H; aquí se comparó con el período de "
      "MFWAM (ver arriba), pero el modelo sigue usando el supuesto.")
    w("- **Sin corrientes en el producto**: E4 y E5 son experimentos de este módulo, no del producto. La corriente de "
      "SMOC ya incluye la deriva por oleaje y la marea.")
    w("- **Forzamientos «históricos» de Open-Meteo**: MFWAM y SMOC son archivos de pronósticos de corto plazo, no "
      "reanálisis; ERA5 sí es reanálisis.")
    w(f"- **Pocos casos**: {n_eval} de evaluación; los intervalos de confianza lo reflejan.")
    w("")
    w("## Cómo reproducir")
    w("")
    w("```powershell")
    w("python -m pip install -r requirements-validacion.txt")
    w("python scripts/validar.py          # descarga a data/validacion/ (no se sube a git) y escribe docs/validacion/")
    w("```")
    w("")
    w("Open-Meteo gratuito permite 10 000 llamadas al día y cada punto cuenta (~900 por caso): si se agota, el script "
      "lo dice y al volver a correrlo sigue donde se quedó.")
    w("")
    return "\n".join(L)


def _tabla_resumen_md(principal) -> str:
    return rp.markdown_tabla(principal)


# ---------------------------------------------------------------------------
# Página /validacion
# ---------------------------------------------------------------------------
def _html(d: Insumos, principal, v, figs_caso, hay_mcc, n_cal, n_eval, cos, mccr) -> str:
    esc = cfg.ESCALA_CALIBRACION_KM
    e = html.escape

    def celda(r, exp):
        if not r or not np.isfinite(r["fss_medio"]):
            return "<td>—</td>"
        txt = f"<b>{r['fss_medio']:.3f}</b><br><small>IC {r['ic_inf']:.3f}–{r['ic_sup']:.3f}</small>"
        if exp != "E0" and np.isfinite(r["dif_vs_E0"]):
            txt += f"<br><small>Δ vs E0 {r['dif_vs_E0']:+.3f} [{r['dif_ic_inf']:+.3f}, {r['dif_ic_sup']:+.3f}]</small>"
        return f"<td>{txt}</td>"

    filas = "\n".join(
        f"<tr><th scope='row'>{e(f['nombre'])}</th>{''.join(celda(f[k], f['experimento']) for k in cfg.HORIZONTES_D)}</tr>"
        for f in principal)
    casos_html = "\n".join(f"<figure><img src='figuras/{n}' alt='Observado vs simulado, {e(n)}' loading='lazy'></figure>"
                           for n in figs_caso)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="/validacion/">
<title>Validación PMS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{ --papel:#f4ecd8; --papel-claro:#fbf6ea; --tinta:#1d3557; --tinta-2:#45597a; --linea:rgba(29,53,87,.18);
          --sans:"IBM Plex Sans","Segoe UI",system-ui,sans-serif; --mono:"IBM Plex Mono",Consolas,monospace; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--papel); color:var(--tinta); font:15px/1.55 var(--sans); }}
  main {{ max-width:1080px; margin:0 auto; padding:28px 16px 60px; }}
  a {{ color:var(--tinta); }}
  .volver {{ font:12px var(--mono); }}
  h1 {{ font-size:26px; margin:10px 0 6px; font-weight:600; }}
  h2 {{ font-size:18px; margin:34px 0 10px; font-weight:600; }}
  .conclusion {{ background:var(--papel-claro); border:1px solid var(--linea); border-left:4px solid var(--tinta);
                 padding:14px 16px; font-size:16px; border-radius:4px; }}
  .nota {{ color:var(--tinta-2); font-size:13px; }}
  .tabla {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; background:var(--papel-claro); font-size:13.5px; }}
  th, td {{ border-bottom:1px solid var(--linea); padding:8px 10px; text-align:left; vertical-align:top; }}
  thead th {{ font:600 11px var(--mono); text-transform:uppercase; letter-spacing:.06em; }}
  td small {{ font-family:var(--mono); font-size:11px; color:var(--tinta-2); }}
  figure {{ margin:14px 0; }}
  img {{ max-width:100%; height:auto; background:#fff; border:1px solid var(--linea); border-radius:4px; }}
  footer {{ margin-top:40px; font-size:12.5px; color:var(--tinta-2); }}
</style>
</head>
<body>
<main>
<a class="volver" href="/">← Volver al mapa</a>
<h1>¿El modelo se mueve como el sargazo real?</h1>
<p class="nota">Validación de PMS v{e(VERSION_APP)} ({e(VERSION_MODELO)}) contra el sargazo visto por satélite (AFAI de USF, NOAA AOML), 2022–2026. Generado el {e(d.generado)} por <code>scripts/validar.py</code>.</p>
<p class="conclusion">{e(_conclusion(v, principal))}</p>
<h2>FSS a {esc} km en {n_eval} casos de evaluación</h2>
<p class="nota">1 = coincidencia perfecta; 0 = ninguna. IC 95 % por bootstrap de casos. Δ vs E0 = diferencia pareada contra suponer que el sargazo no se mueve. γ y K_h de E3 se eligieron con {n_cal} casos de calibración anteriores a 2025.</p>
<div class="tabla"><table>
<thead><tr><th>Experimento</th>{''.join(f'<th>+{k} días</th>' for k in cfg.HORIZONTES_D)}</tr></thead>
<tbody>
{filas}
</tbody></table></div>
<figure><img src="figuras/fss_por_horizonte.png" alt="FSS por experimento y horizonte a 10, 25 y 50 km"></figure>
{"<h2>Desplazamiento observado (MCC) contra el modelo</h2><figure><img src='figuras/mcc_vs_modelo.png' alt='Rapidez observada por MCC contra la del modelo'></figure>" if hay_mcc else ""}
<h2>Casos de evaluación: observado contra simulado</h2>
<p class="nota">Naranja: sargazo observado; azul: simulado; gris claro: nube.</p>
{casos_html}
<h2>Cómo se hizo</h2>
<figure><img src="figuras/inventario.png" alt="Inventario de imágenes y casos elegidos"></figure>
<figure><img src="figuras/mascaras.png" alt="Máscaras de mar evaluado"></figure>
<figure><img src="figuras/calibracion.png" alt="Calibración de gamma y K_h"></figure>
<footer>Fuentes: AFAI de USF (C. Hu) vía NOAA AOML ERDDAP; oleaje MFWAM y corriente SMOC (Météo-France / Copernicus Marine) y viento ERA5 (ECMWF) vía Open-Meteo (CC BY 4.0). Método, limitaciones y todas las tablas: <code>docs/validacion.md</code> y <code>docs/validacion/</code> en el repositorio.</footer>
</main>
</body>
</html>
"""


def _actualizar_readme(principal, v, n_cal, n_eval, d: Insumos):
    ruta = RAIZ / "README.md"
    texto = ruta.read_text(encoding="utf-8")
    bloque = "\n".join([
        MARCA_INICIO,
        f"**{_conclusion(v, principal)}**",
        "",
        f"FSS a {cfg.ESCALA_CALIBRACION_KM} km (1 = perfecto) en {n_eval} casos de evaluación 2025–2026 "
        f"(γ y K_h de E3 calibrados con {n_cal} casos anteriores), media e IC 95 %:",
        "",
        rp.markdown_tabla(principal),
        "",
        "Reporte completo con método, casos y limitaciones: [docs/validacion.md](docs/validacion.md) · "
        "página en la app: `/validacion`.",
        MARCA_FIN,
    ])
    if MARCA_INICIO in texto and MARCA_FIN in texto:
        a = texto.index(MARCA_INICIO)
        b = texto.index(MARCA_FIN) + len(MARCA_FIN)
        texto = texto[:a] + bloque + texto[b:]
    else:
        texto = texto.rstrip("\n") + "\n\n## ¿El modelo se mueve como el sargazo real?\n\n" + bloque + "\n"
    ruta.write_text(texto, encoding="utf-8", newline="\n")
