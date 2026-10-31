"""Lectura tolerante del archivo de oleaje de SEMAR (dirmarea.txt).

Estructura:

    LON;LAT;dirolavto;alturaolavto ← línea 1: nombres de columna, separador ";"
    01OCT2026 00 0                 ← línea de fecha DDMMMAAAA HH [hora de pronóstico] [h]
    -98;23.;116.25;0.84            ← filas del bloque (de norte a sur, de oeste a este)
    01OCT2026 00 3                 ← otra línea de fecha abre el siguiente bloque
    ...

El valor -9.99e+08 (o cualquiera menor que UMBRAL_RELLENO) significa "sin dato" y se
convierte en NaN. Las filas defectuosas no detienen la lectura: se reportan con su número
de línea para que el validador las muestre.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from src.config import UMBRAL_RELLENO

# Mapa propio de meses en inglés (no depende del "locale" del sistema).
MESES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
         "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
NOMBRES_MES = {v: k for k, v in MESES.items()}
PATRON_FECHA = re.compile(r"^(\d{2})([A-Za-z]{3})(\d{4})\s+(\d{1,2})(?:\s+(\d{1,3}))?\s*(?:h)?$")


def parsear_fecha(texto: str) -> tuple[datetime, int] | None:
    """'19AUG2026 00' → (2026-08-19 00 UTC, 0); '01OCT2026 00 3' → (2026-10-01 00 UTC, 3)."""
    m = PATRON_FECHA.match(texto.strip())
    if not m:
        return None
    dia, mes, anio, hora, pronostico = m.groups()
    mes_n = MESES.get(mes.upper())
    if mes_n is None:
        return None
    try:
        base = datetime(int(anio), mes_n, int(dia), int(hora), tzinfo=timezone.utc)
    except ValueError:
        return None
    return base, int(pronostico or 0)


def formatear_fecha(fecha: datetime, hora_pronostico: int | None = None) -> str:
    """Inverso de parsear_fecha, en el formato de SEMAR."""
    texto = f"{fecha.day:02d}{NOMBRES_MES[fecha.month]}{fecha.year} {fecha.hour:02d}"
    return texto if hora_pronostico is None else f"{texto} {hora_pronostico}"


@dataclass
class Bloque:
    texto_fecha: str
    linea: int                          # número de línea (1-based) de la línea de fecha
    fecha_base: datetime | None         # None si la fecha es ilegible
    hora_pronostico: int
    datos: np.ndarray                   # float64 [filas, columnas], NaN = sin dato
    rellenos: int                       # cuántos valores eran -9.99e+08
    huella: str                         # SHA-256 de las filas, para detectar bloques repetidos

    @property
    def fecha_valida(self) -> datetime | None:
        return None if self.fecha_base is None else self.fecha_base + timedelta(hours=self.hora_pronostico)


@dataclass
class ArchivoSemar:
    ruta: Path
    columnas: list[str]
    bloques: list[Bloque] = field(default_factory=list)
    filas_invalidas: list[tuple[int, str]] = field(default_factory=list)
    problemas: list[tuple[int, str]] = field(default_factory=list)   # (línea, descripción) de formato
    huella_sha256: str = ""

    def indice(self, columna: str) -> int:
        return self.columnas.index(columna)


def _es_linea_de_fecha(linea: str) -> bool:
    return ";" not in linea and any(c.isalpha() for c in linea)


def _convertir(filas: list[str], ncol: int, primera_linea: int, invalidas: list) -> np.ndarray:
    """Convierte las filas de un bloque. Camino rápido con un solo split; si algo no cuadra,
    se convierte fila por fila y se reportan las defectuosas."""
    tokens = ";".join(filas).split(";")
    if len(tokens) == len(filas) * ncol:
        try:
            return np.fromiter(map(float, tokens), dtype=float, count=len(tokens)).reshape(len(filas), ncol)
        except ValueError:
            pass
    buenas = []
    for k, fila in enumerate(filas):
        partes = fila.split(";")
        if len(partes) != ncol:
            invalidas.append((primera_linea + k, f"{len(partes)} valores en lugar de {ncol}"))
            continue
        try:
            buenas.append([float(p) for p in partes])
        except ValueError:
            invalidas.append((primera_linea + k, "valor no numérico"))
    return np.array(buenas, dtype=float).reshape(-1, ncol)


def leer_archivo_semar(ruta: Path) -> ArchivoSemar:
    ruta = Path(ruta)
    crudo = ruta.read_bytes()
    texto = crudo.decode("utf-8", errors="replace")
    lineas = texto.splitlines()
    archivo = ArchivoSemar(ruta, [], huella_sha256=hashlib.sha256(crudo).hexdigest())
    if not lineas or ";" not in lineas[0]:
        archivo.problemas.append((1, "la primera línea no es un encabezado de columnas separado por ';'"))
        return archivo
    archivo.columnas = [c.strip() for c in lineas[0].split(";")]
    ncol = len(archivo.columnas)

    actual: dict | None = None

    def cerrar():
        if actual is None:
            return
        filas = actual["filas"]
        datos = _convertir(filas, ncol, actual["primera"], archivo.filas_invalidas)
        relleno = datos < UMBRAL_RELLENO
        datos[relleno] = np.nan
        archivo.bloques.append(Bloque(
            texto_fecha=actual["texto"], linea=actual["linea"], fecha_base=actual["fecha"],
            hora_pronostico=actual["hora"], datos=datos, rellenos=int(relleno.sum()),
            huella=hashlib.sha256("\n".join(filas).encode()).hexdigest(),
        ))

    for n, linea in enumerate(lineas[1:], start=2):
        limpia = linea.strip()
        if not limpia:
            continue
        if _es_linea_de_fecha(limpia):
            cerrar()
            fecha = parsear_fecha(limpia)
            if fecha is None:
                archivo.problemas.append((n, f"fecha ilegible: «{limpia}» (se espera DDMMMAAAA HH, p. ej. 19AUG2026 00)"))
            actual = {"texto": limpia, "linea": n, "fecha": fecha[0] if fecha else None,
                      "hora": fecha[1] if fecha else 0, "filas": [], "primera": n + 1}
            continue
        if actual is None:
            archivo.problemas.append((n, "hay datos antes de la línea de fecha"))
            actual = {"texto": "", "linea": n, "fecha": None, "hora": 0, "filas": [], "primera": n}
        actual["filas"].append(limpia.rstrip(";"))
    cerrar()
    return archivo


# ---------------------------------------------------------------------------
# Malla regular
# ---------------------------------------------------------------------------
@dataclass
class Malla:
    """Malla regular reconstruida a partir de las columnas LON y LAT de un bloque."""
    lons: np.ndarray        # ascendentes
    lats: np.ndarray        # ascendentes (de sur a norte)
    fila: np.ndarray        # índice de latitud de cada fila del archivo
    col: np.ndarray         # índice de longitud de cada fila del archivo
    rectangular: bool
    pasos: tuple[float, float, float, float]  # (min, max) del paso en lon y en lat

    @property
    def forma(self) -> tuple[int, int]:
        return self.lats.size, self.lons.size

    def a_rejilla(self, valores: np.ndarray) -> np.ndarray:
        rejilla = np.full(self.forma, np.nan)
        rejilla[self.fila, self.col] = valores
        return rejilla


def construir_malla(lon: np.ndarray, lat: np.ndarray) -> Malla:
    lons = np.unique(np.round(lon, 4))
    lats = np.unique(np.round(lat, 4))
    col = np.searchsorted(lons, np.round(lon, 4))
    fila = np.searchsorted(lats, np.round(lat, 4))
    unicos = np.unique(fila * lons.size + col).size
    rectangular = lon.size == lons.size * lats.size and unicos == lon.size
    dlon = np.diff(lons) if lons.size > 1 else np.array([np.nan])
    dlat = np.diff(lats) if lats.size > 1 else np.array([np.nan])
    return Malla(lons, lats, fila, col, rectangular,
                 (float(dlon.min()), float(dlon.max()), float(dlat.min()), float(dlat.max())))


# ---------------------------------------------------------------------------
# Conjunto validado, listo para el modelo
# ---------------------------------------------------------------------------
@dataclass
class ConjuntoDatos:
    """Oleaje de SEMAR validado y recortado al dominio del modelo, en su malla nativa.

    Arreglos [bloque, lat, lon] con lat ascendente; NaN = sin dato (tierra).
    """
    lons: np.ndarray
    lats: np.ndarray
    fecha_base: datetime
    horas: np.ndarray               # horas de pronóstico de cada bloque (+0, +3, …, +120)
    altura: np.ndarray              # alturaolavto, m
    direccion: np.ndarray           # dirolavto, grados DESDE donde viene la ola
    mar: np.ndarray                 # bool [lat, lon]: nodo con dato de ola
    archivo: str
    huella_sha256: str
    bloques_identicos: bool
    advertencias: list[str] = field(default_factory=list)

    @property
    def inicio(self) -> datetime:
        return self.fecha_base + timedelta(hours=float(self.horas[0]))

    def resumen(self) -> dict:
        return {
            "fuente": "SEMAR",
            "archivo": self.archivo,
            "huella_sha256": self.huella_sha256,
            "fecha_base_utc": self.fecha_base.strftime("%Y-%m-%dT%H:%MZ"),
            "inicio_utc": self.inicio.strftime("%Y-%m-%dT%H:%MZ"),
            "bloques": int(self.horas.size),
            "horas": [int(h) for h in self.horas],
            "bloques_identicos": self.bloques_identicos,
            "puntos_malla": int(self.lons.size * self.lats.size),
            "puntos_mar": int(self.mar.sum()),
            "advertencias": list(self.advertencias),
        }
