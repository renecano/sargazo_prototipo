"""Capturas de pantalla de la interfaz con Playwright (Edge o Chromium) para docs/.

Usa data/semar/dirmarea.txt y guarda las simulaciones de la sesión en una carpeta temporal.
Para cada tamaño (1366×768 y 1920×1080) produce en docs/capturas/:

    recorrido-<tamaño>.png    primer paso del recorrido guiado (se abre solo la primera vez)
    recorrido-mapa-<tamaño>.png  paso «Cómo leer el mapa» con una simulación real
    listo-<tamaño>.png        datos validados, paso 1
    resultado-<tamaño>.png    120 h frente a Cancún, pausado en +12 h, con el hover
    error-<tamaño>.png        copia del archivo sin la hora +57 (detalle desplegado)

y copia las de 1366×768 a docs/captura*.png para el README.

Uso (PowerShell):
    python scripts/capturar_pantalla.py
"""
from __future__ import annotations

import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from src.api.app import crear_app  # noqa: E402
from src.config import ARCHIVO_OLEAJE, DIR_SEMAR  # noqa: E402

DOCS = RAIZ / "docs"
TAMANOS = [(1366, 768), (1920, 1080)]


def _servidor(dir_semar: Path, dir_sims: Path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(crear_app(dir_semar, dir_sims), host="127.0.0.1", port=puerto, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return srv, f"http://127.0.0.1:{puerto}"


def _esperar(pg, estado, timeout=60_000):
    pg.wait_for_function(f"document.getElementById('estado').dataset.estado === '{estado}'", timeout=timeout)


def _captura(pg, ruta: Path, intentos: int = 3) -> None:
    """Captura con reintentos: en equipos con poca RAM libre Edge a veces tarda en entregar el cuadro."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    for k in range(intentos):
        try:
            pg.screenshot(path=str(ruta), timeout=45_000)
            print(f"[ok] {ruta.relative_to(RAIZ)}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"[reintento {k + 1}] {ruta.name}: {str(e).splitlines()[0]}")
    raise RuntimeError(f"No se pudo capturar {ruta.name}")


def _datos_con_error(destino: Path) -> Path:
    """Copia de dirmarea.txt sin el bloque +57 h."""
    destino.mkdir(parents=True)
    lineas = (DIR_SEMAR / ARCHIVO_OLEAJE).read_text(encoding="utf-8").splitlines()
    salida, saltar = [lineas[0]], False
    for linea in lineas[1:]:
        if ";" not in linea:
            saltar = linea.split()[-1] == "57"
        if not saltar:
            salida.append(linea)
    (destino / ARCHIVO_OLEAJE).write_text("\n".join(salida) + "\n", encoding="utf-8")
    return destino


def _navegador(p):
    try:
        return p.chromium.launch(channel="msedge")
    except Exception:  # noqa: BLE001
        return p.chromium.launch()


def _punto(pg, lat, lon):
    return pg.evaluate("""([lat, lon]) => { const p = window.pmsMapa.latLngToContainerPoint([lat, lon]);
        return [p.x, p.y]; }""", [lat, lon])


def _siguiente(pg):
    """Avanza el recorrido y espera a que el nuevo paso esté en pantalla."""
    k = int(pg.get_attribute('[data-prueba="recorrido"]', "data-paso"))
    pg.click("#rec-siguiente")
    pg.wait_for_function(f"document.querySelector('[data-prueba=\"recorrido\"]')?.dataset.paso === '{k + 1}'")
    pg.wait_for_timeout(350)   # la tarjeta y el foco se deslizan 0.25 s


def _sesion(nav, url, ancho, alto, sufijo):
    pg = nav.new_page(viewport={"width": ancho, "height": alto}, device_scale_factor=1)
    pg.goto(url, wait_until="domcontentloaded")
    _esperar(pg, "listo")
    pg.wait_for_selector('[data-prueba="recorrido"]')     # se abre solo la primera vez
    pg.wait_for_timeout(1500)
    _captura(pg, DOCS / "capturas" / f"recorrido-{sufijo}.png")
    # Recorrido hasta «Cómo leer el mapa», con una simulación real frente a Cancún.
    _siguiente(pg)
    _siguiente(pg)
    pg.mouse.click(*_punto(pg, 21.12, -86.60))
    _siguiente(pg)
    _siguiente(pg)
    _siguiente(pg)
    pg.click("#btn-simular")
    pg.wait_for_function("window.pms.estado === 'resultado'", timeout=60_000)
    _siguiente(pg)
    pg.wait_for_timeout(1200)
    _captura(pg, DOCS / "capturas" / f"recorrido-mapa-{sufijo}.png")
    pg.click("#rec-saltar")
    # Vista de resultado con hover
    pg.eval_on_selector("#lt-slider", "e => { e.value = 12; e.dispatchEvent(new Event('input')); }")
    lat, lon = pg.evaluate("() => window.pms.sim.reg.resultados.series.centroide[12].slice().reverse()")
    x, y = _punto(pg, lat, lon + 0.18)
    pg.mouse.move(x, y)
    pg.wait_for_selector("#tooltip:not([hidden])")
    pg.wait_for_timeout(800)
    _captura(pg, DOCS / "capturas" / f"resultado-{sufijo}.png")
    pg.mouse.move(5, alto - 5)
    pg.click('#pasos [data-paso="1"]')
    pg.wait_for_timeout(500)
    _captura(pg, DOCS / "capturas" / f"listo-{sufijo}.png")
    pg.close()


def principal() -> int:
    if not (DIR_SEMAR / ARCHIVO_OLEAJE).is_file():
        print(f"Falta {ARCHIVO_OLEAJE} en {DIR_SEMAR} (ver data/semar/README.md).")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        srv, url = _servidor(DIR_SEMAR, tmp / "sims")
        srv_e, url_e = _servidor(_datos_con_error(tmp / "semar_error"), tmp / "sims_error")
        with sync_playwright() as p:
            nav = _navegador(p)
            for ancho, alto in TAMANOS:
                sufijo = f"{ancho}x{alto}"
                _sesion(nav, url, ancho, alto, sufijo)
                pg = nav.new_page(viewport={"width": ancho, "height": alto}, device_scale_factor=1)
                pg.goto(url_e, wait_until="domcontentloaded")
                _esperar(pg, "error")
                pg.click("#estado")
                pg.wait_for_timeout(1200)
                _captura(pg, DOCS / "capturas" / f"error-{sufijo}.png")
                pg.close()
            nav.close()
        srv.should_exit = srv_e.should_exit = True
    for nombre in ("recorrido", "resultado", "listo", "error"):
        shutil.copy(DOCS / "capturas" / f"{nombre}-1366x768.png", DOCS / f"captura_{nombre}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
