"""Genera fixtures pequeños de dirmarea.txt en el FORMATO REAL de SEMAR, solo para pruebas.

La aplicación lee data/semar/dirmarea.txt. Este script existe para que las pruebas
(pytest y Playwright) no dependan de ese archivo y puedan sembrar errores. Produce un
archivo con exactamente la misma estructura que el real:

    LON;LAT;dirolavto;alturaolavto
    41 bloques «01OCT2026 00 h» (h = 0, 3, …, 120), filas de norte a sur y de oeste a
    este, malla de 0.16° alineada a la de SEMAR (lon −98 + 0.16·k, lat 15 + 0.16·k) y
    −9.99e+08 en tierra.

Los valores son funciones analíticas suaves (no son datos de SEMAR).

Uso (PowerShell):
    python scripts/generar_fixtures.py --destino tmp/fixture            # recuadro de Cancún
    python scripts/generar_fixtures.py --destino tmp/fixture --completo # dominio completo
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (  # noqa: E402
    ARCHIVO_OLEAJE, COLUMNAS_OLEAJE, HORIZONTE_H, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, PASO_OLEAJE_H,
    RESOLUCION_GRADOS,
)
from src.ingestion.lector import formatear_fecha  # noqa: E402
from src.model import costa  # noqa: E402

FECHA_OLEAJE = datetime(2026, 10, 1, 0, tzinfo=timezone.utc)
RELLENO = "-9.99e+08"
# Recuadro chico alrededor de Cancún y Cozumel (11 × 11 nodos), alineado con la malla de SEMAR.
CANCUN = (-87.60, -86.00, 20.12, 21.72)
DOMINIO = (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)


def nodos(lon_min, lon_max, lat_min, lat_max, paso=RESOLUCION_GRADOS):
    lons = np.round(lon_min + paso * np.arange(int(round((lon_max - lon_min) / paso)) + 1), 2)
    lats = np.round(lat_min + paso * np.arange(int(round((lat_max - lat_min) / paso)) + 1), 2)
    return lons, lats


def _num(v: float) -> str:
    """Como en los archivos de SEMAR: sin ceros de más (−98, 23, −97.84)."""
    if not np.isfinite(v):
        return RELLENO
    return f"{v:.2f}".rstrip("0").rstrip(".")


def ola_analitica(x, y, hora=0.0):
    """Ola de viento: dirección «desde» ~100° (viaja al ONO) y altura que crece hacia el este (m)."""
    direccion = np.mod(100.0 + 5.0 * (y - 20.0) + 0.2 * hora, 360.0)
    altura = 0.4 + 0.25 * (x + 92.0) + 0.002 * hora
    return direccion, altura


def _filas(lons, lats):
    """Orden de SEMAR: de norte a sur y, en cada latitud, de oeste a este."""
    X, Y = np.meshgrid(lons, lats[::-1])
    return X.ravel(), Y.ravel()


def escribir_dirmarea(ruta: Path, extension=CANCUN, fecha=FECHA_OLEAJE, horas=None, identicos=True,
                      ola=ola_analitica) -> Path:
    """41 bloques (+0 … +120 h). Con `identicos=True` todos son iguales, como en el archivo de muestra."""
    lons, lats = nodos(*extension)
    x, y = _filas(lons, lats)
    tierra = costa.en_tierra(x, y)
    horas = list(range(0, HORIZONTE_H + 1, PASO_OLEAJE_H)) if horas is None else list(horas)
    lineas = [";".join(COLUMNAS_OLEAJE)]
    for h in horas:
        direccion, altura = ola(x, y, 0.0 if identicos else float(h))
        lineas.append(formatear_fecha(fecha, h))
        lineas.extend(f"{_num(x[k])};{_num(y[k])};" + (f"{RELLENO};{RELLENO}" if tierra[k] else
                      f"{_num(direccion[k])};{_num(altura[k])}") for k in range(x.size))
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def crear_fixture(destino: Path, completo: bool = False, **kw) -> Path:
    """Carpeta con dirmarea.txt en el formato real."""
    destino = Path(destino)
    escribir_dirmarea(destino / ARCHIVO_OLEAJE, DOMINIO if completo else CANCUN, **kw)
    return destino


def principal(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destino", type=Path, required=True)
    parser.add_argument("--completo", action="store_true", help="dominio completo (51 × 39 nodos) en lugar de Cancún")
    args = parser.parse_args(argv)
    crear_fixture(args.destino, args.completo)
    print(f"[ok] fixture de {ARCHIVO_OLEAJE} en formato SEMAR (valores sintéticos) en {args.destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
