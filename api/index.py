"""Punto de entrada para Vercel (función Python sin servidor).

Vercel enruta todas las peticiones a esta función (ver vercel.json). Diferencias con
`python main.py`:
  - El disco es de solo lectura salvo /tmp: las simulaciones se guardan en
    /tmp/pms-simulaciones y son efímeras (se pierden al reciclarse la instancia).
  - Los datos de SEMAR se leen de data/semar/ dentro del paquete desplegado (están en el
    repositorio privado, así que los despliegues desde GitHub los incluyen).
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.api.app import crear_app  # noqa: E402
from src.config import DIR_SEMAR  # noqa: E402

app = crear_app(DIR_SEMAR, Path("/tmp") / "pms-simulaciones")
