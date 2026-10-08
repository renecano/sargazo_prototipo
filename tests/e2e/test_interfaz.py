"""Prueba de interfaz de punta a punta con Playwright (Edge o Chromium).

Levanta la app real sobre un conjunto sintético recién generado en una carpeta
temporal, y recorre lo que pide SEMAR: simulación de 120 h frente a Cancún,
animación con reproducir/pausa, paso por hora, hover de coordenadas, historial y
los estados Sin datos / Validando / Listo / Calculando / Resultado / Error.

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

from scripts.generar_datos_demo import escribir_conjunto, sembrar_errores  # noqa: E402
from src.api.app import crear_app  # noqa: E402

pytestmark = pytest.mark.e2e

CANCUN = (21.12, -86.66)
PATRON_COORD = re.compile(r"\d{2}\.\d{3}° N · \d{2}\.\d{3}° O")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _levantar(dir_datos, dir_sims):
    puerto = _puerto_libre()
    servidor = uvicorn.Server(uvicorn.Config(crear_app(dir_datos, dir_sims), host="127.0.0.1", port=puerto, log_level="warning"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(100):
        if servidor.started:
            break
        time.sleep(0.05)
    return servidor, f"http://127.0.0.1:{puerto}"


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("datos_e2e")
    escribir_conjunto(raiz / "demo")
    sembrar_errores(raiz / "demo", raiz / "demo_errores")
    return raiz


@pytest.fixture(scope="module")
def app_url(datos):
    servidor, url = _levantar(datos, datos / "simulations")
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
    pg.goto(app_url)
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


def huella_particulas(pg) -> str:
    return pg.evaluate("""() => {
        const s = document.querySelector('canvas[data-capa="particulas"]').toDataURL();
        let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
        return s.length + ':' + h;
    }""")


def hora(pg) -> int:
    return int(pg.text_content("#lt-h").strip().lstrip("+").split()[0])


def test_valida_los_120_archivos_y_queda_listo(pagina):
    esperar_estado(pagina, "listo")
    assert "120/120" in pagina.text_content("#estado-texto")
    resumen = pagina.text_content('[data-prueba="resumen-validacion"] summary')
    assert "verificaciones correctas" in resumen
    assert pagina.locator('[data-prueba="verificaciones"] li').count() == 9


def test_clic_en_el_mapa_fija_el_punto_de_liberacion(pagina):
    x, y = punto_en_pantalla(pagina, *CANCUN)
    pagina.mouse.click(x, y)
    lat = float(pagina.input_value("#p-lat"))
    lon = float(pagina.input_value("#p-lon"))
    assert abs(lat - CANCUN[0]) < 0.02 and abs(lon - CANCUN[1]) < 0.02
    assert pagina.is_hidden("#aviso-punto")


def test_simulacion_de_120_h_frente_a_cancun(pagina):
    pagina.fill("#p-lat", f"{CANCUN[0]:.3f}")
    pagina.fill("#p-lon", f"{CANCUN[1]:.3f}")
    pagina.dispatch_event("#p-lon", "change")
    pagina.eval_on_selector("#p-horizonte", "e => { e.value = 120; e.dispatchEvent(new Event('input')); }")
    pagina.click("#btn-simular")
    esperar_estado(pagina, "resultado")
    assert pagina.get_attribute("#lt-slider", "max") == "120"
    assert pagina.is_visible("#resultado")
    assert pagina.locator('[data-prueba="kpis"] .kpi').count() == 3
    assert pagina.evaluate("window.pms.sim.H") == 120
    assert pagina.locator("#lista-hist li[data-id]").count() == 1


def test_la_animacion_avanza_y_la_pausa_conserva_hora_y_posicion(pagina):
    pagina.wait_for_function("window.pms.hora >= 3", timeout=10_000)  # se reproduce sola al terminar
    pagina.click("#btn-play")  # pausa
    assert not pagina.evaluate("window.pms.reproduciendo")
    h1, f1 = hora(pagina), huella_particulas(pagina)
    time.sleep(1.5)
    assert hora(pagina) == h1
    assert huella_particulas(pagina) == f1
    pagina.click("#btn-play")  # reanuda
    pagina.wait_for_function(f"window.pms.hora > {h1}", timeout=10_000)
    pagina.click("#btn-play")
    assert hora(pagina) > h1


def test_paso_adelante_y_atras_por_hora(pagina):
    pagina.eval_on_selector("#lt-slider", "e => { e.value = 48; e.dispatchEvent(new Event('input')); }")
    assert hora(pagina) == 48
    pagina.click("#btn-adelante")
    assert hora(pagina) == 49
    pagina.click("#btn-atras")
    pagina.click("#btn-atras")
    assert hora(pagina) == 47
    assert "UTC" in pagina.text_content("#lt-utc")
    assert "Cancún (UTC−5)" in pagina.text_content("#lt-local")


def test_hover_muestra_coordenadas_y_valores_de_malla(pagina):
    lat, lon = pagina.evaluate("() => window.pms.sim.reg.resultados.series.centroide[window.pms.hora].slice().reverse()")
    x, y = punto_en_pantalla(pagina, lat, lon)
    pagina.mouse.move(x, y)
    pagina.wait_for_selector("#tooltip:not([hidden])")
    texto = pagina.text_content("#tooltip")
    assert PATRON_COORD.search(texto), texto
    assert "Viento" in texto and "m/s" in texto and "desde" in texto
    assert "Corriente" in texto
    assert "Partículas en esta celda" in texto or "Sin partículas" in texto


def test_historial_guarda_y_reabre(pagina):
    primera = pagina.evaluate("window.pms.sim.id")
    pagina.fill("#p-semilla", "7")
    pagina.click("#btn-simular")
    pagina.wait_for_function(f"window.pms.sim && window.pms.sim.id !== '{primera}' && window.pms.estado === 'resultado'", timeout=60_000)
    pagina.wait_for_function("document.querySelectorAll('#lista-hist li[data-id]').length === 2", timeout=5_000)
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
    assert "tierra" in pagina.text_content('[data-prueba="caja-error"]')
    pagina.click("#estado-acciones button")
    assert estado(pagina) == "resultado"


def test_conjunto_con_errores_muestra_estado_error(pagina):
    pagina.select_option("#conjunto", "demo_errores")
    esperar_estado(pagina, "error")
    caja = pagina.text_content('[data-prueba="caja-error"]')
    assert "salidadatos_2026100309.txt" in caja  # la hora +57 faltante
    detalle = pagina.text_content("#estado-detalle")
    assert "LAT" in detalle or "Latitud" in detalle
    assert "WindsfcDir" in detalle
    assert pagina.is_visible("#velo")
    assert pagina.is_disabled("#btn-simular")
    pagina.select_option("#conjunto", "demo")
    esperar_estado(pagina, "listo")


def test_sin_errores_de_javascript(pagina):
    assert pagina.errores == []


def test_estado_sin_datos(navegador, tmp_path):
    servidor, url = _levantar(tmp_path, tmp_path / "simulations")
    try:
        pg = navegador.new_page(viewport={"width": 1400, "height": 850})
        pg.goto(url)
        esperar_estado(pg, "sin-datos", timeout=15_000)
        assert "generar_datos_demo.py" in pg.text_content("#velo")
        assert pg.is_disabled("#btn-simular")
        pg.close()
    finally:
        servidor.should_exit = True
