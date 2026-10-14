"""Fixtures compartidas: datos pequeños en el formato real de SEMAR, generados en tmp."""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from scripts.generar_fixtures import crear_fixture
from src.config import ARCHIVO_VIENTO, DIR_SEMAR

HAY_DATOS_REALES = (DIR_SEMAR / ARCHIVO_VIENTO).is_file()
solo_con_datos_reales = pytest.mark.skipif(
    not HAY_DATOS_REALES, reason="data/semar/ no tiene los archivos de SEMAR (no se publican en git)")


@pytest.fixture(scope="session")
def semar_base(tmp_path_factory) -> Path:
    """Recuadro de Cancún y Cozumel (10 × 11 nodos), ~0.3 s; se genera una vez por sesión."""
    return crear_fixture(tmp_path_factory.mktemp("base") / "semar")


@pytest.fixture
def semar(semar_base, tmp_path) -> Path:
    """Copia editable del fixture para que cada prueba pueda sembrar errores."""
    destino = tmp_path / "semar"
    shutil.copytree(semar_base, destino)
    return destino


def editar_lineas(ruta: Path, funcion) -> None:
    """Aplica `funcion(lineas) -> lineas` a un archivo de texto y lo reescribe."""
    lineas = Path(ruta).read_text(encoding="utf-8").splitlines()
    Path(ruta).write_text("\n".join(funcion(lineas)) + "\n", encoding="utf-8")


def editar_columna(ruta: Path, columna: str, funcion, solo_mar: bool = True) -> None:
    """Aplica `funcion(valor: float) -> float | str` a una columna de todas las filas de datos."""
    def cambiar(lineas):
        k = lineas[0].split(";").index(columna)
        salida = [lineas[0]]
        for linea in lineas[1:]:
            partes = linea.split(";")
            if len(partes) > k and not (solo_mar and "-9.99e+08" in partes[k]):
                nuevo = funcion(float(partes[k]))
                partes[k] = nuevo if isinstance(nuevo, str) else f"{nuevo:.2f}"
            salida.append(";".join(partes))
        return salida
    editar_lineas(ruta, cambiar)


def sin_tierra(lon, lat):
    return np.zeros(np.shape(lon), dtype=bool)
