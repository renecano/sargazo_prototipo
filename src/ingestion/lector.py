"""Lectura tolerante de los archivos de SEMAR.

Ambos archivos (salidadatos.txt y dirmarea.txt) comparten la misma estructura:

    LON;LAT;col3;col4;...          ← línea 1: nombres de columna, separador ";"
    19AUG2026 00                   ← línea de fecha DDMMMAAAA HH [hora de pronóstico] [h]
    -124;39.;323.96;...            ← filas del bloque
    01OCT2026 00 3                 ← (opcional) otra línea de fecha abre otro bloque
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
# Interpolación bilineal que ignora NaN
# ---------------------------------------------------------------------------
def interpolar_bilineal(lons_o, lats_o, campos: list[np.ndarray], lons_d, lats_d) -> list[np.ndarray]:
    """Interpola campos [ny_o, nx_o] de una malla regular a otra.

    Los pesos de los nodos sin dato (NaN) se descartan y se renormalizan los demás; si
    ningún vecino tiene dato, el resultado es NaN. Todos los campos deben compartir la
    máscara de NaN (p. ej. seno y coseno de una dirección).
    """
    lons_o, lats_o = np.asarray(lons_o, float), np.asarray(lats_o, float)
    X, Y = np.meshgrid(np.asarray(lons_d, float), np.asarray(lats_d, float))
    fj = (X - lons_o[0]) / (lons_o[1] - lons_o[0])
    fi = (Y - lats_o[0]) / (lats_o[1] - lats_o[0])
    fuera = (fj < -1e-9) | (fj > lons_o.size - 1 + 1e-9) | (fi < -1e-9) | (fi > lats_o.size - 1 + 1e-9)
    j0 = np.clip(np.floor(fj).astype(int), 0, lons_o.size - 2)
    i0 = np.clip(np.floor(fi).astype(int), 0, lats_o.size - 2)
    wj = np.clip(fj - j0, 0, 1)
    wi = np.clip(fi - i0, 0, 1)
    esquinas = [(i0, j0, (1 - wi) * (1 - wj)), (i0, j0 + 1, (1 - wi) * wj),
                (i0 + 1, j0, wi * (1 - wj)), (i0 + 1, j0 + 1, wi * wj)]
    salida = []
    for campo in campos:
        suma = np.zeros(X.shape)
        pesos = np.zeros(X.shape)
        for i, j, w in esquinas:
            v = campo[i, j]
            valido = np.isfinite(v) & (w > 0)
            suma += np.where(valido, w * np.nan_to_num(v), 0.0)
            pesos += np.where(valido, w, 0.0)
        resultado = np.where(pesos > 1e-12, suma / np.maximum(pesos, 1e-12), np.nan)
        resultado[fuera] = np.nan
        salida.append(resultado)
    return salida


def interpolar_direccion(lons_o, lats_o, direccion: np.ndarray, lons_d, lats_d) -> np.ndarray:
    """Interpola una dirección en grados por sus componentes seno y coseno (no promedia grados:
    350° y 10° dan 0°, no 180°)."""
    rad = np.radians(direccion)
    s, c = interpolar_bilineal(lons_o, lats_o, [np.sin(rad), np.cos(rad)], lons_d, lats_d)
    return np.mod(np.degrees(np.arctan2(s, c)), 360.0)


# ---------------------------------------------------------------------------
# Conjunto validado, listo para el modelo
# ---------------------------------------------------------------------------
@dataclass
class ConjuntoDatos:
    """Campos de SEMAR validados y recortados a la malla del modelo [tiempo, lat, lon]."""
    lons: np.ndarray
    lats: np.ndarray
    tiempos_viento: list[datetime]
    viento_u: np.ndarray            # m/s hacia el este, NaN en tierra
    viento_v: np.ndarray            # m/s hacia el norte
    viento_vel: np.ndarray          # WindsfcSp
    viento_dir: np.ndarray          # WindsfcDir, grados "desde"
    mar: np.ndarray                 # bool [lat, lon]: nodo con dato de viento
    ola_horas: np.ndarray           # horas de pronóstico del oleaje (vacío si no hay archivo)
    ola_dir: np.ndarray | None      # [horas, lat, lon] grados "desde", interpolado a la malla del modelo
    ola_altura: np.ndarray | None   # [horas, lat, lon] m
    ola_fecha_base: datetime | None
    corriente_u: np.ndarray | None  # [lat, lon] m/s, o None si no hay corrientes
    corriente_v: np.ndarray | None
    archivos: dict[str, str]        # nombre → SHA-256
    advertencias: list[str] = field(default_factory=list)

    @property
    def inicio(self) -> datetime:
        return self.tiempos_viento[0]

    @property
    def horas_viento(self) -> np.ndarray:
        return np.array([(t - self.inicio).total_seconds() / 3600 for t in self.tiempos_viento])

    @property
    def viento_estacionario(self) -> bool:
        return len(self.tiempos_viento) == 1

    def resumen(self) -> dict:
        return {
            "fuente": "SEMAR",
            "archivos": [{"nombre": n, "huella_sha256": h} for n, h in self.archivos.items()],
            "inicio_utc": self.inicio.strftime("%Y-%m-%dT%H:%MZ"),
            "viento_horas": len(self.tiempos_viento),
            "viento_estacionario": self.viento_estacionario,
            "oleaje_horas": int(self.ola_horas.size),
            "oleaje_fecha_base_utc": self.ola_fecha_base.strftime("%Y-%m-%dT%H:%MZ") if self.ola_fecha_base else None,
            "corrientes": self.corriente_u is not None,
            "puntos_malla": int(self.lons.size * self.lats.size),
            "puntos_mar": int(self.mar.sum()),
            "advertencias": list(self.advertencias),
        }
