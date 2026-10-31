"""Oleaje y corriente reales desde Copernicus Marine (origen de MFWAM y SMOC), a resolución nativa.

Se usa el toolbox oficial `copernicusmarine` (Python API, `open_dataset` sobre los servicios
ARCO). Las credenciales NO viven en el repositorio: la primera vez se ejecuta
`copernicusmarine login` en la terminal y el toolbox guarda el archivo en la carpeta del
usuario (~/.copernicusmarine).

Datasets (verificados con `copernicusmarine describe` el 31/10/2026; la cobertura se vuelve a
consultar en cada corrida y se guarda en la caché):
- Ola de viento, análisis y pronóstico: GLOBAL_ANALYSISFORECAST_WAV_001_027,
  `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i` (0.083°, 3 h, desde nov 2022).
- Ola de viento, reanálisis (fechas anteriores): GLOBAL_MULTIYEAR_WAV_001_032,
  `cmems_mod_glo_wav_my_0.2deg_PT3H-i` (0.2°, 3 h).
  Variables: VHM0_WW (altura), VMDR_WW (dirección DESDE), VTM01_WW (período medio) y
  VSDX/VSDY (deriva de Stokes del espectro completo: sirve para verificar la fórmula del modelo).
- Corriente SMOC: GLOBAL_ANALYSISFORECAST_PHY_001_024, `cmems_mod_glo_phy_anfc_merged-uv_PT1H-i`
  (0.083°, 1 h, desde nov 2020): uo/vo (euleriana), utide/vtide (marea), vsdx/vsdy (Stokes) y
  utotal/vtotal = suma de las tres.
"""
from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from validacion import config as cfg

OLEAJE_ANFC = "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i"
OLEAJE_MY = "cmems_mod_glo_wav_my_0.2deg_PT3H-i"
CORRIENTE_SMOC = "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i"
PRODUCTOS = {
    OLEAJE_ANFC: "GLOBAL_ANALYSISFORECAST_WAV_001_027",
    OLEAJE_MY: "GLOBAL_MULTIYEAR_WAV_001_032",
    CORRIENTE_SMOC: "GLOBAL_ANALYSISFORECAST_PHY_001_024",
}
VARS_OLEAJE = ("VHM0_WW", "VMDR_WW", "VTM01_WW", "VSDX", "VSDY")
VARS_CORRIENTE = ("uo", "vo", "utide", "vtide", "utotal", "vtotal")
MARGEN_GRADOS = 0.35        # margen alrededor del recuadro para interpolar en los bordes


class SinCobertura(RuntimeError):
    """Ningún dataset de Copernicus Marine cubre las fechas pedidas."""


class SinCredenciales(RuntimeError):
    """El toolbox no encontró credenciales: hay que correr `copernicusmarine login`."""


@dataclass
class Rejilla:
    """Campos [tiempo, lat, lon] (lat ascendente, float32; NaN = tierra) de un dataset."""
    dataset: str
    lons: np.ndarray
    lats: np.ndarray
    tiempos: list[datetime]
    valores: dict[str, np.ndarray]
    descargado: str

    def indice(self, t: datetime) -> int:
        return self.tiempos.index(t)

    @property
    def resolucion(self) -> float:
        return float(np.mean(np.diff(self.lons)))


# ---------------------------------------------------------------------------
# Catálogo y cobertura
# ---------------------------------------------------------------------------
def _ruta_catalogo(cache: Path) -> Path:
    return cache / "copernicus" / "catalogo.json"


