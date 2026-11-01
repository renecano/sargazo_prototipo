"""Prueba de interfaz de punta a punta con Playwright (Edge o Chromium), versión 0.4.0.

Levanta la app real sobre un dirmarea.txt de fixture (dominio completo, formato real de
SEMAR, valores sintéticos) y recorre: recorrido guiado (Saltar, no reabrirse, completo),
los tres pasos, clic para liberar, simulación de 120 h frente a Cancún, pausa que conserva
hora y posición, teclas, hover con ola, historial, punto en tierra, datos inválidos, sin datos
y la página /validacion (enlace discreto en la leyenda, tabla y figuras).

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
from src.config import ARCHIVO_OLEAJE  # noqa: E402
from tests.conftest import editar_lineas  # noqa: E402

pytestmark = pytest.mark.e2e

CANCUN = (21.12, -86.60)
TIERRA = (20.50, -88.50)
PATRON_COORD = re.compile(r"\d{2}\.\d{3}° N · \d{2}\.\d{3}° O")
RECORRIDO = '[data-prueba="recorrido"]'


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
def contexto(navegador):
    """Un solo contexto (mismo localStorage) para las pruebas que comparten página."""
    ctx = navegador.new_context(viewport={"width": 1366, "height": 768})
    yield ctx
    ctx.close()


@pytest.fixture(scope="module")
def pagina(contexto, app_url):
    pg = contexto.new_page()
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
    return pg.evaluate("([lat, lon]) => { const p = window.pmsMapa.latLngToContainerPoint([lat, lon]); return [p.x, p.y]; }", [lat, lon])


def huella_canvas(pg, capa: str) -> str:
    return pg.evaluate("""(capa) => {
        const s = document.querySelector(`canvas[data-capa="${capa}"]`).toDataURL();
        let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
        return s.length + ':' + h;
    }""", capa)


def hora(pg) -> int:
    return int(pg.text_content("#lt-h").strip().lstrip("+").split()[0])


def paso_recorrido(pg) -> int:
    return int(pg.get_attribute(RECORRIDO, "data-paso"))


def siguiente(pg):
    k = paso_recorrido(pg)
    pg.click("#rec-siguiente")
    pg.wait_for_function(f"document.querySelector('{RECORRIDO}')?.dataset.paso === '{k + 1}'")
    pg.wait_for_timeout(300)


# --- Recorrido guiado: se abre la primera vez, «Saltar» y no se reabre ---------------------

def test_recorrido_se_abre_solo_la_primera_vez_y_saltar_lo_cierra(pagina):
    esperar_estado(pagina, "listo")
    pagina.wait_for_selector(RECORRIDO)
    assert pagina.text_content('[data-prueba="rec-contador"]') == "Paso 1 de 11"
    assert pagina.is_disabled("#rec-atras")
    pagina.click("#rec-saltar")
    assert pagina.locator(RECORRIDO).count() == 0
    pagina.reload(wait_until="domcontentloaded")
    esperar_estado(pagina, "listo")
    pagina.wait_for_timeout(800)
    assert pagina.locator(RECORRIDO).count() == 0, "no debe volver a abrirse solo"


def test_estado_en_una_linea_con_detalle_al_clic(pagina):
    assert "dirmarea.txt validado" in pagina.text_content("#estado-texto")
    assert pagina.is_hidden("#estado-detalle")
    pagina.click("#estado")
    assert "idénticos" in pagina.text_content("#estado-detalle")
    pagina.click("#estado")
    assert pagina.is_hidden("#estado-detalle")


def test_tres_pasos_y_resultado_deshabilitado_sin_simulacion(pagina):
    assert pagina.get_attribute('#pasos [data-paso="1"]', "aria-current") == "step"
    assert pagina.is_disabled('#pasos [data-paso="3"]')
    pagina.click('#pasos [data-paso="2"]')
    assert pagina.is_visible("#p-horizonte") and pagina.is_hidden("#p-lat")
    assert pagina.get_attribute("#avanzado", "open") is None, "«Avanzado» plegado por defecto"
    pagina.click("#avanzado summary")
    for campo in ("#p-radio", "#p-n", "#p-gamma", "#p-kh", "#p-semilla"):
        assert pagina.is_visible(campo)
    assert pagina.locator("#avanzado small").count() == 5, "una línea de explicación por parámetro"
    pagina.click("#avanzado summary")
    pagina.click('#hoja [data-ir="1"]')
    assert pagina.is_visible("#p-lat")


def test_clic_en_el_mar_fija_el_punto_y_el_radio(pagina):
    pagina.mouse.click(*punto_en_pantalla(pagina, *CANCUN))
    lat, lon = float(pagina.input_value("#p-lat")), float(pagina.input_value("#p-lon"))
    assert abs(lat - CANCUN[0]) < 0.03 and abs(lon - CANCUN[1]) < 0.03
    assert pagina.is_hidden("#aviso-punto")
    assert pagina.evaluate("document.querySelectorAll('.leaflet-overlay-pane path').length") >= 2, "círculo del radio y recuadro"


def test_flechas_de_oleaje_estaticas_y_ocultables(pagina):
    f1 = huella_canvas(pagina, "oleaje")
    time.sleep(0.6)
    assert huella_canvas(pagina, "oleaje") == f1, "las flechas no se animan"
    pagina.uncheck("#ver-oleaje")
    assert huella_canvas(pagina, "oleaje") != f1
    pagina.check("#ver-oleaje")
    assert huella_canvas(pagina, "oleaje") == f1


def test_simulacion_de_120_h_frente_a_cancun(pagina):
    pagina.click("#btn-a-ajustes")
    assert pagina.input_value("#p-horizonte") == "120"
    pagina.click("#btn-simular")
    esperar_estado(pagina, "resultado")
    assert pagina.get_attribute('#pasos [data-paso="3"]', "aria-current") == "step"
    texto = pagina.text_content("#resultado")
    assert "Varado al final (+120 h)" in texto and "Radio P90 a +120 h" in texto
    assert 1 <= pagina.locator('[data-prueba="arribos"] li').count() <= 3
    assert pagina.locator('[data-prueba="arribos"] .etq').first.text_content() in ("Alta", "Media", "Baja", "Muy baja")
    assert pagina.get_attribute("#lt-slider", "max") == "120"
    assert pagina.evaluate("window.pms.sim.reg.version_modelo") == "pms-browniano-0.3.0"


def test_la_pausa_conserva_hora_y_posicion(pagina):
    pagina.wait_for_function("window.pms.hora >= 3", timeout=10_000)   # se reproduce sola al terminar
    pagina.click("#btn-play")
    assert not pagina.evaluate("window.pms.reproduciendo")
    h1, f1 = hora(pagina), huella_canvas(pagina, "particulas")
    time.sleep(1.5)
    assert hora(pagina) == h1 and huella_canvas(pagina, "particulas") == f1
    pagina.click("#btn-play")
    pagina.wait_for_function(f"window.pms.hora > {h1}", timeout=10_000)
    pagina.mouse.click(683, 760)          # quita el foco del botón sin tocar el mapa
    pagina.keyboard.press("Space")
    assert not pagina.evaluate("window.pms.reproduciendo")


def test_teclas_y_hora_utc_y_cancun(pagina):
    pagina.eval_on_selector("#lt-slider", "e => { e.value = 48; e.dispatchEvent(new Event('input')); }")
    pagina.mouse.click(683, 760)
    pagina.keyboard.press("ArrowRight")
    assert hora(pagina) == 49
    pagina.keyboard.press("ArrowLeft")
    pagina.keyboard.press("ArrowLeft")
    assert hora(pagina) == 47
    assert pagina.text_content("#lt-utc").endswith("23:00 UTC")          # 01 oct 00 UTC + 47 h
    assert "18:00 Cancún (UTC−5)" in pagina.text_content("#lt-local")


def test_hover_muestra_coordenadas_y_ola(pagina):
    pagina.mouse.move(*punto_en_pantalla(pagina, 21.0, -86.30))
    pagina.wait_for_selector("#tooltip:not([hidden])")
    texto = pagina.text_content("#tooltip")
    assert PATRON_COORD.search(texto), texto
    assert re.search(r"Ola \d+\.\d{2} m · desde \d+° \(\w+\)", texto), texto
    pagina.mouse.move(*punto_en_pantalla(pagina, 21.16, -86.86))     # tierra: ciudad de Cancún
    pagina.wait_for_timeout(300)
    assert "sin dato" in pagina.text_content("#tooltip")


def test_historial_guarda_y_reabre(pagina):
    primera = pagina.evaluate("window.pms.sim.id")
    pagina.click('#pasos [data-paso="2"]')
    pagina.click("#avanzado summary")
    pagina.fill("#p-semilla", "7")
    pagina.click("#btn-simular")
    pagina.wait_for_function(f"window.pms.sim && window.pms.sim.id !== '{primera}' && window.pms.estado === 'resultado'", timeout=60_000)
    assert pagina.is_hidden("#historial"), "el historial está plegado"
    pagina.click("#btn-historial")
    pagina.wait_for_function("document.querySelectorAll('#lista-hist li[data-id]').length === 2", timeout=5_000)
    pagina.click(f'#lista-hist li[data-id="{primera}"] button')
    pagina.wait_for_function(f"window.pms.sim.id === '{primera}'", timeout=10_000)
    assert pagina.input_value("#p-semilla") == "2026"
    assert pagina.is_hidden("#historial")


def test_punto_en_tierra_muestra_error_con_accion(pagina):
    pagina.click('#pasos [data-paso="1"]')
    pagina.fill("#p-lat", f"{TIERRA[0]:.3f}")
    pagina.fill("#p-lon", f"{TIERRA[1]:.3f}")
    pagina.dispatch_event("#p-lon", "change")
    assert "tierra" in pagina.text_content("#aviso-punto")
    pagina.click('#pasos [data-paso="2"]')
    pagina.click("#btn-simular")
    esperar_estado(pagina, "error")
    assert "tierra" in pagina.text_content("#estado-texto")
    pagina.click("#estado")
    assert "Acción" in pagina.text_content('[data-prueba="caja-error"]')


def test_sin_errores_de_javascript(pagina):
    assert pagina.errores == []


# --- Recorrido guiado completo, en un navegador «nuevo» -----------------------------------------

def test_recorrido_guiado_completo(navegador, app_url):
    ctx = navegador.new_context(viewport={"width": 1366, "height": 768})
    pg = ctx.new_page()
    errores = []
    pg.on("pageerror", lambda e: errores.append(str(e)))
    pg.goto(app_url, wait_until="domcontentloaded")
    esperar_estado(pg, "listo")
    pg.wait_for_selector(RECORRIDO)
    siguiente(pg)                                                     # 2: datos y oleaje
    assert "dirmarea.txt" in pg.text_content(RECORRIDO)
    siguiente(pg)                                                     # 3: fijar el punto (espera el clic)
    assert pg.is_disabled("#rec-siguiente")
    pg.mouse.click(*punto_en_pantalla(pg, *CANCUN))
    pg.wait_for_function("!document.getElementById('rec-siguiente').disabled")
    assert "Punto fijado" in pg.text_content("#rec-espera")
    siguiente(pg)                                                     # 4: horizonte
    assert pg.is_visible("#campo-horizonte")
    siguiente(pg)                                                     # 5: γ y K_h
    assert pg.get_attribute("#avanzado", "open") is not None
    siguiente(pg)                                                     # 6: simular (espera el resultado)
    assert pg.is_disabled("#rec-siguiente")
    pg.click("#btn-simular")
    pg.wait_for_function("!document.getElementById('rec-siguiente').disabled", timeout=60_000)
    assert "Simulación lista" in pg.text_content("#rec-espera")
    for esperado in ("Cómo leer el mapa", "línea de tiempo", "resultado", "historial", "Listo"):
        siguiente(pg)
        assert esperado.lower() in pg.text_content(f"{RECORRIDO} h2").lower()
    assert pg.text_content('[data-prueba="rec-contador"]') == "Paso 11 de 11"
    pg.click("#rec-atras")
    assert paso_recorrido(pg) == 10
    siguiente(pg)
    pg.click("#rec-siguiente")                                        # «Terminar»
    assert pg.locator(RECORRIDO).count() == 0
    assert pg.evaluate("localStorage.getItem('pms.recorrido.visto.v3')") == "1"
    pg.click("#btn-recorrido")                                        # siempre disponible
    pg.wait_for_selector(RECORRIDO)
    pg.keyboard.press("Escape")
    assert pg.locator(RECORRIDO).count() == 0
    assert errores == []
    ctx.close()


# --- Datos inválidos y sin datos ------------------------------------------------------------

def test_datos_invalidos_muestran_error(navegador, tmp_path):
    malo = crear_fixture(tmp_path / "semar")
    editar_lineas(malo / ARCHIVO_OLEAJE, lambda l: [l[0], "01OCTU2026 00 0"] + l[2:])   # fecha ilegible
    servidor, url = _levantar(malo, tmp_path / "sims")
    try:
        ctx = navegador.new_context(viewport={"width": 1366, "height": 768})
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded")
        esperar_estado(pg, "error", timeout=20_000)
        assert "Error en los datos" in pg.text_content("#estado-texto")
        assert pg.is_visible("#velo") and ARCHIVO_OLEAJE in pg.text_content("#velo")
        assert "Acción" in pg.text_content("#velo")
        pg.click("#estado")                                            # el velo no tapa el estado
        assert pg.is_visible("#estado-detalle")
        assert pg.is_disabled("#btn-simular")
        assert pg.locator(RECORRIDO).count() == 0, "el recorrido no se abre si los datos no son válidos"
        ctx.close()
    finally:
        servidor.should_exit = True


def test_estado_sin_datos(navegador, tmp_path):
    servidor, url = _levantar(tmp_path / "vacio", tmp_path / "sims")
    try:
        ctx = navegador.new_context(viewport={"width": 1366, "height": 768})
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded")
        esperar_estado(pg, "sin-datos", timeout=15_000)
        assert "data/semar/" in pg.text_content("#velo")
        assert pg.is_disabled("#btn-simular")
        ctx.close()
    finally:
        servidor.should_exit = True


def test_pagina_validacion_desde_el_enlace_de_la_leyenda(navegador, app_url):
    """El enlace discreto de la leyenda abre /validacion con conclusión, tabla y figuras."""
    from src.config import DIR_VALIDACION
    if not (DIR_VALIDACION / "index.html").is_file():
        pytest.skip("Aún no hay resultados de validación en docs/validacion/")
    ctx = navegador.new_context(viewport={"width": 1366, "height": 768})
    pagina = ctx.new_page()
    errores = []
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    pagina.add_init_script("localStorage.setItem('pms.recorrido.visto.v3', '1')")
    pagina.goto(app_url)
    enlace = pagina.locator(".validacion-enlace a")
    enlace.wait_for(state="visible")
    assert "Validación" in enlace.inner_text()
    enlace.click()
    pagina.wait_for_url(re.compile(r"/validacion$"))
    assert pagina.locator("h1").inner_text() == "¿El modelo se mueve como el sargazo real?"
    assert pagina.locator(".conclusion").inner_text().strip()
    filas = pagina.locator("table tbody tr")
    assert filas.count() >= 5 and "E0 Persistencia" in filas.first.inner_text()
    imagenes = pagina.locator("img")
    assert imagenes.count() >= 4
    for k in range(min(imagenes.count(), 6)):
        img = imagenes.nth(k)
        img.scroll_into_view_if_needed()
        pagina.wait_for_function("(i) => i.complete && i.naturalWidth > 0", arg=img.element_handle())
    ancho = pagina.evaluate("document.documentElement.scrollWidth")
    assert ancho <= 1366
    pagina.set_viewport_size({"width": 390, "height": 800})
    assert pagina.evaluate("document.documentElement.scrollWidth") <= 390
    pagina.locator(".volver").click()
    pagina.wait_for_url(re.compile(r"/$"))
    assert not errores
    ctx.close()
