"""Lectura de los archivos horarios (esquema SEMAR) y del campo de corrientes.

Formato esperado (provisional, mientras SEMAR confirma el oficial):
  - Líneas que empiezan con "#": comentarios/metadatos ("clave: valor").
  - Primera línea no comentada: nombres de columna separados por espacios.
  - Resto: una fila numérica por punto de malla; "NaN" = sin dato.
  - Nombre del archivo: <prefijo>_AAAAMMDDHH.txt con la fecha de validez en UTC.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PATRON_HORARIO = re.compile(r"^(?P<prefijo>.+)_(?P<fecha>\d{10})\.txt$")


@dataclass
class ArchivoTabla:
    ruta: Path
    metadatos: dict
    columnas: list[str]
    datos: np.ndarray            # float64 [filas, columnas]
    filas_invalidas: list[tuple[int, str]] = field(default_factory=list)  # (línea, motivo)
    linea_primer_dato: int = 0   # número de línea (1-based) de la primera fila de datos

    def columna(self, nombre: str) -> np.ndarray:
        return self.datos[:, self.columnas.index(nombre)]

    @property
    def sintetico(self) -> bool:
        return any("SINTETICO" in k.upper() for k in self.metadatos.get("_comentarios", []))


def leer_tabla(ruta: Path) -> ArchivoTabla:
    """Lee un archivo de texto tabular tolerando filas defectuosas (se reportan, no se cargan)."""
    texto = Path(ruta).read_text(encoding="utf-8", errors="replace")
    metadatos: dict = {"_comentarios": []}
    columnas: list[str] | None = None
    filas: list[list[str]] = []
    invalidas: list[tuple[int, str]] = []
    primera = 0
    lineas = texto.splitlines()
    rapido = _lectura_rapida(lineas, metadatos)
    if rapido is not None:
        columnas, datos, primera = rapido
        return ArchivoTabla(Path(ruta), metadatos, columnas, datos, [], primera)
    metadatos = {"_comentarios": []}
    for n, linea in enumerate(lineas, start=1):
        limpia = linea.strip()
        if not limpia:
            continue
        if limpia.startswith("#"):
            contenido = limpia.lstrip("#").strip()
            metadatos["_comentarios"].append(contenido)
            if ":" in contenido:
                clave, valor = contenido.split(":", 1)
                metadatos[clave.strip().lower()] = valor.strip()
            continue
        if columnas is None:
            columnas = limpia.split()
            continue
        partes = limpia.split()
        if len(partes) != len(columnas):
            invalidas.append((n, f"{len(partes)} valores en lugar de {len(columnas)}"))
            continue
        if not primera:
            primera = n
        filas.append(partes)
    if columnas is None:
        return ArchivoTabla(Path(ruta), metadatos, [], np.empty((0, 0)), [(0, "archivo sin encabezado de columnas")])
    try:
        datos = np.array(filas, dtype=float) if filas else np.empty((0, len(columnas)))
    except ValueError:
        datos_ok, filas_ok = [], []
        for k, partes in enumerate(filas):
            try:
                datos_ok.append([float(p) for p in partes])
                filas_ok.append(k)
            except ValueError:
                invalidas.append((primera + k, "valor no numérico"))
        datos = np.array(datos_ok, dtype=float).reshape(-1, len(columnas))
    return ArchivoTabla(Path(ruta), metadatos, columnas, datos, invalidas, primera)


def _lectura_rapida(lineas: list[str], metadatos: dict):
    """Camino rápido para archivos bien formados: un solo split y conversión vectorizada.

    Devuelve None si algo no cuadra; entonces se usa la lectura línea por línea, que
    identifica las filas defectuosas.
    """
    k = 0
    while k < len(lineas) and (not lineas[k].strip() or lineas[k].lstrip().startswith("#")):
        contenido = lineas[k].strip().lstrip("#").strip()
        if contenido:
            metadatos["_comentarios"].append(contenido)
            if ":" in contenido:
                clave, valor = contenido.split(":", 1)
                metadatos[clave.strip().lower()] = valor.strip()
        k += 1
    if k >= len(lineas):
        return None
    columnas = lineas[k].split()
    filas = [l for l in lineas[k + 1:] if l and not l.isspace()]
    cuerpo = " ".join(filas)
    if "#" in cuerpo:
        return None
    n_filas = len(filas)
    tokens = cuerpo.split()
    if not n_filas or len(tokens) != n_filas * len(columnas):
        return None
    try:
        datos = np.fromiter(map(float, tokens), dtype=float, count=len(tokens)).reshape(n_filas, len(columnas))
    except ValueError:
        return None
    return columnas, datos, k + 2


def fecha_de_nombre(nombre: str) -> datetime | None:
    m = PATRON_HORARIO.match(nombre)
    if not m:
        return None
    try:
        return datetime.strptime(m.group("fecha"), "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def huella_archivos(rutas: list[Path]) -> str:
    """SHA-256 del contenido de los archivos de entrada, en orden: identifica el conjunto exacto."""
    h = hashlib.sha256()
    for ruta in rutas:
        h.update(ruta.name.encode())
        h.update(Path(ruta).read_bytes())
    return h.hexdigest()


@dataclass
class ConjuntoDatos:
    """Campos ya validados y acomodados en la malla regular [tiempo, lat, lon]."""
    id: str
    lons: np.ndarray
    lats: np.ndarray
    tiempos: list[datetime]
    viento_u: np.ndarray        # m/s, hacia el este
    viento_v: np.ndarray        # m/s, hacia el norte
    viento_vel: np.ndarray      # m/s (WindsfcSp)
    viento_dir: np.ndarray      # grados "desde" (WindsfcDir)
    ola_dir: np.ndarray         # grados "desde" (sfcPrimWaDir), NaN en tierra
    corriente_u: np.ndarray     # m/s [lat, lon], estacionaria
    corriente_v: np.ndarray
    mar: np.ndarray             # bool [lat, lon]: nodo con dato de oleaje (mar)
    archivos: list[str]
    huella: str
    sintetico: bool
    corrientes_esquematicas: bool

    @property
    def horas(self) -> int:
        return len(self.tiempos)

    def resumen(self) -> dict:
        return {
            "id": self.id,
            "archivos": len(self.archivos),
            "primero": self.archivos[0],
            "ultimo": self.archivos[-1],
            "inicio_utc": self.tiempos[0].strftime("%Y-%m-%dT%H:%MZ"),
            "fin_utc": self.tiempos[-1].strftime("%Y-%m-%dT%H:%MZ"),
            "huella_sha256": self.huella,
            "sintetico": self.sintetico,
            "corrientes_esquematicas": self.corrientes_esquematicas,
            "puntos_malla": int(self.lons.size * self.lats.size),
            "puntos_mar": int(self.mar.sum()),
        }
