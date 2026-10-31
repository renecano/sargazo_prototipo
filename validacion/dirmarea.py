"""Escribe oleaje real en el MISMO formato que data/semar/dirmarea.txt.

Así la validación entra al producto por la misma puerta: el validador y el lector de
`src/ingestion` leen el archivo sin cambios y el modelo de `src/model` lo usa igual que el
de SEMAR.

Formato (idéntico al archivo de SEMAR):
- Encabezado `LON;LAT;dirolavto;alturaolavto`.
- 41 bloques que empiezan con `DDMMMAAAA 00 h` (h = 0, 3, …, 120).
- Cada bloque: malla de 94 × 51 nodos de 0.16°, lon −98.00…−83.12 de oeste a este y lat
  23…15 de norte a sur, con las columnas LON;LAT escritas exactamente como en el archivo
  de SEMAR (se copian de él cuando está disponible).
- dirolavto = dirección DESDE la que viene la ola de viento (°); alturaolavto en m; dos
  decimales sin ceros a la derecha; `-9.99e+08` donde no hay dato.

Qué nodos llevan dato: solo los nodos de mar del archivo de SEMAR dentro del recuadro del
modelo (el resto queda con relleno: el modelo no los lee). Los valores salen de la ola de
viento de Copernicus Marine (MFWAM) a su resolución nativa, interpolada de forma bilineal a
los nodos de 0.16° (dirección por seno y coseno).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from src.config import (
    COLUMNAS_OLEAJE, DIR_SEMAR, HORIZONTE_H, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, PASO_OLEAJE_H, RESOLUCION_GRADOS,
)
from src.ingestion.lector import formatear_fecha
from src.model.campos import _bilineal

RELLENO_TEXTO = "-9.99e+08"
LON_ORIGEN, LAT_NORTE, NLON, NLAT = -98.0, 23.0, 94, 51


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


@dataclass
class Plantilla:
    """Malla completa de dirmarea.txt en el orden del archivo."""
    coordenadas: list[str]     # "LON;LAT" de cada fila, en el orden del archivo
    lons: np.ndarray           # [NLON] ascendente
    lats: np.ndarray           # [NLAT] ascendente
    fila_i: np.ndarray         # índice de latitud (ascendente) de cada fila del archivo
    fila_j: np.ndarray         # índice de longitud de cada fila del archivo


def plantilla(ruta_semar: Path | None = DIR_SEMAR / "dirmarea.txt") -> Plantilla:
    lons = np.round(LON_ORIGEN + RESOLUCION_GRADOS * np.arange(NLON), 2)
    lats_desc = np.round(LAT_NORTE - RESOLUCION_GRADOS * np.arange(NLAT), 2)
    if ruta_semar is not None and Path(ruta_semar).is_file():
        coordenadas = []
        with open(ruta_semar, encoding="utf-8") as fh:
            next(fh)
            next(fh)
            for linea in fh:
                if len(coordenadas) == NLON * NLAT:
                    break
                lon, lat = linea.split(";")[:2]
                coordenadas.append(f"{lon};{lat}")
    else:
        coordenadas = [f"{_num(x)};{_num(y)}" for y in lats_desc for x in lons]
    fila_i = np.repeat(np.arange(NLAT)[::-1], NLON)
    fila_j = np.tile(np.arange(NLON), NLAT)
    # Las coordenadas de la plantilla deben coincidir con la malla esperada.
    xy = np.array([[float(c.split(";")[0]), float(c.split(";")[1])] for c in coordenadas])
    lats = lats_desc[::-1]
    if not (np.allclose(xy[:, 0], lons[fila_j]) and np.allclose(xy[:, 1], lats[fila_i])):
        raise ValueError("La plantilla de dirmarea.txt no tiene la malla de 94 × 51 nodos esperada.")
    return Plantilla(coordenadas, lons, lats, fila_i, fila_j)


def escribir(ruta: Path, fecha_base: date, horas: list[int], altura: np.ndarray, direccion: np.ndarray,
             base: Plantilla | None = None) -> Path:
    """altura, direccion: [bloque, NLAT (ascendente), NLON]; NaN → relleno."""
    base = base or plantilla()
    fecha = datetime(fecha_base.year, fecha_base.month, fecha_base.day)
    lineas = [";".join(COLUMNAS_OLEAJE)]
    for b, h in enumerate(horas):
        lineas.append(formatear_fecha(fecha, h))
        a = altura[b][base.fila_i, base.fila_j]
        d = direccion[b][base.fila_i, base.fila_j]
        for c, av, dv in zip(base.coordenadas, a, d):
            if np.isfinite(av) and np.isfinite(dv):
                lineas.append(f"{c};{_num(dv % 360.0)};{_num(max(av, 0.0))}")
            else:
                lineas.append(f"{c};{RELLENO_TEXTO};{RELLENO_TEXTO}")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lineas) + "\n")
    return ruta


def mascara_semar(base: Plantilla, ruta_semar: Path = DIR_SEMAR / "dirmarea.txt") -> np.ndarray:
    """bool [NLAT, NLON]: nodos con dato en el primer bloque del archivo de SEMAR."""
    mar = np.zeros((NLAT, NLON), dtype=bool)
    with open(ruta_semar, encoding="utf-8") as fh:
        next(fh)
        next(fh)
        for k, linea in enumerate(fh):
            if k == NLON * NLAT:
                break
            mar[base.fila_i[k], base.fila_j[k]] = not linea.rstrip().endswith(RELLENO_TEXTO)
    return mar


def recuadro_modelo(base: Plantilla) -> np.ndarray:
    """bool [NLAT, NLON]: nodo dentro del recuadro donde corre el modelo."""
    eps = 1e-6
    dentro_lon = (base.lons >= LON_MIN - eps) & (base.lons <= LON_MAX + eps)
    dentro_lat = (base.lats >= LAT_MIN - eps) & (base.lats <= LAT_MAX + eps)
    return dentro_lat[:, None] & dentro_lon[None, :]


def a_malla_fina(valores_nodos: np.ndarray, ii: np.ndarray, jj: np.ndarray, paso: int, destino: np.ndarray,
                 radio_vecino: float = 1.5) -> tuple[np.ndarray, ...]:
    """Interpola campos medidos en nodos de la submalla (índices ii, jj de la malla fina,
    múltiplos de `paso`) a todos los nodos `destino` (bool [NLAT, NLON]).

    valores_nodos: [campo, nodo]. Bilineal ignorando nodos sin dato (como el modelo); si
    ningún vecino tiene dato, el nodo de submalla más cercano a ≤ 1.5 celdas de submalla.
    """
    nci, ncj = (NLAT + paso - 1) // paso, (NLON + paso - 1) // paso
    gruesos = []
    for v in valores_nodos:
        g = np.full((nci, ncj), np.nan)
        g[ii // paso, jj // paso] = v
        gruesos.append(g)
    di, dj = np.nonzero(destino)
    fi, fj = di / paso, dj / paso
    interp, pesos = _bilineal(tuple(gruesos), fi, fj)
    faltan = ~np.isfinite(interp[0])
    if faltan.any():
        validos = np.isfinite(gruesos[0])
        vi, vj = np.nonzero(validos)
        if vi.size:
            for k in np.flatnonzero(faltan):
                d2 = (vi - fi[k]) ** 2 + (vj - fj[k]) ** 2
                m = int(np.argmin(d2))
                if d2[m] <= radio_vecino ** 2:
                    for s, g in zip(interp, gruesos):
                        s[k] = g[vi[m], vj[m]]
    salida = []
    for s in interp:
        f = np.full((NLAT, NLON), np.nan)
        f[di, dj] = s
        salida.append(f)
    return tuple(salida)


def nodos_descarga(base: Plantilla, paso: int, mar: np.ndarray | None = None):
    """Nodos de mar de SEMAR en una submalla (un nodo de cada `paso`), en el recuadro del modelo
    más una celda de margen. Solo para el viento de Open-Meteo, que cobra cada punto."""
    from scipy import ndimage

    from validacion.openmeteo import submalla
    mar = mascara_semar(base) if mar is None else mar
    zona = ndimage.binary_dilation(recuadro_modelo(base), iterations=paso)
    return submalla(base.lons, base.lats, mar & zona, paso)


def horas_bloques() -> list[int]:
    return list(range(0, HORIZONTE_H + 1, PASO_OLEAJE_H))


def oleaje_desde_rejilla(rej, destino: np.ndarray, fecha_base: date, base: Plantilla,
                         horas: list[int] | None = None):
    """Altura y dirección «desde» de la ola de viento de una rejilla de Copernicus Marine en los
    nodos `destino` de la malla de dirmarea.txt, para cada bloque (+0…+120 h desde fecha_base).

    Bilineal desde la resolución nativa (0.083° o 0.2°) ignorando nodos sin dato; la dirección
    por seno y coseno, como el modelo."""
    from validacion.copernicus import a_puntos
    horas = horas or horas_bloques()
    base_dt = datetime(fecha_base.year, fecha_base.month, fecha_base.day, tzinfo=timezone.utc)
    di, dj = np.nonzero(destino)
    x, y = base.lons[dj], base.lats[di]
    altura = np.full((len(horas), NLAT, NLON), np.nan)
    direccion = np.full((len(horas), NLAT, NLON), np.nan)
    for b, h in enumerate(horas):
        k = rej.indice(base_dt + timedelta(hours=h))
        hs = rej.valores["VHM0_WW"][k]
        rad = np.radians(rej.valores["VMDR_WW"][k])
        ok = np.isfinite(hs) & np.isfinite(rad)
        a, sn, cs = a_puntos([np.where(ok, hs, np.nan), np.where(ok, np.sin(rad), np.nan),
                              np.where(ok, np.cos(rad), np.nan)], rej.lons, rej.lats, x, y)
        altura[b, di, dj] = a
        direccion[b, di, dj] = np.mod(np.degrees(np.arctan2(sn, cs)), 360.0)
    return altura, direccion


def generar(fecha_base: date, destino: Path, cache: Path | None = None, registrar=print,
            rejilla=None) -> tuple[Path, dict]:
    """Descarga (o lee de la caché) la ola de viento de Copernicus Marine y escribe
    destino/dirmarea.txt con la fecha base `fecha_base` 00 UTC y bloques +0…+120 h."""
    from validacion import config as cfg
    from validacion import copernicus
    base = plantilla()
    mar = mascara_semar(base)
    if rejilla is None:
        desde = datetime(fecha_base.year, fecha_base.month, fecha_base.day, tzinfo=timezone.utc)
        hasta = desde + timedelta(hours=HORIZONTE_H)
        ds = copernicus.elegir_oleaje(desde, hasta, cache or cfg.DIR_CACHE)
        rejilla = copernicus.descargar(ds, copernicus.VARS_OLEAJE, desde, hasta, cache or cfg.DIR_CACHE, registrar)
    destino_nodos = mar & recuadro_modelo(base)
    altura, direccion = oleaje_desde_rejilla(rejilla, destino_nodos, fecha_base, base)
    ruta = escribir(Path(destino) / "dirmarea.txt", fecha_base, horas_bloques(), altura, direccion, base)
    resumen = {
        "fecha_base_utc": f"{fecha_base.isoformat()}T00:00Z",
        "fuente": f"Copernicus Marine, dataset {rejilla.dataset} (ola de viento VHM0_WW, VMDR_WW)",
        "resolucion_nativa_grados": round(rejilla.resolucion, 4),
        "nodos_con_dato": int(np.isfinite(altura[0]).sum()), "nodos_mar_semar_en_recuadro": int(destino_nodos.sum()),
        "descargado_utc": rejilla.descargado,
    }
    return ruta, resumen
