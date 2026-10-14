"""Genera fixtures pequeños en el FORMATO REAL de SEMAR, solo para pruebas.

La aplicación ya no usa datos simulados: lee data/semar/. Este script existe para que las
pruebas (pytest y Playwright) no dependan de los archivos de SEMAR, que no se publican.
Produce archivos con exactamente la misma estructura que los reales:

    salidadatos.txt   LON;LAT;sfcPrimWaDir;sfcDirWindWa;U;V;WindsfcSp;WindsfcDir
                      línea de fecha «19AUG2026 00», filas de norte a sur y de oeste a este,
                      −9.99e+08 en tierra y sfcDirWindWa ausente en parte del mar
    dirmarea.txt      LON;LAT;dirolavto;alturaolavto
                      41 bloques «01OCT2026 00 h» (h = 0, 3, …, 120), malla desplazada 0.08°

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
    ARCHIVO_OLEAJE, ARCHIVO_VIENTO, COLUMNAS_OLEAJE, COLUMNAS_VIENTO, HORIZONTE_H, LAT_MAX, LAT_MIN,
    LON_MAX, LON_MIN, PASO_OLEAJE_H, RESOLUCION_GRADOS,
)
from src.ingestion.lector import formatear_fecha  # noqa: E402
from src.model import costa  # noqa: E402
from src.model.conversiones import desde_a_vector  # noqa: E402

FECHA_VIENTO = datetime(2026, 8, 19, 0, tzinfo=timezone.utc)
FECHA_OLEAJE = datetime(2026, 10, 1, 0, tzinfo=timezone.utc)
RELLENO = "-9.99e+08"
# Recuadro chico alrededor de Cancún y Cozumel (10 × 11 nodos), alineado con la malla de SEMAR.
CANCUN = (-87.52, -86.08, 20.12, 21.72)
DOMINIO = (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)


def nodos(lon_min, lon_max, lat_min, lat_max, paso=RESOLUCION_GRADOS):
    lons = np.round(lon_min + paso * np.arange(int(round((lon_max - lon_min) / paso)) + 1), 2)
    lats = np.round(lat_min + paso * np.arange(int(round((lat_max - lat_min) / paso)) + 1), 2)
    return lons, lats


def _num(v: float) -> str:
    """Como en los archivos de SEMAR: sin ceros de más (−124, 39, −123.84)."""
    if not np.isfinite(v):
        return RELLENO
    return f"{v:.2f}".rstrip("0").rstrip(".")


def viento_analitico(x, y, hora=0.0):
    """Alisios del E/SE de ~6 m/s que giran lentamente (velocidad m/s, dirección «desde»)."""
    direccion = 105.0 + 4.0 * (y - 20.0) + 6.0 * np.sin(0.9 * x - 0.6 * y) + 0.1 * hora
    velocidad = 6.0 + 0.6 * (x + 88.0) / 4 + 1.0 * np.sin(1.3 * x + 0.9 * y) + 0.01 * hora
    return np.clip(velocidad, 0.5, 17.0), np.mod(direccion, 360.0)


def _filas(lons, lats):
    """Orden de SEMAR: de norte a sur y, en cada latitud, de oeste a este."""
    X, Y = np.meshgrid(lons, lats[::-1])
    return X.ravel(), Y.ravel()


def escribir_salidadatos(ruta: Path, extension=CANCUN, fecha=FECHA_VIENTO, horas=(None,), viento=viento_analitico) -> Path:
    """Viento y direcciones de oleaje. `horas=(None,)` escribe un solo bloque como el real
    («19AUG2026 00»); con horas numéricas escribe un bloque por hora («19AUG2026 00 3»)."""
    lons, lats = nodos(*extension)
    x, y = _filas(lons, lats)
    tierra = costa.en_tierra(x, y)
    lineas = [";".join(COLUMNAS_VIENTO)]
    for h in horas:
        vel, dirr = viento(x, y, 0.0 if h is None else float(h))
        u, v = desde_a_vector(vel, dirr)
        ola_prim = np.mod(90.0 + 0.3 * (dirr - 105.0), 360.0)
        ola_viento = np.mod(dirr + 11.0, 360.0)
        # No hay mar de viento en todos los nodos de mar (como en los datos reales).
        sin_mar_de_viento = (np.round((x - lons[0]) / RESOLUCION_GRADOS) % 4) == 0
        lineas.append(formatear_fecha(fecha, h))
        for k in range(x.size):
            if tierra[k]:
                lineas.append(f"{_num(x[k])};{_num(y[k])};" + ";".join([RELLENO] * 6))
                continue
            ww = RELLENO if sin_mar_de_viento[k] else _num(ola_viento[k])
            lineas.append(f"{_num(x[k])};{_num(y[k])};{_num(ola_prim[k])};{ww};{_num(u[k])};{_num(v[k])};"
                          f"{_num(vel[k])};{_num(dirr[k])}")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def ola_analitica(x, y, hora=0.0):
    """Ola de viento: dirección «desde» ~100° y altura que crece hacia el este (m)."""
    direccion = np.mod(100.0 + 5.0 * (y - 20.0) + 0.2 * hora, 360.0)
    altura = 0.4 + 0.25 * (x + 92.0) + 0.002 * hora
    return direccion, altura


def escribir_dirmarea(ruta: Path, extension=CANCUN, fecha=FECHA_OLEAJE, horas=None, identicos=True, ola=ola_analitica) -> Path:
    """Oleaje en 41 bloques (+0 … +120 h) sobre una malla desplazada 0.08° en longitud.
    Con `identicos=True` todos los bloques son iguales, como en el archivo de muestra."""
    lon_min, lon_max, lat_min, lat_max = extension
    lons, lats = nodos(lon_min - 0.08, lon_max + 0.08, lat_min, lat_max)
    x, y = _filas(lons, lats)
    tierra = costa.en_tierra(x, y)
    horas = list(range(0, HORIZONTE_H + 1, PASO_OLEAJE_H)) if horas is None else list(horas)
    lineas = [";".join(COLUMNAS_OLEAJE)]
    for h in horas:
        direccion, altura = ola(x, y, 0.0 if identicos else float(h))
        lineas.append(f"{formatear_fecha(fecha, h)}")
        lineas.extend(f"{_num(x[k])};{_num(y[k])};" + (f"{RELLENO};{RELLENO}" if tierra[k] else
                      f"{_num(direccion[k])};{_num(altura[k])}") for k in range(x.size))
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def crear_fixture(destino: Path, completo: bool = False, **kw) -> Path:
    """Carpeta con salidadatos.txt y dirmarea.txt en el formato real."""
    extension = DOMINIO if completo else CANCUN
    destino = Path(destino)
    escribir_salidadatos(destino / ARCHIVO_VIENTO, extension, **kw)
    escribir_dirmarea(destino / ARCHIVO_OLEAJE, extension)
    return destino


def principal(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destino", type=Path, required=True)
    parser.add_argument("--completo", action="store_true", help="dominio completo (51 × 39 nodos) en lugar de Cancún")
    args = parser.parse_args(argv)
    crear_fixture(args.destino, args.completo)
    print(f"[ok] fixture en formato SEMAR (valores sintéticos) en {args.destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
