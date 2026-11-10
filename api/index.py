"""Punto de entrada para Vercel (función Python sin servidor).

Vercel enruta todas las peticiones a esta función (ver vercel.json). Diferencias con
`python main.py`:
  - El disco es de solo lectura salvo /tmp: las simulaciones se guardan en
    /tmp/pms-simulaciones y son efímeras (se pierden al reciclarse la instancia).
  - El único archivo de entrada, data/semar/dirmarea.txt, viaja dentro del paquete de la
    función (vercel.json → includeFiles); está en el repositorio, así que los
    despliegues desde GitHub lo incluyen.
  - Modelo pms-browniano-0.4.0: deriva de Stokes de la ola de viento + movimiento browniano.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.api.app import crear_app  # noqa: E402
from src.config import DIR_SEMAR  # noqa: E402

app = crear_app(DIR_SEMAR, Path("/tmp") / "pms-simulaciones")
