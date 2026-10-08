"""Punto de entrada del prototipo PMS.

    python main.py            → http://localhost:8000
    python main.py --puerto 8080 --no-navegador
"""
from __future__ import annotations

import argparse
from pathlib import Path
import threading
import webbrowser

import uvicorn

from src.api.app import crear_app
from src.config import DIR_DATOS, VERSION_APP


def principal() -> None:
    parser = argparse.ArgumentParser(description="PMS · Predicción de Movimiento del Sargazo (prototipo)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--no-navegador", action="store_true", help="no abrir el navegador automáticamente")
    parser.add_argument("--datos", type=Path, default=DIR_DATOS, help="carpeta con los conjuntos de datos (por defecto data/)")
    parser.add_argument("--simulaciones", type=Path, default=None, help="carpeta donde se guardan las simulaciones (por defecto <datos>/simulations)")
    args = parser.parse_args()

    url = f"http://localhost:{args.puerto}"
    print(f"PMS prototipo v{VERSION_APP} · datos en {args.datos}")
    if not any((args.datos / "demo").glob("*.txt")):
        print("Aviso: no hay datos de demostración; ejecuta  python scripts/generar_datos_demo.py")
    print(f"Abriendo {url}  (Ctrl+C para detener)")
    if not args.no_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app = crear_app(args.datos, args.simulaciones or args.datos / "simulations")
    uvicorn.run(app, host=args.host, port=args.puerto, log_level="warning")


if __name__ == "__main__":
    principal()
