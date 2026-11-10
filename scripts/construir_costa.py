"""Construye la costa del modelo y las localidades del mapa a partir de datos abiertos.

    python scripts/construir_costa.py               # descarga (con caché) y construye todo
    python scripts/construir_costa.py --sin-descarga  # solo reconstruye desde la caché

Qué produce (todo queda versionado en src/model/datos/):

  costa.npz          máscara de tierra del modelo, 1 bit por celda de 0.001° (~105 m), y una
                     máscara de contexto de 0.01° para dibujar la tierra fuera del dominio.
  costa.json         procedencia: fuente, licencia, fecha de los datos, tamaños y huellas.
  localidades.json   ciudades, pueblos, islas, cabos y puertos del dominio con su id de OSM.

Fuentes:

- Línea de costa: vías `natural=coastline` de OpenStreetMap (ODbL), por la API Overpass. Es
  la misma costa que dibuja el mapa base, así que lo que el modelo llama «tierra» coincide
  con lo que se ve. Se rasteriza la línea y se inunda el mar desde puntos de mar abierto:
  todo lo que el mar no alcanza es tierra (incluye lagunas cerradas y canales de menos de
  ~200 m, que el modelo no resuelve).
- Contexto fuera del dominio (solo dibujo): Natural Earth 10 m, dominio público.
- Localidades: poblados (`place=city|town|village|hamlet|locality`), islas, cabos, arrecifes,
  bahías y canales con nombre de OpenStreetMap. Puertos y terminales marítimas según las
  etiquetas `harbour`, `seamark:type=harbour`, `amenity=ferry_terminal`, `landuse=harbour` e
  `industrial=port`: cada uno marca a su poblado más cercano (≤ 8 km).

Necesita scipy (requirements-validacion.txt). La app solo lee los archivos resultantes.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN  # noqa: E402
from src.model.costa import (  # noqa: E402
    ARCHIVO_COSTA, ARCHIVO_LOCALIDADES, ARCHIVO_PROCEDENCIA, CONTEXTO, MALLA_COSTA,
)

DIR_CACHE = RAIZ / "data" / "costa"
AGENTE = "PMS-sargazo/0.5 (scripts/construir_costa.py; github.com/renecano/sargazo_prototipo)"
OVERPASS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
NATURAL_EARTH = {
    "land": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip",
    "minor_islands": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_minor_islands.zip",
}

# Recuadro de descarga (O, S, E, N): la malla de la máscara más un margen, para que ninguna
# vía de costa quede cortada dentro de la máscara.
MARGEN_DESCARGA = 0.3
TESELAS = (4, 4)                  # columnas × filas de consultas a Overpass
PASO_MUESTREO = 0.0004            # densificación de la línea (< media celda de la máscara)
# Mar abierto conocido (lon, lat): Caribe, Golfo de México y Canal de Yucatán.
SEMILLAS_MAR = [(-86.0, 21.0), (-90.0, 22.5), (-85.0, 18.0), (-91.5, 20.0), (-85.5, 22.6)]
# Comprobaciones mínimas de cordura (lon, lat).
DEBE_SER_TIERRA = {"Mérida": (-89.62, 20.97), "Valladolid": (-88.20, 20.69), "centro de Cancún": (-86.83, 21.16),
                   "centro de Cozumel": (-86.90, 20.43), "Isla Mujeres": (-86.737, 21.235), "Chetumal": (-88.31, 18.51)}
DEBE_SER_MAR = {"Bahía de Mujeres": (-86.768, 21.188), "canal de Cozumel": (-87.02, 20.50),
                "Bahía de la Ascensión": (-87.55, 19.70), "Bahía de Chetumal": (-88.10, 18.40),
                "frente a Tulum": (-87.40, 20.20), "frente a Mahahual": (-87.68, 18.71)}
RANGO_AREA_TIERRA_KM2 = (183_000, 196_000)   # GSHHG full da 189 183 km² en el dominio

DIST_COSTA_LOCALIDAD_KM = 6.0
DIST_PUERTO_KM = 8.0
AREA_MAX_ISLA_KM2 = 5000.0
TIPOS_POBLADO = ("city", "town", "village", "hamlet", "locality")
# Rango de cada tipo de lugar (1 = se rotula desde el zoom más lejano). Los poblados suben de
# rango con su población.
TIPOS_LUGAR = {"city": 1, "town": 2, "island": 2, "village": 3, "cape": 3, "reef": 3, "bay": 3, "strait": 3,
               "archipelago": 3, "hamlet": 4, "islet": 4, "locality": 4}


def registrar(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Descargas con caché
# ---------------------------------------------------------------------------
def _descargar(url: str, datos: bytes | None = None, espera: float = 150.0) -> bytes:
    pedido = urllib.request.Request(url, data=datos, headers={"User-Agent": AGENTE, "Accept": "*/*"})
    with urllib.request.urlopen(pedido, timeout=espera) as r:
        return r.read()


def overpass(consulta: str, cache: Path, sin_descarga: bool) -> dict:
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    if sin_descarga:
        raise SystemExit(f"Falta {cache} y se pidió --sin-descarga.")
    cuerpo = urllib.parse.urlencode({"data": consulta}).encode()
    ultimo = None
    for intento in range(9):
        url = OVERPASS[intento % len(OVERPASS)]
        try:
            j = json.loads(_descargar(url, cuerpo).decode("utf-8"))
            if "elements" not in j or j.get("remark"):
                raise ValueError(j.get("remark", "respuesta sin elementos"))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            return j
        except (urllib.error.URLError, TimeoutError, ValueError, ConnectionError) as e:
            ultimo = e
            pausa = 15 * (intento + 1)
            registrar(f"   Overpass no respondió ({url.split('/')[2]}: {str(e)[:80]}); reintento en {pausa} s")
            time.sleep(pausa)
    raise SystemExit(f"Overpass falló tras varios intentos: {ultimo}")


def recuadro_descarga() -> tuple[float, float, float, float]:
    m = MALLA_COSTA
    return (m["lon0"] - MARGEN_DESCARGA, m["lat0"] - MARGEN_DESCARGA,
            m["lon0"] + m["nx"] * m["paso"] + MARGEN_DESCARGA, m["lat0"] + m["ny"] * m["paso"] + MARGEN_DESCARGA)


def descargar_costa(sin_descarga: bool) -> tuple[list[np.ndarray], str]:
    """Vías de costa de OSM (sin repetir) y la fecha más antigua de los datos entre las teselas."""
    o, s, e, n = recuadro_descarga()
    nc, nf = TESELAS
    vias: dict[tuple[int, int], np.ndarray] = {}
    fechas = []
    incompletas = 0
    for i in range(nf):
        for j in range(nc):
            w, x = o + j * (e - o) / nc, o + (j + 1) * (e - o) / nc
            a, b = s + i * (n - s) / nf, s + (i + 1) * (n - s) / nf
            consulta = f'[out:json][timeout:240];way["natural"="coastline"]({a:.4f},{w:.4f},{b:.4f},{x:.4f});out geom;'
            r = overpass(consulta, DIR_CACHE / "osm" / f"costa_{i}_{j}.json", sin_descarga)
            fechas.append(r.get("osm3s", {}).get("timestamp_osm_base", ""))
            for el in r["elements"]:
                if el["type"] != "way" or (el["id"], 0) in vias:
                    continue
                # Un servidor puede devolver vértices nulos (nodo que le falta): la vía se parte
                # ahí y la comprobación de la inundación detecta si el corte abre la costa.
                tramo, k = [], 0
                for p in el["geometry"] + [None]:
                    if p is not None:
                        tramo.append((p["lon"], p["lat"]))
                        continue
                    if len(tramo) >= 2 or k == 0:
                        vias[(el["id"], k)] = np.array(tramo, dtype=float).reshape(-1, 2)
                        k += 1
                    tramo = []
                incompletas += k > 1
            registrar(f"   tesela {i},{j}: {len(r['elements'])} vías (acumuladas {len({v for v, _ in vias})})")
    if incompletas:
        registrar(f"   aviso: {incompletas} vías llegaron con vértices nulos y se partieron")
    return list(vias.values()), min(f for f in fechas if f)


# ---------------------------------------------------------------------------
# Máscara de tierra por inundación
# ---------------------------------------------------------------------------
def rasterizar_lineas(vias: list[np.ndarray], m: dict) -> np.ndarray:
    barrera = np.zeros((m["ny"], m["nx"]), dtype=bool)
    for xy in vias:
        if len(xy) < 2:
            continue
        a, b = xy[:-1], xy[1:]
        n = np.maximum(1, np.ceil(np.abs(b - a).max(axis=1) / PASO_MUESTREO).astype(int))
        idx = np.repeat(np.arange(len(a)), n + 1)
        t = np.concatenate([np.linspace(0.0, 1.0, k + 1) for k in n])
        p = a[idx] + (b[idx] - a[idx]) * t[:, None]
        j = np.floor((p[:, 0] - m["lon0"]) / m["paso"]).astype(np.int64)
        i = np.floor((p[:, 1] - m["lat0"]) / m["paso"]).astype(np.int64)
        ok = (i >= 0) & (i < m["ny"]) & (j >= 0) & (j < m["nx"])
        barrera[i[ok], j[ok]] = True
    return barrera


def inundar(barrera: np.ndarray, m: dict) -> np.ndarray:
    """Tierra = todo lo que el mar abierto no alcanza (vecindad de 4, no cruza diagonales)."""
    from scipy import ndimage

    etiquetas, _ = ndimage.label(~barrera)
    ids = set()
    for lon, lat in SEMILLAS_MAR:
        i, j = int((lat - m["lat0"]) / m["paso"]), int((lon - m["lon0"]) / m["paso"])
        if barrera[i, j]:
            raise SystemExit(f"La semilla de mar ({lat}, {lon}) cayó sobre la línea de costa.")
        ids.add(int(etiquetas[i, j]))
    if len(ids) != 1:
        raise SystemExit(f"Las semillas de mar quedaron en {len(ids)} cuerpos de agua distintos: la costa tiene un corte.")
    return etiquetas != ids.pop()


def indices(m: dict, lon, lat):
    return (np.floor((np.asarray(lat) - m["lat0"]) / m["paso"]).astype(np.int64),
            np.floor((np.asarray(lon) - m["lon0"]) / m["paso"]).astype(np.int64))


def area_tierra_dominio_km2(tierra: np.ndarray, m: dict) -> float:
    lat = m["lat0"] + (np.arange(m["ny"]) + 0.5) * m["paso"]
    lon = m["lon0"] + (np.arange(m["nx"]) + 0.5) * m["paso"]
    fil = (lat >= LAT_MIN) & (lat <= LAT_MAX)
    col = (lon >= LON_MIN) & (lon <= LON_MAX)
    km = m["paso"] * 111.195
    return float((tierra[np.ix_(fil, col)].sum(axis=1) * km * km * np.cos(np.radians(lat[fil]))).sum())


def comprobar(tierra: np.ndarray, m: dict) -> float:
    for nombre, (lon, lat) in DEBE_SER_TIERRA.items():
        i, j = indices(m, lon, lat)
        if not tierra[i, j]:
            raise SystemExit(f"Comprobación fallida: {nombre} ({lat}, {lon}) quedó como mar.")
    for nombre, (lon, lat) in DEBE_SER_MAR.items():
        i, j = indices(m, lon, lat)
        if tierra[i, j]:
            raise SystemExit(f"Comprobación fallida: {nombre} ({lat}, {lon}) quedó como tierra.")
    area = area_tierra_dominio_km2(tierra, m)
    if not RANGO_AREA_TIERRA_KM2[0] <= area <= RANGO_AREA_TIERRA_KM2[1]:
        raise SystemExit(f"Área de tierra en el dominio fuera de rango: {area:.0f} km² (esperado {RANGO_AREA_TIERRA_KM2}).")
    return area


# ---------------------------------------------------------------------------
# Contexto fuera del dominio (Natural Earth 10 m)
# ---------------------------------------------------------------------------
def leer_poligonos_shp(crudo: bytes, recuadro) -> list[list[np.ndarray]]:
    """Polígonos (lista de anillos) de un .shp que tocan el recuadro (O, S, E, N)."""
    o, s, e, n = recuadro
    poligonos, p = [], 100
    while p < len(crudo):
        largo = struct.unpack(">i", crudo[p + 4:p + 8])[0] * 2
        c = p + 8
        if struct.unpack("<i", crudo[c:c + 4])[0] == 5:
            x0, y0, x1, y1 = struct.unpack("<4d", crudo[c + 4:c + 36])
            if not (x1 < o or x0 > e or y1 < s or y0 > n):
                npartes, npuntos = struct.unpack("<2i", crudo[c + 36:c + 44])
                partes = list(np.frombuffer(crudo, "<i4", npartes, c + 44)) + [npuntos]
                xy = np.frombuffer(crudo, "<f8", 2 * npuntos, c + 44 + 4 * npartes).reshape(-1, 2)
                poligonos.append([xy[partes[k]:partes[k + 1]] for k in range(npartes)])
        p = c + largo
    return poligonos


def rasterizar_poligonos(poligonos, m: dict) -> np.ndarray:
    """Relleno par-impar por líneas de barrido en los centros de celda."""
    lon0, lat0, paso, nx, ny = m["lon0"], m["lat0"], m["paso"], m["nx"], m["ny"]
    mascara = np.zeros((ny, nx), dtype=bool)
    for anillos in poligonos:
        filas, cruces = [], []
        for r in anillos:
            x1, y1, x2, y2 = r[:-1, 0], r[:-1, 1], r[1:, 0], r[1:, 1]
            i1 = np.clip(np.ceil((np.minimum(y1, y2) - lat0) / paso - 0.5).astype(int), 0, ny)
            i2 = np.clip(np.ceil((np.maximum(y1, y2) - lat0) / paso - 0.5).astype(int), 0, ny)
            cuenta = i2 - i1
            sel = cuenta > 0
            if not sel.any():
                continue
            idx = np.repeat(np.flatnonzero(sel), cuenta[sel])
            fil = np.concatenate([np.arange(a, b) for a, b in zip(i1[sel], i2[sel])])
            y = lat0 + (fil + 0.5) * paso
            filas.append(fil)
            cruces.append(x1[idx] + (y - y1[idx]) * (x2[idx] - x1[idx]) / (y2[idx] - y1[idx]))
        if not filas:
            continue
        filas, cruces = np.concatenate(filas), np.concatenate(cruces)
        orden = np.lexsort((cruces, filas))
        filas, cruces = filas[orden], cruces[orden]
        cols = np.clip(np.ceil((cruces - lon0) / paso - 0.5).astype(int), 0, nx)
        for f in np.unique(filas):
            c = cols[filas == f]
            for a, b in zip(c[0::2], c[1::2]):
                mascara[f, a:b] = True
    return mascara


def construir_contexto(sin_descarga: bool) -> np.ndarray:
    m = CONTEXTO
    recuadro = (m["lon0"], m["lat0"], m["lon0"] + m["nx"] * m["paso"], m["lat0"] + m["ny"] * m["paso"])
    poligonos = []
    for nombre, url in NATURAL_EARTH.items():
        cache = DIR_CACHE / "natural_earth" / f"ne_10m_{nombre}.zip"
        if not cache.is_file():
            if sin_descarga:
                raise SystemExit(f"Falta {cache} y se pidió --sin-descarga.")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(_descargar(url))
        with zipfile.ZipFile(io.BytesIO(cache.read_bytes())) as z:
            poligonos += leer_poligonos_shp(z.read(f"ne_10m_{nombre}.shp"), recuadro)
    return rasterizar_poligonos(poligonos, m)


# ---------------------------------------------------------------------------
# Localidades
# ---------------------------------------------------------------------------
def distancia_a_tierra_km(tierra: np.ndarray, m: dict, lon: float, lat: float, ventana_km: float = 12.0) -> float:
    """Distancia (km) de un punto a la celda de mar más cercana si está en tierra, o a la de
    tierra más cercana si está en el mar: en ambos casos, distancia a la costa."""
    v = int(ventana_km / 111.195 / m["paso"])
    i, j = (int(k) for k in indices(m, lon, lat))
    if not (0 <= i < m["ny"] and 0 <= j < m["nx"]):
        return np.inf
    a, b, c, d = max(i - v, 0), min(i + v + 1, m["ny"]), max(j - v, 0), min(j + v + 1, m["nx"])
    recorte = tierra[a:b, c:d]
    ii, jj = np.nonzero(recorte != tierra[i, j])
    if not ii.size:
        return np.inf
    dy = (ii + a - i) * m["paso"] * 111.195
    dx = (jj + c - j) * m["paso"] * 111.195 * np.cos(np.radians(lat))
    return float(np.hypot(dx, dy).min())


def construir_localidades(tierra: np.ndarray, m: dict, sin_descarga: bool) -> tuple[list[dict], str]:
    from scipy import ndimage

    etiquetas, _ = ndimage.label(tierra)
    celdas = np.bincount(etiquetas.ravel())

    def isla_de(lon: float, lat: float) -> tuple[int, float]:
        """(componente, área en km²) de la isla de la máscara que contiene el punto, o la más
        cercana a ≤ 2.5 km (el centro de una isla alargada puede caer en el agua); (0, 0) si
        ahí no hay tierra."""
        i, j = (int(k) for k in indices(m, lon, lat))
        v = 25
        a0, c0 = max(i - v, 0), max(j - v, 0)
        recorte = etiquetas[a0:i + v + 1, c0:j + v + 1]
        ii, jj = np.nonzero(recorte)
        if not ii.size:
            return 0, 0.0
        k = int(np.argmin(np.hypot(ii + a0 - i, jj + c0 - j)))
        comp = int(recorte[ii[k], jj[k]])
        km = m["paso"] * 111.195
        return comp, float(celdas[comp] * km * km * np.cos(np.radians(lat)))

    s, o, n, e = LAT_MIN, LON_MIN, LAT_MAX, LON_MAX
    caja = f"({s},{o},{n},{e})"
    lugares = overpass(
        f'[out:json][timeout:180];(node["place"~"^(city|town|village|hamlet|locality)$"]["name"]{caja};'
        f'nwr["place"~"^(island|islet|archipelago)$"]["name"]{caja};'
        f'nwr["natural"~"^(cape|reef|bay|strait)$"]["name"]{caja};);out center tags;',
        DIR_CACHE / "osm" / "lugares_v2.json", sin_descarga)
    puertos = overpass(
        f'[out:json][timeout:180];(nwr["harbour"="yes"]{caja};nwr["seamark:type"="harbour"]{caja};'
        f'nwr["amenity"="ferry_terminal"]{caja};nwr["landuse"="harbour"]{caja};nwr["industrial"="port"]{caja};);out center tags;',
        DIR_CACHE / "osm" / "puertos.json", sin_descarga)

    def centro(el):
        c = el.get("center", el)
        return (float(c["lon"]), float(c["lat"])) if "lon" in c else None

    filas = []
    for el in lugares["elements"]:
        et = el.get("tags", {})
        nombre = et.get("name:es") or et.get("name")
        tipo = et.get("place") if et.get("place") in TIPOS_LUGAR else et.get("natural")
        pos = centro(el)
        if not nombre or tipo not in TIPOS_LUGAR or pos is None:
            continue
        lon, lat = pos
        if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
            continue                                   # p. ej. «Cuba», cuyo centro cae fuera del dominio
        dist = distancia_a_tierra_km(tierra, m, lon, lat)
        if tipo in TIPOS_POBLADO and tipo != "city" and dist > DIST_COSTA_LOCALIDAD_KM:
            continue
        try:
            poblacion = int(str(et.get("population", "")).replace(",", "").replace(" ", "").split(".")[0])
        except ValueError:
            poblacion = None
        rango = TIPOS_LUGAR[tipo]
        if poblacion is not None and tipo in TIPOS_POBLADO:
            por_poblacion = 1 if poblacion >= 100_000 else 2 if poblacion >= 10_000 else 3 if poblacion >= 1_000 else 4
            # Una «city» de menos de 10 000 habitantes se rotula según su población.
            rango = por_poblacion if (tipo == "city" and poblacion < 10_000) else min(rango, por_poblacion)
        area, comp = None, 0
        if tipo in ("island", "islet"):
            # Las islas se ordenan por su tamaño en la máscara del modelo. Las de lagunas y
            # ríos, que la máscara une al continente, no son islas para el modelo: se omiten.
            comp, area = isla_de(lon, lat)
            if area > AREA_MAX_ISLA_KM2:
                continue
            rango = 2 if area >= 50 else 3 if area >= 2 else 4
        filas.append({
            "nombre": nombre, "lat": round(lat, 5), "lon": round(lon, 5), "tipo": tipo, "rango": rango,
            "poblacion": poblacion, "distancia_costa_km": None if not np.isfinite(dist) else round(dist, 2),
            "area_km2": None if area is None else round(area, 1), "_comp": comp,
            "puerto": False, "puertos_osm": [], "osm": f"{el['type']}/{el['id']}",
        })
    # Varios cayos de un mismo atolón comparten isla en la máscara: solo el más cercano al
    # centro de la isla conserva su rango; los demás se rotulan al final.
    por_isla: dict[int, list[dict]] = {}
    for f in filas:
        if f["_comp"]:
            por_isla.setdefault(f["_comp"], []).append(f)
    if por_isla:
        ids = sorted(por_isla)
        centros = ndimage.center_of_mass(tierra, etiquetas, ids)
        for comp, (ci, cj) in zip(ids, centros):
            clat, clon = m["lat0"] + (ci + 0.5) * m["paso"], m["lon0"] + (cj + 0.5) * m["paso"]
            grupo = sorted(por_isla[comp], key=lambda f: (f["tipo"] != "island", np.hypot(f["lon"] - clon, f["lat"] - clat)))
            for f in grupo[1:]:
                f["rango"] = 4
    for f in filas:
        del f["_comp"]
    # Un mismo nombre puede venir como poblado y como isla o relación: a menos de 15 km se
    # queda el de mayor rango (y, a igual rango, el poblado).
    filas.sort(key=lambda f: (f["rango"], f["tipo"] not in TIPOS_POBLADO, -(f["poblacion"] or 0), -(f["area_km2"] or 0), f["nombre"]))
    unicas: list[dict] = []
    for f in filas:
        repetida = any(u["nombre"].casefold() == f["nombre"].casefold()
                       and np.hypot((u["lon"] - f["lon"]) * np.cos(np.radians(f["lat"])), u["lat"] - f["lat"]) * 111.195 < 15.0
                       for u in unicas)
        if not repetida:
            unicas.append(f)

    # Cada puerto o terminal marítima de OSM se asigna a su poblado más cercano (≤ 8 km).
    poblados = [f for f in unicas if f["tipo"] in TIPOS_POBLADO and f["rango"] <= 3]
    for el in puertos["elements"]:
        pos = centro(el)
        if pos is None or not poblados:
            continue
        d = [np.hypot((f["lon"] - pos[0]) * np.cos(np.radians(pos[1])), f["lat"] - pos[1]) * 111.195 for f in poblados]
        k = int(np.argmin(d))
        if d[k] <= DIST_PUERTO_KM:
            poblados[k]["puerto"] = True
            if len(poblados[k]["puertos_osm"]) < 3:
                poblados[k]["puertos_osm"].append(f"{el['type']}/{el['id']}")
    fecha = min(lugares.get("osm3s", {}).get("timestamp_osm_base", ""), puertos.get("osm3s", {}).get("timestamp_osm_base", ""))
    return unicas, fecha


# ---------------------------------------------------------------------------
def principal(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sin-descarga", action="store_true", help="usa solo lo que ya está en data/costa/")
    a = p.parse_args(argv)
    m = MALLA_COSTA

    registrar("1. Línea de costa de OpenStreetMap")
    vias, fecha_costa = descargar_costa(a.sin_descarga)
    registrar(f"   {len(vias)} vías, {sum(len(v) for v in vias)} vértices; datos de OSM al {fecha_costa}")

    registrar(f"2. Máscara de {m['paso']}° ({m['nx']} × {m['ny']} celdas)")
    barrera = rasterizar_lineas(vias, m)
    tierra = inundar(barrera, m)
    area = comprobar(tierra, m)
    registrar(f"   tierra en el dominio: {area:.0f} km²; celdas de línea de costa: {int(barrera.sum())}")

    registrar("3. Contexto fuera del dominio (Natural Earth 10 m)")
    contexto = construir_contexto(a.sin_descarga)

    registrar("4. Localidades y puertos (OpenStreetMap)")
    localidades, fecha_lugares = construir_localidades(tierra, m, a.sin_descarga)
    registrar(f"   {len(localidades)} localidades; {sum(f['puerto'] for f in localidades)} con puerto o terminal marítima")

    bits = np.packbits(tierra, axis=1)
    bits_contexto = np.packbits(contexto, axis=1)
    ARCHIVO_COSTA.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ARCHIVO_COSTA, tierra=bits, contexto=bits_contexto)
    procedencia = {
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generado_con": "scripts/construir_costa.py",
        "costa": {
            "fuente": "OpenStreetMap, vías natural=coastline (API Overpass)",
            "licencia": "ODbL 1.0",
            "atribucion": "© colaboradores de OpenStreetMap",
            "datos_al": fecha_costa,
            "vias": len(vias), "vertices": int(sum(len(v) for v in vias)),
            "malla": m, "area_tierra_dominio_km2": round(area),
            "sha256_bits": hashlib.sha256(bits.tobytes()).hexdigest(),
            "metodo": "línea rasterizada e inundación del mar desde mar abierto (vecindad de 4)",
        },
        "contexto": {
            "fuente": "Natural Earth 10 m (land + minor islands)", "licencia": "dominio público",
            "atribucion": "Natural Earth", "malla": CONTEXTO, "uso": "solo dibujo, fuera del dominio del modelo",
            "sha256_bits": hashlib.sha256(bits_contexto.tobytes()).hexdigest(),
        },
        "localidades": {
            "fuente": "OpenStreetMap: poblados (place=*), islas, cabos, arrecifes, bahías y canales con nombre; "
                      "puertos por harbour, seamark:type=harbour, amenity=ferry_terminal, landuse=harbour e "
                      f"industrial=port, asignados al poblado más cercano (≤ {DIST_PUERTO_KM:g} km)",
            "licencia": "ODbL 1.0", "atribucion": "© colaboradores de OpenStreetMap", "datos_al": fecha_lugares,
            "criterio": f"ciudades del dominio, poblados a ≤ {DIST_COSTA_LOCALIDAD_KM:g} km de la costa del modelo y "
                        "rasgos geográficos con nombre",
            "total": len(localidades),
        },
    }
    ARCHIVO_PROCEDENCIA.write_text(json.dumps(procedencia, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ARCHIVO_LOCALIDADES.write_text(
        json.dumps(localidades, ensure_ascii=False, separators=(",", ":")).replace("},{", "},\n{") + "\n", encoding="utf-8")
    for ruta in (ARCHIVO_COSTA, ARCHIVO_PROCEDENCIA, ARCHIVO_LOCALIDADES):
        registrar(f"   {ruta.relative_to(RAIZ)}: {ruta.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
