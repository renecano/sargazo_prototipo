"""Capturas de pantalla de la interfaz con Playwright (Edge o Chromium) para docs/.

Usa data/semar/dirmarea.txt y guarda las simulaciones de la sesión en una carpeta temporal.
Para cada tamaño (1366×768 y 1920×1080) produce en docs/capturas/:

    recorrido-<tamaño>.png    primer paso del recorrido guiado (se abre solo la primera vez)
    recorrido-mapa-<tamaño>.png  paso «Cómo leer el mapa» con una simulación real
    resultado-<tamaño>.png    120 h frente a Cancún, en pausa, con el cursor sobre una partícula
    arribos-<tamaño>.png      tras tocar un tramo de la tabla de arribos
    satelite-<tamaño>.png     mapa base de satélite con el panel «Mapa y capas» (necesita internet)
    listo-<tamaño>.png        datos validados, paso 1, carta completa
    error-<tamaño>.png        copia del archivo sin la hora +57 (detalle desplegado)
    resumen-a4.png            el resumen de una página, como se imprime

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
    pg.wait_for_function("window.pms.costa && window.pms.localidades")
    pg.wait_for_selector('[data-prueba="recorrido"]')     # se abre solo la primera vez
    pg.wait_for_timeout(1500)
    _captura(pg, DOCS / "capturas" / f"recorrido-{sufijo}.png")
    # Recorrido hasta «Cómo leer el mapa», con una simulación real frente a Cancún.
    for _ in range(3):
        _siguiente(pg)                                    # datos → carta y capas → fijar el punto
    pg.mouse.click(*_punto(pg, 21.12, -86.60))
    for _ in range(3):
        _siguiente(pg)                                    # horizonte → γ y K_h → simular
    pg.click("#btn-simular")
    pg.wait_for_function("window.pms.estado === 'resultado'", timeout=60_000)
    _siguiente(pg)
    pg.wait_for_timeout(1200)
    _captura(pg, DOCS / "capturas" / f"recorrido-mapa-{sufijo}.png")
    pg.click("#rec-saltar")
    # Resultado en pausa, con el cursor sobre una partícula (rapidez y rumbo).
    pg.evaluate("window.pmsDepurar.ponerHora(12.4)")
    pt = pg.evaluate("""() => { const s = window.pms.sim, p = [0, 0];
        for (let n = 0; n < s.N; n++) { if (s.estado(n, 12.4) !== 0) continue; s.pos(n, 12.4, p);
            const q = window.pmsMapa.latLngToContainerPoint([p[1], p[0]]);
            if (q.x > 520 && q.x < window.innerWidth - 420 && q.y > 140 && q.y < window.innerHeight - 330) return [q.x, q.y]; }
        return null; }""")
    if pt:
        pg.mouse.move(pt[0] + 1, pt[1] + 1)
        pg.wait_for_selector("#tooltip:not([hidden])")
    pg.wait_for_timeout(800)
    _captura(pg, DOCS / "capturas" / f"resultado-{sufijo}.png")
    pg.mouse.move(5, alto - 5)
    # Clic en el último tramo de la tabla de arribos: el mapa va a ese lugar y a esa hora.
    pg.locator("#resultado .arribo").last.click()
    pg.wait_for_timeout(1500)
    _captura(pg, DOCS / "capturas" / f"arribos-{sufijo}.png")
    # Mapa base de satélite, con el panel de capas abierto.
    pg.click("#btn-capas")
    pg.check('input[name="base"][value="satelite"]')
    try:
        pg.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001 — sin internet la captura sale con las teselas que haya
        pass
    pg.wait_for_timeout(1500)
    _captura(pg, DOCS / "capturas" / f"satelite-{sufijo}.png")
    pg.check('input[name="base"][value="carta"]')
    pg.click("#btn-capas")
    if sufijo == "1366x768":
        # Resumen de una página, tal como se imprime (A4 a 96 ppp).
        pg.evaluate("() => { window.print = () => {}; }")
        pg.evaluate("window.pmsDepurar.imprimirResumen()")
        pg.set_viewport_size({"width": 794, "height": 1123})
        pg.emulate_media(media="print")
        pg.wait_for_timeout(600)
        _captura(pg, DOCS / "capturas" / "resumen-a4.png")
        pg.emulate_media(media="screen")
        pg.set_viewport_size({"width": ancho, "height": alto})
    pg.click('#pasos [data-paso="1"]')
    pg.evaluate("window.pmsMapa.fitBounds([[16.92, -92.08], [23, -84.08]], { animate: false, paddingTopLeft: [360, 84], paddingBottomRight: [40, 96] })")
    pg.wait_for_timeout(900)
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
    for nombre in ("recorrido", "resultado", "arribos", "satelite", "listo", "error"):
        shutil.copy(DOCS / "capturas" / f"{nombre}-1366x768.png", DOCS / f"captura_{nombre}.png")
    shutil.copy(DOCS / "capturas" / "resumen-a4.png", DOCS / "captura_resumen.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
