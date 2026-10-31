"""Mide tiempos y memoria del prototipo en esta máquina y escribe docs/rendimiento.md.

Uso (PowerShell):
    python scripts/medir_rendimiento.py
"""
from __future__ import annotations

import gzip
import json
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

from src.api.almacen import armar_registro  # noqa: E402
from src.api.servicios import ServicioDatos  # noqa: E402
from src.config import ARCHIVO_OLEAJE, DIR_SEMAR  # noqa: E402
from src.ingestion.validador import validar_conjunto  # noqa: E402
from src.model.campos import CamposOleaje  # noqa: E402
from src.model.metricas import resumir  # noqa: E402
from src.model.simulacion import Parametros, simular  # noqa: E402

REPETICIONES = 3


def medir(funcion, repeticiones=REPETICIONES):
    tiempos, resultado = [], None
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        resultado = funcion()
        tiempos.append(time.perf_counter() - t0)
    return statistics.median(tiempos), max(tiempos), resultado


def pico_memoria(funcion) -> float:
    """Pico de memoria asignada por Python (MB) en una corrida aparte: tracemalloc vuelve lento el código."""
    tracemalloc.start()
    funcion()
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return pico / 2**20


def memoria_sistema() -> str:
    """RAM total y libre al medir (solo Windows); el resultado depende mucho de lo que haya abierto."""
    if platform.system() != "Windows":
        return "n/d"
    import ctypes

    class Estado(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    e = Estado()
    e.dwLength = ctypes.sizeof(Estado)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
    return f"{e.ullTotalPhys / 2**30:.1f} GB de RAM, {e.ullAvailPhys / 2**30:.1f} GB libres al medir"


def principal() -> int:
    if not (DIR_SEMAR / ARCHIVO_OLEAJE).is_file():
        print(f"Falta {ARCHIVO_OLEAJE} en {DIR_SEMAR} (ver data/semar/README.md).")
        return 1
    filas = []
    med, mx, (reporte, conjunto) = medir(lambda: validar_conjunto(DIR_SEMAR))
    filas.append(("Validar dirmarea.txt (lectura de 196 554 filas y 8 verificaciones)",
                  f"{med:.2f} s", f"{mx:.2f} s", f"{pico_memoria(lambda: validar_conjunto(DIR_SEMAR)):.0f} MB"))

    campos = CamposOleaje(conjunto)
    dominio = (float(conjunto.lons[0]), float(conjunto.lons[-1]), float(conjunto.lats[0]), float(conjunto.lats[-1]))
    for etiqueta, lon, lat in (("frente a Cancún", -86.66, 21.12), ("en mar abierto", -86.30, 21.00)):
        for n in (500, 2000, 5000):
            p = Parametros(lon=lon, lat=lat, particulas=n, horizonte_h=120)
            med, mx, r = medir(lambda: simular(campos, p, dominio=dominio))
            filas.append((f"Simular {n:,} partículas × 120 h {etiqueta}".replace(",", " "), f"{med:.2f} s", f"{mx:.2f} s",
                          f"{pico_memoria(lambda: simular(campos, p, dominio=dominio)):.0f} MB"))
    p = Parametros(lon=-86.30, lat=21.00, particulas=2000, horizonte_h=120)
    r = simular(campos, p, dominio=dominio)
    t0 = time.perf_counter()
    reg = armar_registro(r, resumir(r), conjunto.resumen())
    texto = json.dumps(reg, ensure_ascii=False, separators=(",", ":"))
    filas.append(("Métricas + registro JSON (2 000 partículas)", f"{time.perf_counter() - t0:.2f} s", "—",
                  f"{len(texto) / 2**20:.1f} MB en disco"))
    servicio = ServicioDatos(DIR_SEMAR)
    campos_json = json.dumps(servicio.campos(), separators=(",", ":")).encode()
    filas.append(("Campos de oleaje para la interfaz (41 bloques)", "—", "—",
                  f"{len(campos_json) / 2**20:.2f} MB; {len(gzip.compress(campos_json)) / 2**20:.2f} MB con gzip"))

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = [
        "# Rendimiento medido",
        "",
        f"Medido con `python scripts/medir_rendimiento.py` el {ahora} en "
        f"{platform.system()} {platform.release()}, Python {platform.python_version()}, NumPy {np.__version__}, "
        f"procesador `{platform.processor() or platform.machine()}`, {memoria_sistema()}. Mediana y máximo de {REPETICIONES} repeticiones; "
        "memoria = pico asignado por Python medido con tracemalloc en una corrida aparte (no incluye el intérprete).",
        "",
        "| Operación | Mediana | Máximo | Memoria / tamaño |",
        "|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} |" for a, b, c, d in filas],
        "",
        "Notas:",
        "",
        f"- Datos: {ARCHIVO_OLEAJE}, {conjunto.resumen()['puntos_malla']} nodos en el dominio "
        f"({conjunto.resumen()['puntos_mar']} con ola), 41 bloques idénticos; modelo pms-browniano-0.3.0.",
        "- Frente a Cancún (21.12° N, 86.66° O) la ola empuja hacia la costa: todas las partículas varan entre "
        "+8 h y +61 h (mediana +27 h) y las varadas dejan de calcularse; por eso esa simulación es más barata "
        "que la de mar abierto.",
        "- La interfaz descarga los campos de oleaje una sola vez al abrir; la API los comprime con gzip (los 41 "
        "bloques idénticos se comprimen casi por completo).",
        "- Los tiempos varían con la carga del equipo: con poca RAM libre todo se vuelve más lento.",
        "",
    ]
    destino = RAIZ / "docs" / "rendimiento.md"
    destino.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