def cobertura(dataset_id: str, cache: Path = cfg.DIR_CACHE) -> tuple[datetime, datetime]:
    """(inicio, fin) del eje de tiempo del dataset según el catálogo (se consulta una vez por día)."""
    ruta = _ruta_catalogo(cache)
    catalogo = json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}
    hoy = date.today().isoformat()
    if catalogo.get(dataset_id, {}).get("consultado") != hoy:
        import copernicusmarine as cm
        d = cm.describe(dataset_id=dataset_id, disable_progress_bar=True).model_dump()
        inicio = fin = None
        for p in d["products"]:
            for ds in p["datasets"]:
                if ds["dataset_id"] != dataset_id:
                    continue
                for s in ds["versions"][-1]["parts"][0]["services"]:
                    for v in s["variables"]:
                        for c in v["coordinates"]:
                            if c["coordinate_id"] == "time" and c.get("minimum_value") is not None:
                                inicio, fin = c["minimum_value"], c["maximum_value"]
                                break
        if inicio is None:
            raise RuntimeError(f"El catálogo de Copernicus Marine no da el eje de tiempo de {dataset_id}.")
        catalogo[dataset_id] = {"inicio_ms": inicio, "fin_ms": fin, "consultado": hoy,
                                "producto": PRODUCTOS.get(dataset_id)}
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(catalogo, indent=1), encoding="utf-8")
    c = catalogo[dataset_id]
    a = datetime.fromtimestamp(c["inicio_ms"] / 1000, timezone.utc)
    b = datetime.fromtimestamp(c["fin_ms"] / 1000, timezone.utc)
    return a, b


def _cubre(dataset_id: str, desde: datetime, hasta: datetime, cache: Path) -> bool:
    a, b = cobertura(dataset_id, cache)
    return a <= desde and hasta <= b


def elegir_oleaje(desde: datetime, hasta: datetime, cache: Path = cfg.DIR_CACHE) -> str:
    """Análisis/pronóstico (0.083°) si cubre la ventana; si no, el reanálisis (0.2°)."""
    for ds in (OLEAJE_ANFC, OLEAJE_MY):
        if _cubre(ds, desde, hasta, cache):
            return ds
    raise SinCobertura(f"Ningún dataset de oleaje de Copernicus Marine cubre {desde:%Y-%m-%d %H:%M}…{hasta:%Y-%m-%d %H:%M}.")


def elegir_corriente(desde: datetime, hasta: datetime, cache: Path = cfg.DIR_CACHE) -> str:
    if _cubre(CORRIENTE_SMOC, desde, hasta, cache):
        return CORRIENTE_SMOC
    raise SinCobertura(f"SMOC no cubre {desde:%Y-%m-%d %H:%M}…{hasta:%Y-%m-%d %H:%M}.")


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
def ruta_cache(dataset_id: str, desde: datetime, hasta: datetime, cache: Path = cfg.DIR_CACHE) -> Path:
    return cache / "copernicus" / f"{dataset_id}_{desde:%Y%m%d%H}_{hasta:%Y%m%d%H}.npz"


