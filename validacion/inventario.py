"""Inventario de todas las imágenes AFAI 2022–2026 del recuadro del modelo.

Dos pasadas sobre todos los días disponibles:

1. Detección con el mar del modelo. Se cuenta, por píxel, cuántas veces se observó y en
   cuántas superó el umbral. Los píxeles que casi nunca se observan (p. ej. la franja al
   sur de 21° N y al oeste de 90.5° O, que AOML no cubre) y los "brillantes persistentes"
   (≥ 20 % de sus observaciones sobre el umbral: fondo somero, turbidez fija, arrecifes)
   se excluyen: el sargazo se mueve, un fondo brillante no.
2. Detección final con ese mar útil. Por día se guardan los conteos (CSV) y las máscaras
   empaquetadas en bits (caché) para seleccionar casos y calcular métricas sin repetir.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from validacion import afai
from validacion import config as cfg

MIN_OBSERVACIONES = 30          # un píxel con menos observaciones en 5 años no se evalúa


def meses(desde: date = cfg.BUSQUEDA_DESDE, hasta: date = cfg.BUSQUEDA_HASTA):
    a, m = desde.year, desde.month
    while (a, m) <= (hasta.year, hasta.month):
        yield a, m
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


def _ruta_mascaras(cache: Path) -> Path:
    return cache / "inventario" / "mascaras.npz"


def _ruta_mes(cache: Path, anio: int, mes: int) -> Path:
    return cache / "inventario" / f"deteccion_{anio:04d}-{mes:02d}.npz"


def ruta_csv(cache: Path = cfg.DIR_CACHE) -> Path:
    return cache / "inventario" / "dias.csv"


@dataclass
class Mascaras:
    lons: np.ndarray
    lats: np.ndarray
    mar_modelo: np.ndarray       # bool: mar según la costa del modelo
    observaciones: np.ndarray    # int: días con observación válida (pasada 1)
    sobre_umbral: np.ndarray     # int: días con ΔAFAI > T0 (pasada 1)
    persistente: np.ndarray      # bool: brillante persistente (se excluye)
    mar_util: np.ndarray         # bool: mar del modelo, observado ≥ 30 veces y no persistente

    @property
    def forma(self):
        return self.mar_util.shape


def calcular_mascaras(archivo: afai.ArchivoAfai, cache: Path = cfg.DIR_CACHE, registrar=print) -> Mascaras:
    ruta = _ruta_mascaras(cache)
    if ruta.is_file():
        with np.load(ruta) as z:
            return Mascaras(**{k: z[k] for k in z.files})
    lons, lats = archivo.rejilla()
    mar = afai.mar_del_modelo(lons, lats)
    obs = np.zeros(mar.shape, dtype=np.int32)
    sobre = np.zeros(mar.shape, dtype=np.int32)
    for anio, mes, o, s in _en_paralelo(_pasada1_mes, [(a, m, mar, cache) for a, m in meses()]):
        obs += o
        sobre += s
        registrar(f"  pasada 1 {anio}-{mes:02d}")
    with np.errstate(invalid="ignore", divide="ignore"):
        frecuencia = np.where(obs > 0, sobre / np.maximum(obs, 1), 0.0)
    persistente = mar & (obs >= MIN_OBSERVACIONES) & (frecuencia >= cfg.FRECUENCIA_PERSISTENTE)
    mar_util = mar & (obs >= MIN_OBSERVACIONES) & ~persistente
    m = Mascaras(lons, lats, mar, obs, sobre, persistente, mar_util)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ruta, **m.__dict__)
    return m


PROCESOS = 4          # meses en paralelo (≈ 300 MB de memoria cada uno)


def _en_paralelo(funcion, tareas):
    """Aplica `funcion` a cada tarea en procesos aparte; entrega los resultados en orden."""
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=PROCESOS) as ex:
        yield from ex.map(funcion, tareas)


def _pasada1_mes(tarea):
    anio, mes, mar, cache = tarea
    rej = afai.mes_afai(anio, mes, cache, registrar=lambda *_: None)
    obs = np.zeros(mar.shape, dtype=np.int32)
    sobre = np.zeros(mar.shape, dtype=np.int32)
    for k in range(len(rej.fechas)):
        d = afai.detectar(rej.afai[k], mar)
        obs += d.valido
        sobre += d.sargazo
    return anio, mes, obs, sobre


def _pasada2_mes(tarea):
    anio, mes, mar_util, cache = tarea
    ruta = _ruta_mes(cache, anio, mes)
    if not ruta.is_file():
        rej = afai.mes_afai(anio, mes, cache, registrar=lambda *_: None)
        valido, sargazo = [], []
        for k in range(len(rej.fechas)):
            d = afai.detectar(rej.afai[k], mar_util)
            valido.append(d.valido)
            sargazo.append(d.sargazo)
        forma = mar_util.shape
        v = np.array(valido) if valido else np.zeros((0, *forma), bool)
        sg = np.array(sargazo) if sargazo else np.zeros((0, *forma), bool)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(ruta, fechas=np.array([f.isoformat() for f in rej.fechas]),
                            valido=_empacar(v), sargazo=_empacar(sg))
    return anio, mes


def _empacar(b: np.ndarray) -> np.ndarray:
    return np.packbits(b.reshape(b.shape[0], -1), axis=1)


def _desempacar(p: np.ndarray, forma) -> np.ndarray:
    n = forma[0] * forma[1]
    return np.unpackbits(p, axis=1, count=n).reshape(p.shape[0], *forma).astype(bool)


class Detecciones:
    """Detección final por día (pasada 2), con caché mensual en bits."""

    def __init__(self, archivo: afai.ArchivoAfai, mascaras: Mascaras, cache: Path = cfg.DIR_CACHE,
                 registrar=print):
        self.archivo, self.m, self.cache, self.registrar = archivo, mascaras, cache, registrar
        self._meses: dict[tuple[int, int], dict] = {}

    def mes(self, anio: int, mes: int) -> dict:
        clave = (anio, mes)
        if clave in self._meses:
            return self._meses[clave]
        ruta = _ruta_mes(self.cache, anio, mes)
        if not ruta.is_file():
            fechas = self.archivo.fechas_mes(anio, mes)
            valido, sargazo = [], []
            for f in fechas:
                d = afai.detectar(self.archivo.dia(f), self.m.mar_util)
                valido.append(d.valido)
                sargazo.append(d.sargazo)
            forma = self.m.forma
            v = np.array(valido) if valido else np.zeros((0, *forma), bool)
            s = np.array(sargazo) if sargazo else np.zeros((0, *forma), bool)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(ruta, fechas=np.array([f.isoformat() for f in fechas]),
                                valido=_empacar(v), sargazo=_empacar(s))
            self.registrar(f"  pasada 2 {anio}-{mes:02d}: {len(fechas)} días")
        with np.load(ruta) as z:
            fechas = [date.fromisoformat(s) for s in z["fechas"]]
            datos = {"fechas": fechas,
                     "valido": _desempacar(z["valido"], self.m.forma),
                     "sargazo": _desempacar(z["sargazo"], self.m.forma)}
        if len(self._meses) >= 4:
            self._meses.pop(next(iter(self._meses)))
        self._meses[clave] = datos
        return datos

    def dia(self, fecha: date) -> tuple[np.ndarray, np.ndarray] | None:
        """(válido, sargazo) del día, o None si no hay imagen."""
        d = self.mes(fecha.year, fecha.month)
        if fecha not in d["fechas"]:
            return None
        i = d["fechas"].index(fecha)
        return d["valido"][i], d["sargazo"][i]


CAMPOS_CSV = ("fecha", "mar_util", "validos", "claro", "sargazo")


def construir(cache: Path = cfg.DIR_CACHE, registrar=print) -> tuple[Mascaras, Detecciones, list[dict]]:
    """Descarga (si falta), detecta y escribe el CSV con un renglón por imagen disponible."""
    archivo = afai.ArchivoAfai(cache, registrar)
    registrar("Inventario AFAI: máscaras (pasada 1)")
    m = calcular_mascaras(archivo, cache, registrar)
    det = Detecciones(archivo, m, cache, registrar)
    ruta = ruta_csv(cache)
    if not ruta.is_file():
        registrar("Inventario AFAI: detección final (pasada 2)")
        tareas = [(anio, mes, m.mar_util, cache) for anio, mes in meses()]
        for anio, mes in _en_paralelo(_pasada2_mes, tareas):
            registrar(f"  pasada 2 {anio}-{mes:02d}")
        filas = []
        n_util = int(m.mar_util.sum())
        for anio, mes in meses():
            d = det.mes(anio, mes)
            for f, v, s in zip(d["fechas"], d["valido"], d["sargazo"]):
                filas.append({"fecha": f.isoformat(), "mar_util": n_util, "validos": int(v.sum()),
                              "claro": round(float(v.sum()) / n_util, 4), "sargazo": int(s.sum())})
        with ruta.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CAMPOS_CSV)
            w.writeheader()
            w.writerows(filas)
    with ruta.open(encoding="utf-8") as fh:
        filas = [{"fecha": date.fromisoformat(r["fecha"]), "mar_util": int(r["mar_util"]),
                  "validos": int(r["validos"]), "claro": float(r["claro"]), "sargazo": int(r["sargazo"])}
                 for r in csv.DictReader(fh)]
    return m, det, filas


if __name__ == "__main__":
    import time
    t = time.perf_counter()
    _, _, filas = construir()
    print(f"{len(filas)} imágenes en {time.perf_counter() - t:.0f} s")
