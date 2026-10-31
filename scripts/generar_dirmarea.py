"""Genera un dirmarea.txt con el oleaje de viento REAL de una fecha (Open-Meteo / MFWAM).

Mismo formato que el archivo de SEMAR (ver validacion/dirmarea.py), de modo que el
validador y el modelo del producto lo leen sin cambios.

Uso (PowerShell):
    python scripts/generar_dirmarea.py --fecha 2026-10-01 --destino data/validacion/dirmarea_2026-10-01
    python main.py --datos data/validacion/dirmarea_2026-10-01      # la app con ese oleaje
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.ingestion.validador import validar_conjunto  # noqa: E402
from validacion import config as cfg  # noqa: E402
from validacion.dirmarea import generar  # noqa: E402


def principal(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fecha", required=True, type=date.fromisoformat, help="fecha base (AAAA-MM-DD), 00 UTC")
    p.add_argument("--destino", type=Path, help="carpeta de salida (por defecto data/validacion/dirmarea_<fecha>)")
    a = p.parse_args(argv)
    destino = a.destino or cfg.DIR_CACHE / f"dirmarea_{a.fecha.isoformat()}"
    ruta, resumen = generar(a.fecha, destino)
    reporte, conjunto = validar_conjunto(destino)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(f"[{'ok' if reporte.valido else 'error'}] {ruta}")
    for v in reporte.verificaciones:
        print(f"  {v.estado:11s} {v.nombre}: {v.resumen}")
        for h in v.hallazgos:
            print(f"      - {h.nivel}: {h.detalle}")
    return 0 if reporte.valido else 1


if __name__ == "__main__":
    raise SystemExit(principal())
