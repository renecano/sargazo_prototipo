"""Genera las capturas de pantalla de docs/ con Playwright (Edge o Chromium).

Usa los datos reales de data/semar/ (no se publican en git; ver data/semar/README.md) y
guarda las simulaciones de la sesión en una carpeta temporal para no ensuciar tu historial:

    docs/captura_listo.png    datos validados, listo para simular
    docs/captura.png          resultado de 120 h frente a Cancún, pausado, con el hover
    docs/captura_error.png    estado «Error» con una copia de los datos a la que le falta
                              la hora +57 del oleaje (detalle desplegado)

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
from src.config import ARCHIVO_OLEAJE, ARCHIVO_VIENTO, DIR_SEMAR  # noqa: E402

DOCS = RAIZ / "docs"


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
    for k in range(intentos):
        try:
            pg.screenshot(path=str(ruta), timeout=45_000)
            print(f"[ok] {ruta.relative_to(RAIZ)}")
            return
        except Exception as e:  # noqa: BLE001
            print(f"[reintento {k + 1}] {ruta.name}: {str(e).splitlines()[0]}")
    raise RuntimeError(f"No se pudo capturar {ruta.name}")


def _simular(pg, lat, lon, horizonte=120, semilla=2026):
    pg.fill("#p-lat", f"{lat:.3f}")
    pg.fill("#p-lon", f"{lon:.3f}")
    pg.dispatch_event("#p-lon", "change")
    pg.eval_on_selector("#p-horizonte", f"e => {{ e.value = {horizonte}; e.dispatchEvent(new Event('input')); }}")
    pg.eval_on_selector("#p-semilla", f"e => {{ e.value = {semilla}; }}")  # sin desplegar «Opciones avanzadas»
    anterior = pg.evaluate("window.pms.sim ? window.pms.sim.id : ''")
    pg.click("#btn-simular")
    pg.wait_for_function(f"window.pms.estado === 'resultado' && window.pms.sim.id !== '{anterior}'", timeout=60_000)


def _datos_con_error(destino: Path) -> Path:
    """Copia de los datos reales sin el bloque +57 h del oleaje."""
    destino.mkdir(parents=True)
    shutil.copy(DIR_SEMAR / ARCHIVO_VIENTO, destino / ARCHIVO_VIENTO)
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


def principal() -> int:
    if not (DIR_SEMAR / ARCHIVO_VIENTO).is_file():
        print(f"Faltan los datos de SEMAR en {DIR_SEMAR} (ver data/semar/README.md).")
        return 1
    DOCS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        srv, url = _servidor(DIR_SEMAR, tmp / "sims")
        with sync_playwright() as p:
            nav = _navegador(p)
            pg = nav.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
            pg.goto(url, wait_until="domcontentloaded")
            _esperar(pg, "listo")
            pg.wait_for_timeout(1500)  # deja que carguen las teselas del mapa base
            _captura(pg, DOCS / "captura_listo.png")

            _simular(pg, 20.82, -86.80, horizonte=72, semilla=5)
            _simular(pg, 21.12, -86.66, horizonte=120, semilla=2026)
            pg.click("#btn-play")  # pausa la reproducción automática
            pg.eval_on_selector("#lt-slider", "e => { e.value = 12; e.dispatchEvent(new Event('input')); }")
            pg.click("#historial summary")
            lat, lon = pg.evaluate("() => window.pms.sim.reg.resultados.series.centroide[12].slice().reverse()")
            x, y = pg.evaluate("""([lat, lon]) => { const m = window.pmsMapa, p = m.latLngToContainerPoint([lat, lon]);
                const r = m.getContainer().getBoundingClientRect(); return [r.left + p.x + 150, r.top + p.y + 40]; }""", [lat, lon])
            pg.mouse.move(x, y)
            pg.wait_for_selector("#tooltip:not([hidden])")
            pg.wait_for_timeout(1200)
            _captura(pg, DOCS / "captura.png")
            nav.close()
        srv.should_exit = True

        srv, url = _servidor(_datos_con_error(tmp / "semar_error"), tmp / "sims_error")
        with sync_playwright() as p:
            nav = _navegador(p)
            pg = nav.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
            pg.goto(url, wait_until="domcontentloaded")
            _esperar(pg, "error")
            pg.click("#btn-detalle")
            pg.wait_for_timeout(1200)
            _captura(pg, DOCS / "captura_error.png")
            nav.close()
        srv.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
