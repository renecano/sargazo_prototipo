"""Mide el contraste de la paleta del sargazo contra la tierra y el mar de cada mapa base.

    python scripts/medir_contraste.py                # mide los fondos (descarga teselas) y escribe todo
    python scripts/medir_contraste.py --sin-descarga # usa los fondos ya medidos en docs/contraste.json

Qué hace:

1. Lee la paleta de src/view/js/paleta.js (los mismos colores que usa el mapa).
2. Fondos. En la carta propia son constantes de la paleta. En el satélite (Sentinel-2 cloudless
   2016 de EOX) y en las calles (OpenStreetMap, con el filtro sepia de la interfaz) se miden en
   teselas reales de zoom 10 de ocho zonas del dominio: cada píxel se clasifica como tierra o mar
   con la máscara de costa del modelo y se toma la mediana, más los extremos claro y oscuro
   (decil superior e inferior de luminancia).
3. Calcula la razón de contraste WCAG 2.x de cada elemento contra cada fondo y la diferencia de
   color ΔE (CIE76) entre el sargazo y la tierra, el mar y lo varado, con visión normal y con
   protanopía, deuteranopía y tritanopía simuladas (Machado, Oliveira y Fernandes, 2009).
4. Escribe docs/contraste.json, docs/contraste.md y el bloque «contraste» del README.

Necesita Pillow (viene con matplotlib, en requirements-validacion.txt).
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.model import costa  # noqa: E402

ARCHIVO_PALETA = RAIZ / "src" / "view" / "js" / "paleta.js"
SALIDA_JSON = RAIZ / "docs" / "contraste.json"
SALIDA_MD = RAIZ / "docs" / "contraste.md"
README = RAIZ / "README.md"
DIR_TESELAS = RAIZ / "data" / "costa" / "teselas"
AGENTE = "PMS-sargazo/0.5 (scripts/medir_contraste.py; github.com/renecano/sargazo_prototipo)"
URLS = {
    "satelite": "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg",
    "calles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}
ZOOM = 10
# (lat, lon): Cancún, canal de Cozumel, Tulum, Mahahual, Holbox, Progreso, mar abierto y Sian Ka'an.
ZONAS = [(21.12, -86.70), (20.50, -87.00), (20.20, -87.40), (18.70, -87.65), (21.50, -87.30), (21.30, -89.60),
         (20.40, -86.30), (19.60, -87.50)]
# Filtro CSS de la capa de calles (src/view/css/carta.css, .tesela-calles).
FILTRO_CALLES = {"sepia": 0.3, "saturate": 0.72, "brightness": 1.03, "contrast": 0.94}
ALFA_DENSIDAD = (0.16, 0.30, 0.46, 0.62)        # src/view/js/capas.js
NOMBRES_BASE = {"carta": "Carta propia", "satelite": "Satélite", "calles": "Calles"}
MINIMO = 3.0                                    # WCAG 2.x, 1.4.11: objetos gráficos

# Matrices de Machado et al. (2009), severidad 1.0, sobre RGB lineal.
DALTONISMO = {
    "protanopía": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deuteranopía": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritanopía": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------
def hexa(color: str) -> np.ndarray:
    c = color.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def a_hexa(rgb) -> str:
    return "#" + "".join(f"{int(round(float(v))):02x}" for v in np.clip(rgb, 0, 255))


def lineal(rgb) -> np.ndarray:
    c = np.asarray(rgb, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def de_lineal(lin) -> np.ndarray:
    c = np.clip(np.asarray(lin, dtype=float), 0.0, 1.0)
    return 255.0 * np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)


def luminancia(rgb) -> float:
    return float(lineal(rgb) @ np.array([0.2126, 0.7152, 0.0722]))


def contraste(a, b) -> float:
    """Razón de contraste WCAG 2.x entre dos colores sRGB (1 a 21)."""
    la, lb = luminancia(a), luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mezclar(color, alfa: float, fondo) -> np.ndarray:
    """Color que resulta de pintar `color` con opacidad `alfa` sobre `fondo`."""
    return alfa * np.asarray(color, dtype=float) + (1 - alfa) * np.asarray(fondo, dtype=float)


def simular(rgb, tipo: str | None) -> np.ndarray:
    if tipo is None:
        return np.asarray(rgb, dtype=float)
    return de_lineal(np.array(DALTONISMO[tipo]) @ lineal(rgb))


def lab(rgb) -> np.ndarray:
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = (m @ lineal(rgb)) / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def delta_e(a, b, tipo: str | None = None) -> float:
    """Diferencia de color CIE76 (ΔE*ab); con `tipo`, como la vería una persona con ese daltonismo."""
    return float(np.linalg.norm(lab(simular(a, tipo)) - lab(simular(b, tipo))))


def filtro_css(rgb: np.ndarray, sepia: float, saturate: float, brightness: float, contrast: float) -> np.ndarray:
    """sepia() saturate() brightness() contrast() de CSS, en ese orden, sobre píxeles sRGB [n, 3]."""
    c = np.asarray(rgb, dtype=float) / 255.0
    a = 1 - sepia
    m_sepia = np.array([[0.393 + 0.607 * a, 0.769 - 0.769 * a, 0.189 - 0.189 * a],
                        [0.349 - 0.349 * a, 0.686 + 0.314 * a, 0.168 - 0.168 * a],
                        [0.272 - 0.272 * a, 0.534 - 0.534 * a, 0.131 + 0.869 * a]])
    s = saturate
    m_sat = np.array([[0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
                      [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
                      [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s]])
    c = np.clip(c @ m_sepia.T, 0, 1)
    c = np.clip(c @ m_sat.T, 0, 1)
    c = np.clip(c * brightness, 0, 1)
    c = np.clip((c - 0.5) * contrast + 0.5, 0, 1)
    return 255.0 * c


# ---------------------------------------------------------------------------
# Paleta y fondos
# ---------------------------------------------------------------------------
def leer_paleta() -> dict:
    texto = ARCHIVO_PALETA.read_text(encoding="utf-8")
    m = re.search(r"/\* paleta:inicio \*/(.*?)/\* paleta:fin \*/", texto, re.S)
    if not m:
        raise SystemExit(f"No se encontró la paleta en {ARCHIVO_PALETA}")
    return json.loads(m.group(1))


def _tesela(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def _pixeles(base: str, z: int, x: int, y: int) -> np.ndarray:
    from PIL import Image

    ruta = DIR_TESELAS / f"{base}_{z}_{x}_{y}"
    if not ruta.is_file():
        DIR_TESELAS.mkdir(parents=True, exist_ok=True)
        pedido = urllib.request.Request(URLS[base].format(z=z, x=x, y=y), headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(pedido, timeout=60) as r:
            ruta.write_bytes(r.read())
    return np.asarray(Image.open(io.BytesIO(ruta.read_bytes())).convert("RGB"), dtype=float)


def _tierra_de_la_tesela(z: int, x: int, y: int) -> np.ndarray:
    n = 2 ** z
    px = (np.arange(256) + 0.5) / 256
    lon = (x + px) / n * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + px) / n))))
    glon, glat = np.meshgrid(lon, lat)
    return costa.en_tierra(glon, glat)


def medir_fondo(base: str) -> dict:
    """Mediana de tierra y de mar en las teselas de `base`, y sus extremos claro y oscuro."""
    tierra, mar, teselas = [], [], []
    for lat, lon in ZONAS:
        x, y = _tesela(lat, lon, ZOOM)
        img = _pixeles(base, ZOOM, x, y).reshape(-1, 3)
        if base == "calles":
            img = filtro_css(img, **FILTRO_CALLES)
        es_tierra = _tierra_de_la_tesela(ZOOM, x, y).ravel()
        tierra.append(img[es_tierra])
        mar.append(img[~es_tierra])
        teselas.append(f"{ZOOM}/{x}/{y}")
    tierra, mar = np.concatenate(tierra), np.concatenate(mar)

    def resumen(px: np.ndarray) -> dict:
        lum = lineal(px) @ np.array([0.2126, 0.7152, 0.0722])
        claro, oscuro = px[lum >= np.percentile(lum, 90)], px[lum <= np.percentile(lum, 10)]
        return {"mediana": a_hexa(np.median(px, axis=0)), "claro": a_hexa(np.median(claro, axis=0)),
                "oscuro": a_hexa(np.median(oscuro, axis=0)), "pixeles": int(len(px))}

    return {"tierra": resumen(tierra), "mar": resumen(mar), "teselas": teselas,
            "filtro": FILTRO_CALLES if base == "calles" else None}


def fondos(paleta: dict, sin_descarga: bool) -> dict:
    carta = paleta["carta"]
    f = {"carta": {"tierra": {"mediana": a_hexa(carta["tierraCarta"])}, "mar": {"mediana": a_hexa(carta["marCarta"])},
                   "origen": "constantes de la paleta (la carta se pinta con ellas)"}}
    previos = json.loads(SALIDA_JSON.read_text(encoding="utf-8"))["fondos"] if SALIDA_JSON.is_file() else {}
    for base in ("satelite", "calles"):
        if sin_descarga:
            if base not in previos:
                raise SystemExit(f"Faltan los fondos de «{base}» en {SALIDA_JSON}; corre el script sin --sin-descarga.")
            f[base] = previos[base]
        else:
            f[base] = medir_fondo(base)
            f[base]["origen"] = f"teselas de zoom {ZOOM} clasificadas con la máscara de costa del modelo"
    return f


# ---------------------------------------------------------------------------
# Medición
# ---------------------------------------------------------------------------
def elementos(p: dict, mar: np.ndarray) -> list[tuple[str, np.ndarray, str]]:
    """(nombre, color, forma) de cada elemento del sargazo en un mapa base. La trama de la
    densidad se mide como su línea ya mezclada con el mar, que es sobre lo que se pinta."""
    filas = [(f"Partícula a flote, {v}", hexa(c), "cuadro relleno con borde")
             for v, c in zip(("lenta", "media", "rápida"), p["sargazo"])]
    for alfa, rango in zip(ALFA_DENSIDAD, ("0.2–1 %", "1–5 %", "5–20 %", "≥ 20 %")):
        filas.append((f"Densidad {rango} (línea de la trama)", mezclar(hexa(p["densidad"]), alfa, mar), "trama diagonal"))
    filas.append(("Zona con el 90 % (línea)", mezclar(hexa(p["zona"]), 0.8, mar), "línea fina"))
    filas.append(("Varado", hexa(p["varada"]), "anillo hueco con halo"))
    return filas


def medir(paleta: dict, f: dict) -> dict:
    resultado = {}
    for base, p in paleta.items():
        tierra, mar = hexa(f[base]["tierra"]["mediana"]), hexa(f[base]["mar"]["mediana"])
        extremos = {}
        for nombre, zona in (("tierra", "tierra"), ("mar", "mar")):
            for extremo in ("claro", "oscuro"):
                if extremo in f[base][zona]:
                    extremos[f"{nombre}_{extremo}"] = hexa(f[base][zona][extremo])
        filas = []
        for nombre, color, forma in elementos(p, mar):
            fila = {"elemento": nombre, "color": a_hexa(color), "forma": forma,
                    "tierra": round(contraste(color, tierra), 2), "mar": round(contraste(color, mar), 2)}
            for k, v in extremos.items():
                fila[k] = round(contraste(color, v), 2)
            filas.append(fila)
        medio = hexa(p["sargazo"][1])
        distincion = {}
        for tipo in (None, *DALTONISMO):
            distincion[tipo or "visión normal"] = {
                "tierra": round(delta_e(medio, tierra, tipo), 1), "mar": round(delta_e(medio, mar, tipo), 1),
                "varado": round(delta_e(medio, hexa(p["varada"]), tipo), 1),
                "borde": round(delta_e(medio, hexa(p["bordeSargazo"]), tipo), 1),
            }
        resultado[base] = {
            "tierra": a_hexa(tierra), "mar": a_hexa(mar), "elementos": filas, "delta_e": distincion,
            "borde_vs_particula": [round(contraste(hexa(p["bordeSargazo"]), hexa(c)), 2) for c in p["sargazo"]],
            "halo_vs_varado": round(contraste(hexa(p["haloVarada"]), hexa(p["varada"])), 2),
        }
    return resultado


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
def _n(v: float) -> str:
    return f"{v:.1f}" if v < MINIMO else f"**{v:.1f}**"


def tabla_readme(r: dict) -> list[str]:
    """Tabla compacta: cada elemento contra tierra y mar (medianas) en los tres mapas base."""
    md = ["| Elemento | Forma | Carta: tierra · mar | Satélite: tierra · mar | Calles: tierra · mar |", "|---|---|---|---|---|"]
    for k, fila in enumerate(r["carta"]["elementos"]):
        celdas = []
        for base in ("carta", "satelite", "calles"):
            e = r[base]["elementos"][k]
            celdas.append(f"{_n(e['tierra'])} · {_n(e['mar'])}")
        md.append(f"| {fila['elemento']} | {fila['forma']} | " + " | ".join(celdas) + " |")
    return md


def bloque_readme(r: dict, f: dict) -> list[str]:
    md = [
        "Razón de contraste WCAG (1 = igual, 21 = negro sobre blanco) contra la **mediana** de la tierra y del mar de "
        f"cada mapa base; en negritas, lo que llega a {MINIMO:g}:1, el mínimo de WCAG para objetos gráficos. Lo genera "
        "`python scripts/medir_contraste.py`; detalle y extremos claro y oscuro en [`docs/contraste.md`](docs/contraste.md).",
        "",
        *tabla_readme(r),
        "",
        "Fondos medidos: " + "; ".join(f"{NOMBRES_BASE[b].lower()}: tierra `{r[b]['tierra']}` y mar `{r[b]['mar']}`" for b in r) + ".",
        "",
        "Diferencia de color ΔE (CIE76; más de ~10 ya se distingue a simple vista) entre la partícula a flote media y lo "
        "que la rodea, con visión normal y con daltonismo simulado:",
        "",
        "| Mapa base | Visión | vs tierra | vs mar | vs varado |",
        "|---|---|---|---|---|",
    ]
    for base in r:
        for tipo, d in r[base]["delta_e"].items():
            md.append(f"| {NOMBRES_BASE[base]} | {tipo} | {d['tierra']:.0f} | {d['mar']:.0f} | {d['varado']:.0f} |")
    return md


def escribir_md(r: dict, f: dict, generado: str) -> None:
    md = [
        "# Contraste de la paleta del sargazo",
        "",
        f"Generado por `python scripts/medir_contraste.py` el {generado}. No editar a mano.",
        "",
        "El sargazo se dibuja en púrpura sobre la carta y las calles y en rosa claro sobre el satélite: un tono que no "
        "aparece en la tierra ni en el mar de ningún mapa base. Además del tono, cada cosa tiene su forma: lo que flota es "
        "un cuadro relleno con borde, lo varado es un anillo hueco con halo y la densidad es una trama de líneas diagonales.",
        "",
        "## Cómo se mide",
        "",
        "- **Razón de contraste** WCAG 2.x entre dos colores: (L₁ + 0.05) / (L₂ + 0.05), con L la luminancia relativa. "
        f"El criterio 1.4.11 pide al menos {MINIMO:g}:1 para objetos gráficos.",
        "- **Fondos.** En la carta propia son los colores con que se pinta. En el satélite y en las calles se miden en "
        f"teselas reales de zoom {ZOOM} de ocho zonas del dominio (Cancún, canal de Cozumel, Tulum, Mahahual, Holbox, "
        "Progreso, mar abierto y Sian Ka'an): cada píxel se clasifica como tierra o mar con la máscara de costa del modelo. "
        "Se reporta la mediana y, como extremos, la mediana del decil más claro y del más oscuro. A las calles se les aplica "
        "el mismo filtro sepia que usa la interfaz.",
        "- **Densidad y zona.** Se pintan con transparencia y solo sobre el mar: se mide el color de su línea ya mezclado "
        "con el mar del mapa base.",
        "- **Daltonismo.** ΔE (CIE76) entre la partícula a flote media y lo que la rodea, con los colores transformados "
        "por las matrices de Machado, Oliveira y Fernandes (2009) para protanopía, deuteranopía y tritanopía completas.",
        "",
    ]
    for base in r:
        fb, rb = f[base], r[base]
        md += [f"## {NOMBRES_BASE[base]}", ""]
        partes = [f"tierra `{rb['tierra']}`", f"mar `{rb['mar']}`"]
        for zona in ("tierra", "mar"):
            for extremo in ("claro", "oscuro"):
                if extremo in fb[zona]:
                    partes.append(f"{zona} {extremo} `{fb[zona][extremo]}`")
        md += ["Fondos: " + ", ".join(partes) + f". Origen: {fb['origen']}.", ""]
        extremos = [k for k in ("tierra_claro", "tierra_oscuro", "mar_claro", "mar_oscuro") if k in rb["elementos"][0]]
        md.append("| Elemento | Color | Forma | Tierra | Mar | " + " | ".join(e.replace("_", " ") for e in extremos) + (" |" if extremos else ""))
        md.append("|---|---|---|---|---|" + "---|" * len(extremos))
        for e in rb["elementos"]:
            md.append(f"| {e['elemento']} | `{e['color']}` | {e['forma']} | {_n(e['tierra'])} | {_n(e['mar'])} | "
                      + " | ".join(_n(e[k]) for k in extremos) + (" |" if extremos else ""))
        md += ["",
               f"Borde contra el relleno de la partícula (lenta, media, rápida): {', '.join(f'{v:.1f}' for v in rb['borde_vs_particula'])}. "
               f"Halo contra el anillo de lo varado: {rb['halo_vs_varado']:.1f}.", "",
               "| Visión | ΔE vs tierra | ΔE vs mar | ΔE vs varado | ΔE vs su borde |", "|---|---|---|---|---|"]
        for tipo, d in rb["delta_e"].items():
            md.append(f"| {tipo} | {d['tierra']:.0f} | {d['mar']:.0f} | {d['varado']:.0f} | {d['borde']:.0f} |")
        md.append("")
    md += [
        "## Lo que no llega a 3:1 y por qué",
        "",
        "- **Las clases bajas de densidad** (menos de 5 % por celda) son tenues a propósito: poca opacidad es poco "
        "sargazo. La información de dónde hay sargazo la dan las partículas, que sí cumplen.",
        "- **Sobre lo más claro del satélite** (playas, zonas urbanas y bajos de arena) el rosa claro pierde contraste de "
        "luminancia. Ahí cada partícula se distingue por su borde oscuro y por el tono, que no existe en la imagen.",
        "- **Sobre lo más oscuro de las calles** (selva en verde) la partícula lenta, la más clara, queda cerca del "
        "mínimo; el borde claro la separa.",
        "",
    ]
    SALIDA_MD.write_text("\n".join(md), encoding="utf-8", newline="\n")


def escribir_readme(r: dict, f: dict) -> bool:
    texto = README.read_text(encoding="utf-8")
    ini, fin = "<!-- contraste:inicio (generado por scripts/medir_contraste.py; no editar a mano) -->", "<!-- contraste:fin -->"
    if ini not in texto or fin not in texto:
        return False
    nuevo = texto[:texto.index(ini) + len(ini)] + "\n" + "\n".join(bloque_readme(r, f)) + "\n" + texto[texto.index(fin):]
    README.write_text(nuevo, encoding="utf-8", newline="\n")
    return True


def principal(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sin-descarga", action="store_true", help="usa los fondos ya medidos en docs/contraste.json")
    a = ap.parse_args(argv)
    paleta = leer_paleta()
    f = fondos(paleta, a.sin_descarga)
    r = medir(paleta, f)
    generado = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    previo = json.loads(SALIDA_JSON.read_text(encoding="utf-8")) if SALIDA_JSON.is_file() else {}
    datos = {"generado": previo.get("generado", generado) if a.sin_descarga else generado, "minimo_wcag": MINIMO,
             "zoom": ZOOM, "zonas": ZONAS, "fondos": f, "contraste": r}
    SALIDA_JSON.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    escribir_md(r, f, datos["generado"])
    en_readme = escribir_readme(r, f)
    print("\n".join(tabla_readme(r)))
    for base in r:
        print(base, r[base]["delta_e"], "borde:", r[base]["borde_vs_particula"], "halo:", r[base]["halo_vs_varado"])
    print(f"Escritos {SALIDA_JSON.name}, {SALIDA_MD.name}" + (" y el bloque del README" if en_readme else " (el README no tiene el bloque «contraste»)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
