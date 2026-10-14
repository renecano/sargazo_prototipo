"""Prueba de interfaz de punta a punta con Playwright (Edge o Chromium).

Levanta la app real sobre un fixture en el formato de SEMAR (dominio completo, valores
sintéticos) generado en una carpeta temporal y recorre lo que pide SEMAR: validación,
clic para liberar, simulación de 120 h frente a Cancún, pausa que conserva hora y
posición, hover con viento y ola, historial, punto en tierra, datos inválidos y sin datos.

    pytest -m e2e
"""
from __future__ import annotations

import re
import socket
import threading
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

from scripts.generar_fixtures import crear_fixture  # noqa: E402
from src.api.app import crear_app  # noqa: E402
from src.config import ARCHIVO_VIENTO  # noqa: E402
from tests.conftest import editar_lineas  # noqa: E402

pytestmark = pytest.mark.e2e

CANCUN = (21.12, -86.66)
PATRON_COORD = re.compile(r"\d{2}\.\d{3}° N · \d{2}\.\d{3}° O")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _levantar(dir_semar, dir_sims):
    puerto = _puerto_libre()
    servidor = uvicorn.Server(uvicorn.Config(crear_app(dir_semar, dir_sims), host="127.0.0.1", port=puerto, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True).start()
    for _ in range(200):
        if servidor.started:
            break
        time.sleep(0.05)
    return servidor, f"http://127.0.0.1:{puerto}"


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    return crear_fixture(tmp_path_factory.mktemp("e2e") / "semar", completo=True)


@pytest.fixture(scope="module")
def app_url(datos, tmp_path_factory):
    servidor, url = _levantar(datos, tmp_path_factory.mktemp("sims"))
    yield url
    servidor.should_exit = True


@pytest.fixture(scope="module")
def navegador():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001 — sin Edge, se usa el Chromium de Playwright
            b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def pagina(navegador, app_url):
    pg = navegador.new_page(viewport={"width": 1600, "height": 900})
    errores = []
    pg.on("pageerror", lambda e: errores.append(str(e)))
    pg.goto(app_url, wait_until="domcontentloaded")
    pg.errores = errores
    yield pg
    pg.close()


def estado(pg) -> str:
    return pg.get_attribute("#estado", "data-estado")


def esperar_estado(pg, nombre, timeout=60_000):
    pg.wait_for_function(f"document.getElementById('estado').dataset.estado === '{nombre}'", timeout=timeout)


def punto_en_pantalla(pg, lat, lon):
    return pg.evaluate("""([lat, lon]) => {
        const m = window.pmsMapa, p = m.latLngToContainerPoint([lat, lon]);
        const r = m.getContainer().getBoundingClientRect();
        return [r.left + p.x, r.top + p.y];
    }""", [lat, lon])


def huella_canvas(pg, capa: str) -> str:
    return pg.evaluate("""(capa) => {
        const s = document.querySelector(`canvas[data-capa="${capa}"]`).toDataURL();
        let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
        return s.length + ':' + h;
    }""", capa)


def hora(pg) -> int:
    return int(pg.text_content("#lt-h").strip().lstrip("+").split()[0])


def test_valida_los_datos_y_queda_listo(pagina):
    esperar_estado(pagina, "listo")
    assert pagina.text_content("#fuente") == "Datos SEMAR · viento 19 ago 2026 00 UTC (fijo)"
    assert pagina.text_content("#aviso-modelo") == "Pronóstico probabilístico; viento fijo de t = 0; sin corrientes."
    # El detalle de validación está plegado y se abre con un clic (hay advertencias).
    assert pagina.is_hidden("#estado-detalle")
    pagina.click("#btn-detalle")
    detalle = pagina.text_content("#estado-detalle")
    assert "una sola hora" in detalle and "idénticos" in detalle and "u_c = 0" in detalle
    pagina.click("#btn-detalle")
    assert pagina.is_hidden("#estado-detalle")


def test_interfaz_minima(pagina):
    assert pagina.locator(".leyenda li").count() <= 4
    assert pagina.locator("#conjunto").count() == 0, "ya no hay selector de conjunto de datos"
    assert pagina.locator("#lt-vel").count() == 0, "la velocidad de reproducción es fija"
    assert pagina.locator("input[type=checkbox]").count() == 1, "solo queda el interruptor «Mostrar viento»"
    assert pagina.get_attribute("#avanzadas", "open") is None, "opciones avanzadas plegadas por defecto"
    assert pagina.get_attribute("#historial", "open") is None


def test_flechas_de_viento_estaticas_y_ocultables(pagina):
    f1 = huella_canvas(pagina, "viento")
    time.sleep(0.6)
    assert huella_canvas(pagina, "viento") == f1, "las flechas no se animan"
    pagina.uncheck("#ver-viento")
    assert huella_canvas(pagina, "viento") != f1
    pagina.check("#ver-viento")
    assert huella_canvas(pagina, "viento") == f1


def test_clic_en_el_mapa_fija_el_punto_de_liberacion(pagina):
    x, y = punto_en_pantalla(pagina, *CANCUN)
    pagina.mouse.click(x, y)
    lat, lon = float(pagina.input_value("#p-lat")), float(pagina.input_value("#p-lon"))
    assert abs(lat - CANCUN[0]) < 0.02 and abs(lon - CANCUN[1]) < 0.02
    assert pagina.is_hidden("#aviso-punto")


def test_simulacion_de_120_h_frente_a_cancun(pagina):
    pagina.fill("#p-lat", f"{CANCUN[0]:.3f}")
    pagina.fill("#p-lon", f"{CANCUN[1]:.3f}")
    pagina.dispatch_event("#p-lon", "change")
    assert pagina.input_value("#p-horizonte") == "120"
    pagina.click("#btn-simular")
    esperar_estado(pagina, "resultado")
    assert pagina.get_attribute("#lt-slider", "max") == "120"
    assert pagina.is_visible("#resultado")
    assert "Varadas al final" in pagina.text_content("#resultado")
    assert "Radio P90 a +120 h" in pagina.text_content("#resultado")
    assert pagina.locator('[data-prueba="arribos"] li').count() <= 3
    assert pagina.evaluate("window.pms.sim.H") == 120
    assert pagina.locator("#lista-hist li[data-id]").count() == 1


def test_la_pausa_conserva_hora_y_posicion(pagina):
    pagina.wait_for_function("window.pms.hora >= 3", timeout=10_000)  # se reproduce sola al terminar
    pagina.click("#btn-play")
    assert not pagina.evaluate("window.pms.reproduciendo")
    h1, f1 = hora(pagina), huella_canvas(pagina, "particulas")
    time.sleep(1.5)
    assert hora(pagina) == h1 and huella_canvas(pagina, "particulas") == f1
    pagina.click("#btn-play")
    pagina.wait_for_function(f"window.pms.hora > {h1}", timeout=10_000)
    pagina.keyboard.press("Space")
    assert not pagina.evaluate("window.pms.reproduciendo")


def test_teclas_y_hora_utc_y_cancun(pagina):
    pagina.eval_on_selector("#lt-slider", "e => { e.value = 48; e.dispatchEvent(new Event('input')); }")
    pagina.mouse.click(5, 890)  # quita el foco de los campos sin tocar el mapa
    pagina.keyboard.press("ArrowRight")
    assert hora(pagina) == 49
    pagina.keyboard.press("ArrowLeft")
    pagina.keyboard.press("ArrowLeft")
    assert hora(pagina) == 47
    assert pagina.text_content("#lt-utc").endswith("23:00 UTC")       # 19 ago 00 UTC + 47 h
    assert "18:00 Cancún (UTC−5)" in pagina.text_content("#lt-local")


def test_hover_muestra_coordenadas_viento_y_ola(pagina):
    x, y = punto_en_pantalla(pagina, 21.0, -86.3)  # mar abierto al este de Cancún
    pagina.mouse.move(x, y)
    pagina.wait_for_selector("#tooltip:not([hidden])")
    texto = pagina.text_content("#tooltip")
    assert PATRON_COORD.search(texto), texto
    assert re.search(r"Viento\d+\.\d m/s desde \d+° \(\w+\)", texto), texto
    assert re.search(r"Ola\d+\.\d m desde \d+° \(\w+\)", texto), texto
    assert "Partículas" not in texto, "el hover solo muestra coordenadas, viento y ola"


def test_historial_guarda_y_reabre(pagina):
    primera = pagina.evaluate("window.pms.sim.id")
    pagina.click("#avanzadas summary")
    pagina.fill("#p-semilla", "7")
    pagina.click("#btn-simular")
    pagina.wait_for_function(f"window.pms.sim && window.pms.sim.id !== '{primera}' && window.pms.estado === 'resultado'", timeout=60_000)
    pagina.wait_for_function("document.querySelectorAll('#lista-hist li[data-id]').length === 2", timeout=5_000)
    pagina.click("#historial summary")
    pagina.click(f'#lista-hist li[data-id="{primera}"] button')
    pagina.wait_for_function(f"window.pms.sim.id === '{primera}'", timeout=10_000)
    assert pagina.input_value("#p-semilla") == "2026"
    assert "activa" in pagina.get_attribute(f'#lista-hist li[data-id="{primera}"]', "class")


def test_punto_en_tierra_muestra_error_con_accion(pagina):
    pagina.fill("#p-lat", "20.500")
    pagina.fill("#p-lon", "-88.500")
    pagina.dispatch_event("#p-lon", "change")
    assert pagina.is_visible("#aviso-punto")
    pagina.click("#btn-simular")
    esperar_estado(pagina, "error")
    assert "tierra" in pagina.text_content("#estado-texto")
    pagina.click("#btn-detalle")
    assert "Acción" in pagina.text_content('[data-prueba="caja-error"]')
    pagina.click("#estado-detalle button")
    assert estado(pagina) == "resultado"


def test_sin_errores_de_javascript(pagina):
    assert pagina.errores == []


def test_datos_invalidos_muestran_error(navegador, tmp_path):
    malo = crear_fixture(tmp_path / "semar")
    editar_lineas(malo / ARCHIVO_VIENTO, lambda l: [l[0], "19AGO2026 00"] + l[2:])  # mes en español: ilegible
    servidor, url = _levantar(malo, tmp_path / "sims")
    try:
        pg = navegador.new_page(viewport={"width": 1400, "height": 850})
        pg.goto(url, wait_until="domcontentloaded")
        esperar_estado(pg, "error", timeout=20_000)
        assert "Error en los datos" in pg.text_content("#estado-texto")
        pg.click("#btn-detalle")
        caja = pg.text_content('[data-prueba="caja-error"]')
        assert ARCHIVO_VIENTO in caja and "Acción" in caja
        assert pg.is_visible("#velo") and pg.is_disabled("#btn-simular")
        pg.close()
    finally:
        servidor.should_exit = True


def test_estado_sin_datos(navegador, tmp_path):
    servidor, url = _levantar(tmp_path / "vacio", tmp_path / "sims")
    try:
        pg = navegador.new_page(viewport={"width": 1400, "height": 850})
        pg.goto(url, wait_until="domcontentloaded")
        esperar_estado(pg, "sin-datos", timeout=15_000)
        assert "data/semar/" in pg.text_content("#velo")
        assert pg.is_disabled("#btn-simular")
        pg.close()
    finally:
        servidor.should_exit = True
