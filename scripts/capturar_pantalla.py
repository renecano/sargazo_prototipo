"""Genera las capturas de pantalla de docs/ con Playwright (Edge o Chromium).

Levanta la app sobre data/ (requiere haber corrido generar_datos_demo.py), guarda las
simulaciones de la sesión en una carpeta temporal para no ensuciar tu historial, y
produce:

    docs/captura.png          resultado de 120 h frente a Cancún, pausado en +72 h, con hover
    docs/captura_listo.png    estado «Datos validados · listo para simular»
    docs/captura_error.png    estado «Error» con el conjunto de errores sembrados

Uso (PowerShell):
    python scripts/capturar_pantalla.py
"""
from __future__ import annotations

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
from src.config import DIR_DATOS  # noqa: E402

DOCS = RAIZ / "docs"


def _servidor(dir_sims: Path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(crear_app(DIR_DATOS, dir_sims), host="127.0.0.1", port=puerto, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return srv, f"http://127.0.0.1:{puerto}"


def _esperar(pg, estado, timeout=60_000):
    pg.wait_for_function(f"document.getElementById('estado').dataset.estado === '{estado}'", timeout=timeout)


def _simular(pg, lat, lon, horizonte=120, alpha=1.0, semilla=2026):
    pg.fill("#p-lat", f"{lat:.3f}")
    pg.fill("#p-lon", f"{lon:.3f}")
    pg.dispatch_event("#p-lon", "change")
    pg.eval_on_selector("#p-horizonte", f"e => {{ e.value = {horizonte}; e.dispatchEvent(new Event('input')); }}")
    pg.eval_on_selector("#p-alpha", f"e => {{ e.value = {alpha}; e.dispatchEvent(new Event('input')); }}")
    pg.fill("#p-semilla", str(semilla))
    anterior = pg.evaluate("window.pms.sim ? window.pms.sim.id : ''")
    pg.click("#btn-simular")
    pg.wait_for_function(f"window.pms.estado === 'resultado' && window.pms.sim.id !== '{anterior}'", timeout=60_000)


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


def principal() -> int:
    if not any((DIR_DATOS / "demo").glob("*.txt")):
        print("Primero genera los datos: python scripts/generar_datos_demo.py")
        return 1
    DOCS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        srv, url = _servidor(Path(tmp))
        with sync_playwright() as p:
            try:
                nav = p.chromium.launch(channel="msedge")
            except Exception:  # noqa: BLE001
                nav = p.chromium.launch()
            pg = nav.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
            pg.goto(url, wait_until="domcontentloaded")
            _esperar(pg, "listo")
            pg.wait_for_timeout(1500)  # deja que carguen las teselas del mapa base
            _captura(pg, DOCS / "captura_listo.png")

            _simular(pg, 18.75, -87.56, horizonte=72, alpha=2.0, semilla=11)
            _simular(pg, 20.25, -86.70, horizonte=96, alpha=1.0, semilla=5)
            _simular(pg, 21.12, -86.66, horizonte=120, alpha=1.0, semilla=2026)
            pg.click("#btn-play")  # pausa la reproducción automática
            pg.eval_on_selector("#lt-slider", "e => { e.value = 72; e.dispatchEvent(new Event('input')); }")
            lat, lon = pg.evaluate("() => window.pms.sim.reg.resultados.series.centroide[72].slice().reverse()")
            pg.wait_for_timeout(1500)
            punto = pg.evaluate("""([lat, lon]) => { const m = window.pmsMapa, p = m.latLngToContainerPoint([lat, lon]);
                const r = m.getContainer().getBoundingClientRect(); return [r.left + p.x + 12, r.top + p.y - 105]; }""", [lat, lon])
            pg.mouse.move(*punto)
            pg.wait_for_selector("#tooltip:not([hidden])")
            pg.eval_on_selector(".panel", "e => e.scrollTop = 0")
            pg.wait_for_timeout(800)
            _captura(pg, DOCS / "captura.png")

            pg.mouse.move(5, 5)
            pg.select_option("#conjunto", "demo_errores")
            _esperar(pg, "error")
            pg.eval_on_selector(".panel", "e => e.scrollTop = 0")
            pg.wait_for_timeout(800)
            _captura(pg, DOCS / "captura_error.png")
            nav.close()
        srv.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
