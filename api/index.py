"""Punto de entrada para Vercel (función Python sin servidor).

Vercel enruta todas las peticiones a esta función (ver vercel.json). Diferencias con
`python main.py`:
  - El disco es de solo lectura salvo /tmp: las simulaciones se guardan en
    /tmp/pms-simulaciones y son efímeras (se pierden al reciclarse la instancia).
  - Si el despliegue no incluye data/demo/, se generan los datos sintéticos en /tmp
    al arrancar (son deterministas: todas las instancias producen el mismo conjunto).
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.api.app import crear_app  # noqa: E402
from src.config import DIR_DATOS  # noqa: E402

DIR_TMP = Path("/tmp")


def _dir_datos() -> Path:
    if any((DIR_DATOS / "demo").glob("*.txt")):
        return DIR_DATOS
    destino = DIR_TMP / "pms-datos"
    if not any((destino / "demo").glob("*.txt")):
        from scripts.generar_datos_demo import escribir_conjunto, sembrar_errores
        escribir_conjunto(destino / "demo")
        sembrar_errores(destino / "demo", destino / "demo_errores")
    return destino


app = crear_app(_dir_datos(), DIR_TMP / "pms-simulaciones")
