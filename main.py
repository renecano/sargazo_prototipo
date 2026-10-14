"""Punto de entrada de PMS.

    python main.py            → http://localhost:8000
    python main.py --puerto 8080 --no-navegador --datos D:/otra/carpeta/semar
"""
from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from src.api.app import crear_app
from src.config import ARCHIVO_VIENTO, DIR_SEMAR, DIR_SIMULACIONES, VERSION_APP


def principal() -> None:
    parser = argparse.ArgumentParser(description="PMS · Predicción de Movimiento del Sargazo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--no-navegador", action="store_true", help="no abrir el navegador automáticamente")
    parser.add_argument("--datos", type=Path, default=DIR_SEMAR,
                        help="carpeta con salidadatos.txt y dirmarea.txt (por defecto data/semar/)")
    parser.add_argument("--simulaciones", type=Path, default=DIR_SIMULACIONES,
                        help="carpeta donde se guardan las simulaciones (por defecto data/simulations/)")
    args = parser.parse_args()

    url = f"http://localhost:{args.puerto}"
    print(f"PMS v{VERSION_APP} · datos de SEMAR en {args.datos}")
    if not (args.datos / ARCHIVO_VIENTO).is_file():
        print(f"Aviso: falta {ARCHIVO_VIENTO}; copia los archivos de SEMAR en {args.datos} (ver data/semar/README.md)")
    print(f"Abriendo {url}  (Ctrl+C para detener)")
    if not args.no_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(crear_app(args.datos, args.simulaciones), host=args.host, port=args.puerto, log_level="warning")


if __name__ == "__main__":
    principal()
