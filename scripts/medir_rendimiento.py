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
from src.config import DIR_DATOS  # noqa: E402
from src.ingestion.validador import validar_conjunto  # noqa: E402
from src.model.campos import CamposMalla  # noqa: E402
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
    demo = DIR_DATOS / "demo"
    if not any(demo.glob("*.txt")):
        print("Primero genera los datos: python scripts/generar_datos_demo.py")
        return 1
    filas = []
    med, mx, (reporte, conjunto) = medir(lambda: validar_conjunto(demo))
    filas.append(("Validar 120 archivos + corrientes", f"{med:.2f} s", f"{mx:.2f} s", f"{pico_memoria(lambda: validar_conjunto(demo)):.0f} MB"))

    campos = CamposMalla(conjunto)
    for n in (500, 2000, 5000):
        p = Parametros(lon=-86.66, lat=21.12, particulas=n, horizonte_h=120)
        med, mx, r = medir(lambda: simular(campos, p))
        filas.append((f"Simular {n:,} partículas × 120 h".replace(",", " "), f"{med:.2f} s", f"{mx:.2f} s",
                      f"{pico_memoria(lambda: simular(campos, p)):.0f} MB"))
        if n in (2000, 5000):
            t0 = time.perf_counter()
            reg = armar_registro(r, resumir(r), conjunto.resumen())
            texto = json.dumps(reg, ensure_ascii=False, separators=(",", ":"))
            filas.append((f"Métricas + registro JSON ({n:,} partículas)".replace(",", " "),
                          f"{time.perf_counter() - t0:.2f} s", "—", f"{len(texto) / 2**20:.1f} MB en disco"))

    servicio = ServicioDatos(DIR_DATOS)
    campos_json = json.dumps(servicio.campos("demo"), separators=(",", ":")).encode()
    filas.append(("Campos para la interfaz (JSON)", "—", "—",
                  f"{len(campos_json) / 2**20:.1f} MB; {len(gzip.compress(campos_json)) / 2**20:.1f} MB con gzip"))

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
        f"- Conjunto: {conjunto.resumen()['puntos_malla']} nodos × 120 horas (sintético).",
        "- La simulación incluye la prueba de tierra por segmento y la búsqueda binaria del punto de varamiento.",
        "- La interfaz descarga los campos una sola vez por conjunto; la API los comprime con gzip.",
        "- Los tiempos varían con la carga del equipo: con poca RAM libre todo se vuelve más lento.",
        "",
    ]
    destino = RAIZ / "docs" / "rendimiento.md"
    destino.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
