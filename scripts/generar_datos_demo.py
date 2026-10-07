"""Genera el conjunto de datos SINTÉTICO del prototipo PMS.

Crea, por defecto:
  data/demo/                  120 archivos horarios con el esquema de SEMAR
  data/demo/corrientes/       un campo de corriente esquemático (estacionario)
  data/demo_errores/          copia con tres errores sembrados para probar el validador

Los valores NO provienen de SEMAR, CMEMS ni HYCOM: son funciones analíticas suaves
diseñadas para parecer plausibles (alisios del E/SE de ~5 m/s, Corriente de Yucatán
hacia el norte) y permitir demostrar la aplicación de punta a punta mientras se
confirma el formato oficial de los archivos.

Uso (PowerShell):
    python scripts/generar_datos_demo.py
    python scripts/generar_datos_demo.py --inicio 2026-10-01T00 --destino data/demo
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (  # noqa: E402
    COLUMNAS_CORRIENTE, COLUMNAS_SEMAR, DIR_DATOS, HORAS_ESPERADAS, LAT_MAX, LAT_MIN,
    LON_MAX, LON_MIN, RESOLUCION_GRADOS,
)
from src.model import costa  # noqa: E402
from src.model.conversiones import desde_a_vector  # noqa: E402

INICIO_DEFECTO = datetime(2026, 10, 1, 0, tzinfo=timezone.utc)
PREFIJO = "salidadatos_"
NOMBRE_CORRIENTES = "corrientes_esquematicas.txt"

AVISO = [
    "PMS - DATOS SINTETICOS. NO SON DATOS DE SEMAR NI DE CMEMS/HYCOM.",
    "Generados por scripts/generar_datos_demo.py solo para demostrar el prototipo;",
    "el formato oficial de SEMAR aun no esta confirmado.",
]


def malla(lon_min=LON_MIN, lon_max=LON_MAX, lat_min=LAT_MIN, lat_max=LAT_MAX,
          paso=RESOLUCION_GRADOS):
    """Nodos de la malla de 0.16°, redondeados para evitar ruido de coma flotante."""
    lons = np.round(lon_min + paso * np.arange(int(round((lon_max - lon_min) / paso)) + 1), 2)
    lats = np.round(lat_min + paso * np.arange(int(round((lat_max - lat_min) / paso)) + 1), 2)
    return lons, lats


def _suave(t, centro, ancho):
    return 0.5 * (1.0 + np.tanh((t - centro) / ancho))


def evento_norte(t):
    """Intensidad (0–1) de un evento de viento del NE entre las horas ~78 y ~108."""
    return _suave(t, 78.0, 6.0) - _suave(t, 108.0, 6.0)


def campo_viento(x, y, t, tierra):
    """Viento a 10 m: (velocidad m/s, dirección "desde" en grados).

    Alisios del E/SE (~105°) de ~5 m/s con ciclo diurno, un giro lento de ±15° y un
    evento del NE más intenso el día 4. Sobre tierra se debilita.
    """
    ev = evento_norte(t)
    direccion = (
        105.0
        + 15.0 * np.sin(2 * np.pi * t / 72.0)
        + 6.0 * np.sin(2 * np.pi * (t - 14.0) / 24.0)
        + 4.0 * (y - 20.0)
        - 55.0 * ev
        + 5.0 * np.sin(0.9 * x - 0.6 * y + t / 11.0)
    )
    velocidad = (
        5.5
        + 1.0 * np.sin(2 * np.pi * (t - 10.0) / 24.0)
        + 0.8 * np.sin(2 * np.pi * t / 60.0 + 0.5 * x)
        + 3.4 * ev
        + 0.15 * (x + 88.0)
        + 0.7 * np.sin(1.3 * x + 0.9 * y + t / 9.0) * np.cos(0.7 * y - t / 13.0)
    )
    velocidad = np.where(tierra, 0.55 * velocidad, velocidad)
    return np.clip(velocidad, 0.01, 17.0), np.mod(direccion, 360.0)


def campo_oleaje(x, y, t, direccion_viento, tierra):
    """Direcciones "desde" del oleaje primario (mar de fondo) y del oleaje de viento."""
    primaria = 88.0 + 10.0 * np.sin(2 * np.pi * t / 96.0) + 0.25 * (direccion_viento - 105.0) + 2.0 * (y - 20.0)
    de_viento = direccion_viento + 6.0 * np.sin(0.8 * x + t / 7.0)
    primaria = np.where(tierra, np.nan, np.mod(primaria, 360.0))
    de_viento = np.where(tierra, np.nan, np.mod(de_viento, 360.0))
    return primaria, de_viento


_EJE_CORRIENTE_LAT = np.array([18.0, 18.6, 19.5, 20.3, 21.0, 21.5, 22.0, 22.5, 23.2])
_EJE_CORRIENTE_LON = np.array([-87.20, -87.05, -86.95, -86.55, -86.30, -86.05, -85.85, -85.70, -85.55])


def campo_corriente(x, y, tierra, distancia_costa_km):
    """Corriente superficial esquemática (uo, vo) en m/s, estacionaria.

    - Corriente de Yucatán: chorro hacia el norte cuyo eje va del E de Cozumel al canal
      de Yucatán, con máximo de ~1.5 m/s entre Cancún y Cuba.
    - Corriente del Caribe: flujo débil hacia el O-NO al sur de 21°N que alimenta el chorro.
    - Banco de Campeche: deriva débil hacia el oeste al norte de la península.
    - Se debilita al acercarse a la costa y es cero sobre tierra.
    """
    eje = np.interp(y, _EJE_CORRIENTE_LAT, _EJE_CORRIENTE_LON)
    pendiente = np.gradient(_EJE_CORRIENTE_LON, _EJE_CORRIENTE_LAT)
    dlon_dlat = np.interp(y, _EJE_CORRIENTE_LAT, pendiente)
    # Vector tangente al eje en metros (este, norte), normalizado.
    tx = dlon_dlat * np.cos(np.radians(y))
    norma = np.hypot(tx, 1.0)
    tx, ty = tx / norma, 1.0 / norma

    pico = np.interp(y, [17.5, 18.6, 20.0, 21.3, 23.5], [0.25, 0.55, 1.05, 1.50, 1.50])
    ancho = np.interp(y, [17.5, 21.0, 23.5], [0.55, 0.38, 0.45])
    peso_chorro = np.exp(-(((x - eje) / ancho) ** 2))
    u = pico * peso_chorro * tx
    v = pico * peso_chorro * ty

    # Caribe: hacia el O-NO, se apaga al norte de 21°N y al fundirse con el chorro.
    caribe = (1.0 - _suave(y, 21.0, 0.35)) * (1.0 - peso_chorro) * _suave(x, -87.6, 0.4)
    u += -0.28 * caribe
    v += 0.10 * caribe

    # Banco de Campeche (norte y oeste de la península): deriva débil.
    golfo = _suave(y, 21.55, 0.12) * (1.0 - _suave(x, -86.9, 0.25)) * (1.0 - peso_chorro)
    u += -0.14 * golfo
    v += -0.02 * golfo
    oeste = 1.0 - _suave(x, -90.0, 0.3)
    u += -0.03 * oeste * (1.0 - golfo)
    v += 0.07 * oeste * (1.0 - golfo)

    # Corriente costera débil hacia el norte frente a Quintana Roo.
    costera = np.exp(-distancia_costa_km / 25.0) * (1.0 - _suave(y, 21.5, 0.15)) * _suave(x, -88.2, 0.2)
    v += 0.22 * costera

    atenuacion = np.clip(distancia_costa_km / 30.0, 0.0, 1.0) ** 0.6
    u = np.where(tierra, 0.0, u * atenuacion)
    v = np.where(tierra, 0.0, v * atenuacion)
    return u, v


def _encabezado(lineas_extra, columnas):
    """Comentarios (#) con el aviso y metadatos, seguidos de la fila de nombres de columna."""
    return "\n".join([f"# {l}" for l in AVISO + lineas_extra] + [" ".join(columnas)])


def escribir_conjunto(destino: Path, inicio: datetime = INICIO_DEFECTO, horas: int = HORAS_ESPERADAS,
                      lons=None, lats=None) -> list[Path]:
    """Escribe `horas` archivos horarios y el campo de corrientes en `destino`."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    for viejo in destino.glob(f"{PREFIJO}*.txt"):
        viejo.unlink()
    if lons is None or lats is None:
        lons, lats = malla()
    X, Y = np.meshgrid(lons, lats)
    x, y = X.ravel(), Y.ravel()
    tierra = costa.en_tierra(x, y)

    archivos = []
    for h in range(horas):
        fecha = inicio + timedelta(hours=h)
        velocidad, direccion = campo_viento(x, y, float(h), tierra)
        u, v = desde_a_vector(velocidad, direccion)
        ola_primaria, ola_viento = campo_oleaje(x, y, float(h), direccion, tierra)
        datos = np.column_stack([x, y, u, v, velocidad, direccion, ola_primaria, ola_viento])
        ruta = destino / f"{PREFIJO}{fecha:%Y%m%d%H}.txt"
        encabezado = _encabezado([
            f"fecha_validez: {fecha:%Y-%m-%dT%H:%MZ}",
            f"malla: {RESOLUCION_GRADOS} grados; lon {lons[0]:.2f}..{lons[-1]:.2f}; lat {lats[0]:.2f}..{lats[-1]:.2f}",
            "unidades: U,V,WindsfcSp en m/s; direcciones en grados DESDE (meteorologica); NaN = sin dato (tierra)",
        ], COLUMNAS_SEMAR)
        np.savetxt(ruta, datos, fmt=["%.2f", "%.2f", "%.3f", "%.3f", "%.3f", "%.2f", "%.1f", "%.1f"],
                   header=encabezado, comments="", delimiter=" ")
        archivos.append(ruta)

    dist = costa.distancia_costa_km(x, y)
    uo, vo = campo_corriente(x, y, tierra, dist)
    dir_corr = destino / "corrientes"
    dir_corr.mkdir(exist_ok=True)
    encabezado = _encabezado([
        "campo: corriente superficial ESQUEMATICA y estacionaria (sustituye a CMEMS/HYCOM, aun sin fuente confirmada)",
        "unidades: UO (este) y VO (norte) en m/s, convencion oceanografica (hacia donde fluye)",
    ], COLUMNAS_CORRIENTE)
    np.savetxt(dir_corr / NOMBRE_CORRIENTES, np.column_stack([x, y, uo, vo]),
               fmt=["%.2f", "%.2f", "%.3f", "%.3f"], header=encabezado, comments="", delimiter=" ")
    return archivos


def sembrar_errores(origen: Path, destino: Path) -> dict:
    """Copia `origen` en `destino` y siembra tres errores que el validador debe detectar."""
    origen, destino = Path(origen), Path(destino)
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(origen, destino)
    archivos = sorted(destino.glob(f"{PREFIJO}*.txt"))

    faltante = archivos[57]
    faltante.unlink()

    lat_mala = archivos[10]
    lineas = lat_mala.read_text(encoding="utf-8").splitlines()
    i = next(k for k, l in enumerate(lineas) if l.startswith("LON")) + 6
    partes = lineas[i].split()
    partes[1] = "95.00"
    lineas[i] = " ".join(partes)
    lat_mala.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    sin_columna = archivos[80]
    lineas = sin_columna.read_text(encoding="utf-8").splitlines()
    nuevas = []
    for l in lineas:
        if l.startswith("LON"):
            nuevas.append(" ".join(c for c in l.split() if c != "WindsfcDir"))
        elif l and not l.startswith("#"):
            p = l.split()
            nuevas.append(" ".join(p[:5] + p[6:]))
        else:
            nuevas.append(l)
    sin_columna.write_text("\n".join(nuevas) + "\n", encoding="utf-8")

    (destino / "LEEME.md").write_text(
        "# Conjunto con errores sembrados (SINTÉTICO)\n\n"
        "Copia de `data/demo/` con tres errores intencionales para demostrar el validador:\n\n"
        f"1. Falta el archivo horario `{faltante.name}` (hora +57).\n"
        f"2. `{lat_mala.name}` tiene una fila con LAT = 95.00 (fuera de rango).\n"
        f"3. `{sin_columna.name}` no tiene la columna `WindsfcDir`.\n\n"
        "La aplicación debe mostrar el estado **Error** con la causa, el archivo afectado y la acción.\n",
        encoding="utf-8",
    )
    return {"faltante": faltante.name, "latitud": lat_mala.name, "columna": sin_columna.name}


def principal(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--destino", type=Path, default=DIR_DATOS / "demo")
    parser.add_argument("--inicio", default=INICIO_DEFECTO.strftime("%Y-%m-%dT%H"),
                        help="fecha de validez del primer archivo, UTC (AAAA-MM-DDTHH)")
    parser.add_argument("--sin-errores", action="store_true", help="no crear data/demo_errores/")
    args = parser.parse_args(argv)

    inicio = datetime.strptime(args.inicio, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    archivos = escribir_conjunto(args.destino, inicio)
    print(f"[ok] {len(archivos)} archivos horarios sintéticos en {args.destino}")
    print(f"[ok] corrientes esquemáticas en {args.destino / 'corrientes' / NOMBRE_CORRIENTES}")
    if not args.sin_errores:
        destino_errores = args.destino.parent / f"{args.destino.name}_errores"
        info = sembrar_errores(args.destino, destino_errores)
        print(f"[ok] conjunto con errores sembrados en {destino_errores}: {info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
