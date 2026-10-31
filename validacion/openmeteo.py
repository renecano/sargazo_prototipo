"""Forzamientos reales desde Open-Meteo (sin llave, uso no comercial, CC BY 4.0).

- Oleaje de viento: MeteoFrance MFWAM (`models=meteofrance_wave`, 0.08°, desde oct 2021):
  wind_wave_height, wind_wave_direction (DESDE donde viene, como dirolavto) y
  wind_wave_period.
- Corriente superficial: MeteoFrance SMOC (`models=meteofrance_currents`, 0.08°, desde
  ene 2022): ocean_current_velocity y ocean_current_direction (HACIA donde va). Según la
  documentación de Open-Meteo es la corriente "Eulerian, Waves and Tides": ya incluye la
  deriva de Stokes del oleaje y la marea.
- Viento a 10 m: ERA5 (`archive-api`, `models=era5`, 0.25°): wind_speed_10m y
  wind_direction_10m (DESDE donde sopla).

Open-Meteo cuenta cada punto de una petición como una llamada (verificado: dos peticiones
de 700 y 1 295 puntos en el mismo minuto dan HTTP 429) y el uso gratuito permite 600 por
minuto, 5 000 por hora y 10 000 por día. Por eso los forzamientos se piden en una
submalla de la malla de 0.16° de dirmarea.txt (un nodo de cada `paso`) y luego se
interpolan; cada descarga se guarda en la caché y no se vuelve a pedir.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from validacion import config as cfg

MARINA = "https://marine-api.open-meteo.com/v1/marine"
HISTORICO = "https://archive-api.open-meteo.com/v1/archive"
MAX_PUNTOS_PETICION = 500
MAX_PUNTOS_MINUTO = 550


@dataclass(frozen=True)
class Grupo:
    nombre: str
    url: str
    modelo: str
    variables: tuple[str, ...]
    paso: int                 # submalla: un nodo de cada `paso` de la malla de 0.16°
    extra: tuple = ()


OLEAJE = Grupo("oleaje", MARINA, "meteofrance_wave",
               ("wind_wave_height", "wind_wave_direction", "wind_wave_period"), 2)
CORRIENTE = Grupo("corriente", MARINA, "meteofrance_currents",
                  ("ocean_current_velocity", "ocean_current_direction"), 2)
VIENTO = Grupo("viento", HISTORICO, "era5", ("wind_speed_10m", "wind_direction_10m"), 3,
               (("wind_speed_unit", "ms"),))
GRUPOS = {g.nombre: g for g in (OLEAJE, CORRIENTE, VIENTO)}

# Conversión a unidades SI según las unidades que declara la respuesta.
A_SI = {"m": 1.0, "s": 1.0, "°": 1.0, "m/s": 1.0, "km/h": 1 / 3.6, "kn": 0.514444}


class CuotaAgotada(RuntimeError):
    """Open-Meteo rechazó la petición por el límite diario u horario del uso gratuito."""


@dataclass
class Serie:
    """Series horarias en los nodos pedidos: valores [variable][hora, nodo] (NaN = sin dato)."""
    grupo: str
    modelo: str
    lons: np.ndarray          # nodos pedidos (malla de dirmarea.txt)
    lats: np.ndarray
    tiempos: list[datetime]   # UTC
    valores: dict[str, np.ndarray]
    unidades: dict[str, str]
    celdas: np.ndarray        # [nodo, 2] lon/lat de la celda del modelo que usó Open-Meteo
    descargado: str

    def indice_hora(self, t: datetime) -> int:
        return self.tiempos.index(t)


class Limitador:
    """Respeta el límite por minuto contando los puntos pedidos en los últimos 60 s."""

    def __init__(self, maximo=MAX_PUNTOS_MINUTO):
        self.maximo, self.historial = maximo, []

    def esperar(self, puntos: int, registrar=print):
        ahora = time.monotonic()
        self.historial = [(t, n) for t, n in self.historial if ahora - t < 61]
        usados = sum(n for _, n in self.historial)
        if usados + puntos > self.maximo and self.historial:
            pausa = 61 - (ahora - self.historial[0][0])
            registrar(f"    (pausa de {pausa:.0f} s por el límite de Open-Meteo de 600 llamadas por minuto)")
            time.sleep(max(pausa, 0))
            self.historial = []
        self.historial.append((time.monotonic(), puntos))


LIMITADOR = Limitador()


def _peticion(grupo: Grupo, lons, lats, desde: date, hasta: date, registrar=print) -> list[dict]:
    params = {
        "latitude": ",".join(f"{v:.2f}" for v in lats),
        "longitude": ",".join(f"{v:.2f}" for v in lons),
        "hourly": ",".join(grupo.variables),
        "start_date": desde.isoformat(), "end_date": hasta.isoformat(),
        "models": grupo.modelo, "timezone": "GMT", **dict(grupo.extra),
    }
    cuerpo = urllib.parse.urlencode(params).encode()
    for intento in range(6):
        LIMITADOR.esperar(len(lons), registrar)
        try:
            with urllib.request.urlopen(urllib.request.Request(grupo.url, data=cuerpo), timeout=300) as r:
                datos = json.load(r)
            return datos if isinstance(datos, list) else [datos]
        except urllib.error.HTTPError as e:
            motivo = e.read().decode("utf-8", "replace")
            if e.code == 429 and "Minutely" in motivo:
                registrar("    Open-Meteo: límite por minuto; espero 65 s")
                time.sleep(65)
                LIMITADOR.historial = []
                continue
            if e.code == 429 and "Hourly" in motivo and intento < 5:
                registrar("    Open-Meteo: límite por hora (5 000 llamadas); espero 12 min")
                time.sleep(720)
                LIMITADOR.historial = []
                continue
            if e.code == 429:
                raise CuotaAgotada(f"Open-Meteo rechazó la descarga ({grupo.nombre}): {motivo}") from e
            raise RuntimeError(f"Open-Meteo respondió {e.code} ({grupo.nombre}): {motivo}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            registrar(f"    Open-Meteo sin respuesta ({e}); reintento")
            time.sleep(20 * (intento + 1))
    raise RuntimeError(f"Open-Meteo no respondió tras varios intentos ({grupo.nombre}).")


def ruta_cache(grupo: Grupo, desde: date, hasta: date, cache: Path = cfg.DIR_CACHE) -> Path:
    return cache / "openmeteo" / f"{grupo.nombre}_{desde.isoformat()}_{hasta.isoformat()}_p{grupo.paso}.npz"


def descargar_serie(grupo: Grupo, lons: np.ndarray, lats: np.ndarray, desde: date, hasta: date,
                    cache: Path = cfg.DIR_CACHE, registrar=print) -> Serie:
    """Series horarias del grupo en los nodos (lons, lats) entre dos fechas (inclusive)."""
    ruta = ruta_cache(grupo, desde, hasta, cache)
    if ruta.is_file():
        return leer_serie(ruta)
    registrar(f"  Open-Meteo {grupo.nombre} {desde}…{hasta}: {lons.size} puntos")
    respuestas = []
    for k in range(0, lons.size, MAX_PUNTOS_PETICION):
        respuestas += _peticion(grupo, lons[k:k + MAX_PUNTOS_PETICION], lats[k:k + MAX_PUNTOS_PETICION],
                                desde, hasta, registrar)
    tiempos = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in respuestas[0]["hourly"]["time"]]
    valores, unidades = {}, {}
    for v in grupo.variables:
        unidad = respuestas[0]["hourly_units"].get(v, "")
        if unidad not in A_SI:
            raise RuntimeError(f"Unidad inesperada para {v}: {unidad!r}")
        unidades[v] = unidad
        m = np.array([[np.nan if x is None else float(x) for x in r["hourly"][v]] for r in respuestas]).T
        valores[v] = m * (A_SI[unidad] if unidad not in ("°",) else 1.0)
    celdas = np.array([[r["longitude"], r["latitude"]] for r in respuestas], dtype=float)
    serie = Serie(grupo.nombre, grupo.modelo, np.asarray(lons, float), np.asarray(lats, float), tiempos, valores,
                  unidades, celdas, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ruta, grupo=serie.grupo, modelo=serie.modelo, lons=serie.lons, lats=serie.lats,
                        tiempos=np.array([t.strftime("%Y-%m-%dT%H:%M") for t in tiempos]),
                        variables=np.array(list(valores)), valores=np.stack([valores[v] for v in valores]),
                        unidades=np.array([unidades[v] for v in valores]), celdas=celdas,
                        descargado=serie.descargado)
    return serie


def leer_serie(ruta: Path) -> Serie:
    with np.load(ruta) as z:
        variables = [str(v) for v in z["variables"]]
        return Serie(str(z["grupo"]), str(z["modelo"]), z["lons"], z["lats"],
                     [datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc) for t in z["tiempos"]],
                     {v: z["valores"][k] for k, v in enumerate(variables)},
                     {v: str(u) for v, u in zip(variables, z["unidades"])}, z["celdas"], str(z["descargado"]))


def submalla(lons: np.ndarray, lats: np.ndarray, mar: np.ndarray, paso: int):
    """Nodos de mar de la submalla (un nodo de cada `paso`, alineada con el origen de la malla).

    Devuelve índices (i, j) en la malla fina y sus coordenadas."""
    ii, jj = np.meshgrid(np.arange(0, lats.size, paso), np.arange(0, lons.size, paso), indexing="ij")
    ii, jj = ii.ravel(), jj.ravel()
    sel = mar[ii, jj]
    return ii[sel], jj[sel], lons[jj[sel]], lats[ii[sel]]