def descargar(dataset_id: str, variables, desde: datetime, hasta: datetime, cache: Path = cfg.DIR_CACHE,
              registrar=print, recuadro=cfg.RECUADRO) -> Rejilla:
    """Recorte del recuadro del modelo (más margen) a resolución nativa, una variable a la vez
    para no pasar de ~200 MB de memoria; se guarda en la caché como float32 comprimido."""
    ruta = ruta_cache(dataset_id, desde, hasta, cache)
    if ruta.is_file():
        return leer(ruta)
    import copernicusmarine as cm
    lon_min, lon_max, lat_min, lat_max = recuadro
    t0 = time.perf_counter()
    valores, lons, lats, tiempos = {}, None, None, None
    for v in variables:
        for intento in range(4):
            try:
                ds = cm.open_dataset(
                    dataset_id=dataset_id, variables=[v],
                    minimum_longitude=lon_min - MARGEN_GRADOS, maximum_longitude=lon_max + MARGEN_GRADOS,
                    minimum_latitude=lat_min - MARGEN_GRADOS, maximum_latitude=lat_max + MARGEN_GRADOS,
                    start_datetime=desde.strftime("%Y-%m-%dT%H:%M:%S"), end_datetime=hasta.strftime("%Y-%m-%dT%H:%M:%S"),
                    minimum_depth=0, maximum_depth=1)
                break
            except Exception as e:  # noqa: BLE001 — credenciales o red; se reintenta y se explica
                texto = str(e)
                if "credentials" in texto.lower() or "login" in texto.lower():
                    raise SinCredenciales("Copernicus Marine pidió credenciales: corre `copernicusmarine login` "
                                          "en la terminal (se guardan fuera del repositorio).") from e
                if intento == 3:
                    raise
                registrar(f"    Copernicus Marine sin respuesta ({texto[:80]}); reintento")
                time.sleep(30 * (intento + 1))
        arr = ds[v]
        if "depth" in arr.dims:
            arr = arr.isel(depth=0)
        datos = np.asarray(arr.transpose("time", "latitude", "longitude").values, dtype=np.float32)
        la = np.asarray(ds["latitude"].values, dtype=float)
        if la[0] > la[-1]:
            la, datos = la[::-1], datos[:, ::-1]
        if lons is None:
            lons, lats = np.asarray(ds["longitude"].values, dtype=float), la
            tiempos = [datetime.fromisoformat(str(t)[:19]).replace(tzinfo=timezone.utc) for t in ds["time"].values]
        valores[v] = datos
        ds.close()
        del ds, arr
        gc.collect()
    rej = Rejilla(dataset_id, lons, lats, tiempos, valores, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atómica: otro proceso nunca ve un archivo a medias en la caché.
    temporal = ruta.with_name(ruta.stem + f".{os.getpid()}.tmp.npz")
    np.savez_compressed(temporal, dataset=dataset_id, lons=lons, lats=lats,
                        tiempos=np.array([t.strftime("%Y-%m-%dT%H:%M") for t in tiempos]),
                        variables=np.array(list(valores)), valores=np.stack([valores[v] for v in valores]),
                        descargado=rej.descargado)
    os.replace(temporal, ruta)
    registrar(f"  Copernicus Marine {dataset_id} {desde:%Y-%m-%d}…{hasta:%Y-%m-%d}: "
              f"{len(tiempos)} tiempos × {lats.size} × {lons.size} en {time.perf_counter() - t0:.0f} s")
    return rej


def leer(ruta: Path) -> Rejilla:
    with np.load(ruta) as z:
        variables = [str(v) for v in z["variables"]]
        return Rejilla(str(z["dataset"]), z["lons"], z["lats"],
                       [datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc) for t in z["tiempos"]],
                       {v: z["valores"][k] for k, v in enumerate(variables)}, str(z["descargado"]))


# ---------------------------------------------------------------------------
# Interpolación a puntos
# ---------------------------------------------------------------------------
def a_puntos(campos: list[np.ndarray], lons: np.ndarray, lats: np.ndarray, x: np.ndarray, y: np.ndarray,
             radio_vecino: float = 1.5) -> list[np.ndarray]:
    """Bilineal (ignorando NaN, como el modelo) de campos [lat, lon] a los puntos (x, y); si
    ningún vecino tiene dato, el nodo con dato más cercano a ≤ 1.5 celdas."""
    from src.model.campos import _bilineal
    fi = (np.asarray(y) - lats[0]) / (lats[1] - lats[0])
    fj = (np.asarray(x) - lons[0]) / (lons[1] - lons[0])
    salida, _ = _bilineal(tuple(np.asarray(c, dtype=np.float64) for c in campos), fi, fj)
    salida = [np.array(s) for s in salida]
    faltan = ~np.isfinite(salida[0])
    if faltan.any():
        vi, vj = np.nonzero(np.isfinite(campos[0]))
        for k in np.flatnonzero(faltan):
            d2 = (vi - fi[k]) ** 2 + (vj - fj[k]) ** 2
            if d2.size:
                m = int(np.argmin(d2))
                if d2[m] <= radio_vecino ** 2:
                    for s, c in zip(salida, campos):
                        s[k] = c[vi[m], vj[m]]
    return salida
