"""Fixtures compartidas: un conjunto sintético pequeño (120 h, malla recortada) para pruebas rápidas."""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from scripts.generar_datos_demo import PREFIJO, escribir_conjunto, malla

# Recuadro chico alrededor de Cancún y Cozumel: 10 × 11 nodos, ~0.2 s por conjunto.
LONS_PEQ, LATS_PEQ = malla(lon_min=-87.52, lon_max=-86.08, lat_min=20.12, lat_max=21.72)


@pytest.fixture(scope="session")
def conjunto_base(tmp_path_factory) -> Path:
    destino = tmp_path_factory.mktemp("base") / "demo"
    escribir_conjunto(destino, lons=LONS_PEQ, lats=LATS_PEQ)
    return destino


@pytest.fixture
def conjunto(conjunto_base, tmp_path) -> Path:
    """Copia editable del conjunto pequeño para que cada prueba pueda sembrar errores."""
    destino = tmp_path / "demo"
    shutil.copytree(conjunto_base, destino)
    return destino


def archivos_horarios(directorio: Path) -> list[Path]:
    return sorted(Path(directorio).glob(f"{PREFIJO}*.txt"))


def editar_filas(ruta: Path, funcion) -> None:
    """Aplica `funcion(columnas, filas)` a un archivo y lo reescribe."""
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    comentarios = [l for l in lineas if l.startswith("#")]
    k = next(i for i, l in enumerate(lineas) if l and not l.startswith("#"))
    columnas = lineas[k].split()
    filas = [l.split() for l in lineas[k + 1:] if l.strip()]
    columnas, filas = funcion(columnas, filas)
    texto = "\n".join(comentarios + [" ".join(columnas)] + [" ".join(f) for f in filas]) + "\n"
    ruta.write_text(texto, encoding="utf-8")


def sin_tierra(lon, lat):
    return np.zeros(np.shape(lon), dtype=bool)
