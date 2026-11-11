"""Prueba de interfaz de punta a punta con Playwright (Edge o Chromium), versión 0.5.0.

Levanta la app real sobre un dirmarea.txt de fixture (dominio completo, formato real de
SEMAR, valores sintéticos) y recorre, en el orden de las observaciones de SEMAR:

  1. Tierra y mar: la carta dibuja la costa del modelo, la interfaz y el modelo usan la misma
     máscara y ninguna partícula se dibuja sobre tierra, tampoco entre horas.
  2. Interpolación: la ola del hover es la del modelo (también entre bloques de 3 h) y la
     animación avanza de forma continua entre horas guardadas.
  3. Oleaje animado, con interruptor y con «prefers-reduced-motion».
  4. Estelas, rapidez del conglomerado y rapidez de una partícula en pausa.
  5. Escalas: barra en km y millas náuticas con el zoom, flecha de ola de 1 m, densidad con
     unidades, línea de tiempo con fechas, saltos y velocidad, radio inicial a escala.
  6. Localidades sin encimarse y selector de mapa base con atribuciones.
  7. Interfaz limpia: lo secundario, bajo «Ver detalle».

y además la tabla de arribos, la exportación (imagen y resumen de una página), el recorrido
guiado completo, el historial, los errores y la página /validacion.

    pytest -m e2e
    pytest -m e2e --url-base https://<despliegue>      # contra un servidor ya desplegado

Contra un servidor externo las simulaciones de prueba quedan en su historial.
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
PATRON_GM = re.compile(r"\d{2}° \d{2}\.\d{2}′ N · \d{3}° \d{2}\.\d{2}′ O")
PATRON_FECHA = re.compile(r"(lun|mar|mié|jue|vie|sáb|dom) \d{2} \w{3} · \d{2}:00")
RECORRIDO = '[data-prueba="recorrido"]'
CLAVE_VISTO = "pms.recorrido.visto.v4"
PASOS_RECORRIDO = 14
VISTA = {"width": 1366, "height": 768}


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
def url_externa(request):
    url = request.config.getoption("--url-base")
    return url.rstrip("/") if url else None


@pytest.fixture(scope="module")
def app_url(url_externa, tmp_path_factory):
    if url_externa:
        yield url_externa
        return
    datos = crear_fixture(tmp_path_factory.mktemp("e2e") / "semar", completo=True)
    servidor, url = _levantar(datos, tmp_path_factory.mktemp("sims"))
    yield url
    servidor.should_exit = True


def _solo_local(url_externa):
    if url_externa:
        pytest.skip("Necesita levantar un servidor local con datos propios; no aplica a --url-base")


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
    ctx = navegador.new_context(viewport=VISTA, accept_downloads=True)
    yield ctx
    ctx.close()


@pytest.fixture(scope="module")
def pagina(contexto, app_url):
    pg = contexto.new_page()
    errores, teselas = [], []
    pg.on("pageerror", lambda e: errores.append(str(e)))
    pg.on("request", lambda r: teselas.append(r.url) if ("tile.openstreetmap.org" in r.url or "tiles.maps.eox.at" in r.url) else None)
    pg.goto(app_url, wait_until="domcontentloaded")
    pg.errores, pg.teselas = errores, teselas
    yield pg
    pg.close()


def abrir(navegador, url, visto=True, **opciones):
    ctx = navegador.new_context(viewport=VISTA, **opciones)
    pg = ctx.new_page()
    pg.errores = []
    pg.on("pageerror", lambda e: pg.errores.append(str(e)))
    if visto:
        pg.add_init_script(f"localStorage.setItem('{CLAVE_VISTO}', '1')")
    pg.goto(url, wait_until="domcontentloaded")
    return ctx, pg


def esperar_estado(pg, nombre, timeout=60_000):
    pg.wait_for_function(f"document.getElementById('estado').dataset.estado === '{nombre}'", timeout=timeout)


def esperar_lista(pg):
    esperar_estado(pg, "listo")
    pg.wait_for_function("window.pms.costa && window.pms.localidades && window.pms.campos", timeout=30_000)


def punto_en_pantalla(pg, lat, lon):
    return pg.evaluate("([lat, lon]) => { const p = window.pmsMapa.latLngToContainerPoint([lat, lon]); return [p.x, p.y]; }", [lat, lon])


def huella_canvas(pg, capa: str) -> str:
    return pg.evaluate("""(capa) => {
        const s = document.querySelector(`canvas[data-capa="${capa}"]`).toDataURL();
        let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
        return s.length + ':' + h;
    }""", capa)


def hora(pg) -> int:
    """«Hora 49 de 120» → 49."""
    return int(pg.text_content("#lt-h").split()[1])


def poner_hora(pg, h):
    pg.evaluate("(h) => window.pmsDepurar.ponerHora(h)", h)


def pausar(pg):
    if pg.evaluate("window.pms.reproduciendo"):
        pg.click("#btn-play")
    assert not pg.evaluate("window.pms.reproduciendo")


def poner_zoom(pg, zoom, centro=None):
    pg.evaluate("([z, c]) => { const m = window.pmsMapa; m.setView(c || m.getCenter(), z, { animate: false }); }", [zoom, centro])
    pg.wait_for_function(f"window.pmsMapa.getZoom() === {zoom}")
    pg.wait_for_timeout(150)


def capas(pg, abierto: bool):
    """Abre o cierra «Mapa y capas» sin depender de cómo lo dejó la prueba anterior."""
    if pg.is_visible("#capas") != abierto:
        pg.click("#btn-capas")
    assert pg.is_visible("#capas") == abierto


def color_carta(pg, lat, lon):
    """Color (r, g, b) de la carta propia en un punto, leído de la tesela que lo contiene."""
    return pg.evaluate("""([lat, lon]) => {
        const m = window.pmsMapa, marco = m.getContainer().getBoundingClientRect();
        const p = m.latLngToContainerPoint([lat, lon]);
        for (const t of document.querySelectorAll('.leaflet-tile-pane canvas.leaflet-tile')) {
            const r = t.getBoundingClientRect();
            const x = p.x + marco.left - r.left, y = p.y + marco.top - r.top;
            if (x < 0 || y < 0 || x >= r.width || y >= r.height) continue;
            const d = t.getContext('2d').getImageData(Math.floor(x * t.width / r.width), Math.floor(y * t.height / r.height), 1, 1).data;
            return [d[0], d[1], d[2]];
        }
        return null;
    }""", [lat, lon])


def paso_recorrido(pg) -> int:
    return int(pg.get_attribute(RECORRIDO, "data-paso"))


def siguiente(pg):
    k = paso_recorrido(pg)
    pg.click("#rec-siguiente")
    pg.wait_for_function(f"document.querySelector('{RECORRIDO}')?.dataset.paso === '{k + 1}'")
    pg.wait_for_timeout(300)


MAR_CARTA, TIERRA_CARTA, COSTA_CARTA = [238, 241, 234], [227, 211, 168], [29, 53, 87]

# Para cada partícula varada a la vista: ¿hay tierra o línea de costa de la carta a 2 px o menos?
JS_VARADAS_SOBRE_TIERRA = """() => {
    const s = window.pms.sim, m = window.pmsMapa, marco = m.getContainer().getBoundingClientRect(), p = [0, 0];
    const teselas = [...document.querySelectorAll('.leaflet-tile-pane canvas.leaflet-tile')]
        .map((t) => ({ t, r: t.getBoundingClientRect(), g: t.getContext('2d', { willReadFrequently: true }) }));
    const esMar = (x, y) => {
        for (const { t, r, g } of teselas) {
            const a = x + marco.left - r.left, b = y + marco.top - r.top;
            if (a < 0 || b < 0 || a >= r.width || b >= r.height) continue;
            const d = g.getImageData(Math.floor(a * t.width / r.width), Math.floor(b * t.height / r.height), 1, 1).data;
            return d[0] === 238 && d[1] === 241 && d[2] === 234;
        }
        return true;
    };
    let varadas = 0, conTierra = 0;
    for (let n = 0; n < s.N; n++) {
        if (s.estado(n, s.H) !== 1) continue;
        s.pos(n, s.H, p);
        const q = m.latLngToContainerPoint([p[1], p[0]]);
        if (q.x < 3 || q.y < 3 || q.x > marco.width - 3 || q.y > marco.height - 3) continue;
        varadas++;
        let hay = false;
        for (let dx = -2; dx <= 2 && !hay; dx++) for (let dy = -2; dy <= 2 && !hay; dy++) hay = !esMar(q.x + dx, q.y + dy);
        if (hay) conTierra++;
    }
    return { varadas, conTierra };
}"""


# --- Recorrido guiado: se abre la primera vez, «Saltar» y no se reabre ---------------------

def test_recorrido_se_abre_solo_la_primera_vez_y_saltar_lo_cierra(pagina):
    esperar_lista(pagina)
    pagina.wait_for_selector(RECORRIDO)
    assert pagina.text_content('[data-prueba="rec-contador"]') == f"Paso 1 de {PASOS_RECORRIDO}"
    assert pagina.is_disabled("#rec-atras")
    pagina.click("#rec-saltar")
    assert pagina.locator(RECORRIDO).count() == 0
    pagina.reload(wait_until="domcontentloaded")
    esperar_lista(pagina)
    pagina.wait_for_timeout(800)
    assert pagina.locator(RECORRIDO).count() == 0, "no debe volver a abrirse solo"


def test_estado_en_una_linea_con_detalle_al_clic(pagina):
    assert "dirmarea.txt validado" in pagina.text_content("#estado-texto")
    assert pagina.is_hidden("#estado-detalle")
    pagina.click("#estado")
    assert "idénticos" in pagina.text_content("#estado-detalle")
    pagina.click("#estado")
    assert pagina.is_hidden("#estado-detalle")


# --- 7. Interfaz limpia -----------------------------------------------------------------------

def test_por_defecto_solo_lo_esencial(pagina):
    """Mapa, paso actual, línea de tiempo y una leyenda mínima. Lo demás, plegado."""
    assert pagina.locator(".rosa").count() == 0, "se quitó la rosa de los vientos"
    assert pagina.locator("#chip-oleaje").count() == 0, "el interruptor de oleaje vive en «Mapa y capas»"
    for oculto in ("#capas", "#historial", "#estado-detalle", "#ley-sim", "#lt-rapidez", "#velo"):
        assert pagina.is_hidden(oculto), oculto
    assert pagina.get_attribute("#ley-detalle", "open") is None, "el detalle de la leyenda está plegado"
    assert pagina.get_attribute("#avanzado", "open") is None
    visibles = pagina.evaluate("""() => [...document.querySelectorAll('.cabecera > *, .hoja, .leyenda, .linea-tiempo, .flotante')]
        .filter((n) => n.offsetParent !== null || getComputedStyle(n).position === 'fixed' && !n.hidden).map((n) => n.className)""")
    assert len(visibles) == 6, visibles           # marca, pasos, acciones, hoja, leyenda, línea de tiempo
    aviso = pagina.locator(".leyenda .aviso")
    assert "sin viento ni corrientes" in aviso.inner_text() and "Validación" in aviso.inner_text()
    assert pagina.evaluate("parseFloat(getComputedStyle(document.querySelector('.leyenda .aviso')).fontSize)") <= 11, "discreto"
    assert len(pagina.inner_text('.paso[data-paso="1"] .guia')) < 60, "una sola línea de guía"


def test_tres_pasos_y_resultado_deshabilitado_sin_simulacion(pagina):
    assert pagina.get_attribute('#pasos [data-paso="1"]', "aria-current") == "step"
    assert pagina.is_disabled('#pasos [data-paso="3"]')
    pagina.click('#pasos [data-paso="2"]')
    assert pagina.is_visible("#p-horizonte") and pagina.is_hidden("#p-lat")
    pagina.click("#avanzado summary")
    for campo in ("#p-radio", "#p-n", "#p-gamma", "#p-kh", "#p-semilla"):
        assert pagina.is_visible(campo)
    assert pagina.locator("#avanzado small").count() == 5, "una línea de explicación por parámetro"
    pagina.click("#avanzado summary")
    pagina.click('#hoja [data-ir="1"]')
    assert pagina.is_visible("#p-lat")


# --- 1. Tierra y mar: la carta, la interfaz y el modelo comparten la costa -------------------------

def test_la_carta_propia_dibuja_la_costa_del_modelo_sin_internet(pagina):
    assert pagina.evaluate("window.pms.base") == "carta"
    assert pagina.locator(".leaflet-tile-pane canvas.leaflet-tile").count() > 0
    assert pagina.teselas == [], "la carta por defecto no pide teselas a internet"
    assert color_carta(pagina, 20.0, -89.5) == TIERRA_CARTA, "interior de Yucatán"
    assert color_carta(pagina, 20.0, -85.5) == MAR_CARTA, "Caribe abierto"
    poner_zoom(pagina, 10, [21.19, -86.77])
    # Observación 1 de SEMAR: en la Bahía de Mujeres la costa anterior tenía «tierra».
    assert color_carta(pagina, 21.188, -86.768) == MAR_CARTA
    assert color_carta(pagina, 21.235, -86.737) != MAR_CARTA, "Isla Mujeres existe"
    assert color_carta(pagina, 21.16, -86.83) == TIERRA_CARTA, "centro de Cancún"


def test_la_interfaz_y_el_modelo_usan_la_misma_mascara(pagina):
    """Puntos a lo largo de la costa de Quintana Roo: tierra/mar idéntico en el navegador y en el modelo."""
    resultado = pagina.evaluate("""async () => {
        const fallos = [];
        let tierra = 0;
        for (let k = 0; k < 40; k++) {
            const lat = 18.3 + k * 0.08, lon = -87.9 + ((k * 37) % 23) * 0.05;
            const r = await (await fetch(`/api/ola?lon=${lon}&lat=${lat}&hora=0`)).json();
            const aqui = window.pmsDepurar.enTierra(lon, lat);
            tierra += aqui ? 1 : 0;
            if (aqui !== r.en_tierra) fallos.push([lat, lon, aqui, r.en_tierra]);
        }
        return { fallos, tierra };
    }""")
    assert resultado["fallos"] == []
    assert 5 < resultado["tierra"] < 35, "la muestra tiene tierra y mar"


def test_clic_en_el_mar_fija_el_punto_con_grados_y_minutos(pagina):
    poner_zoom(pagina, 9.5, [21.12, -86.53])
    pagina.mouse.click(*punto_en_pantalla(pagina, *CANCUN))
    lat, lon = float(pagina.input_value("#p-lat")), float(pagina.input_value("#p-lon"))
    assert abs(lat - CANCUN[0]) < 0.03 and abs(lon - CANCUN[1]) < 0.03
    assert pagina.is_hidden("#aviso-punto")
    assert PATRON_GM.fullmatch(pagina.text_content("#p-gm")), pagina.text_content("#p-gm")
    assert pagina.text_content("#p-gm").startswith("21° 0")
    # Clic sobre Isla Mujeres: es tierra del modelo y la interfaz lo dice antes de simular.
    pagina.mouse.click(*punto_en_pantalla(pagina, 21.235, -86.737))
    assert "tierra" in pagina.text_content("#aviso-punto")
    pagina.mouse.click(*punto_en_pantalla(pagina, *CANCUN))
    assert pagina.is_hidden("#aviso-punto")


def test_la_tierra_angosta_se_dibuja_y_lo_varado_queda_sobre_tierra_visible(navegador, app_url):
    """La barra de Isla Blanca (al norte de Cancún, 300 m en su parte más delgada) e Isla Contoy
    medían 1 o 2 píxeles y la carta las pintaba como una raya o las perdía: los varados parecían
    estar sobre el mar. Ahora la tierra angosta se ve en todos los zooms de trabajo y cada
    partícula varada tiene tierra o línea de costa a 2 píxeles o menos."""
    ctx, pg = abrir(navegador, app_url)
    try:
        esperar_lista(pg)
        # (lat, lon) sobre la barra de Isla Blanca, de sur a norte, y sobre Isla Contoy.
        franja = [(21.30, -86.820), (21.34, -86.7925), (21.36, -86.7915), (21.40, -86.7965), (21.42, -86.8215), (21.50, -86.7965)]
        for zoom in (9, 9.5, 10, 10.5, 11):
            poner_zoom(pg, zoom, [21.38, -86.90])
            pg.wait_for_timeout(250)
            for lat, lon in franja:
                vecinos = pg.evaluate("""([lat, lon]) => {
                    const m = window.pmsMapa, marco = m.getContainer().getBoundingClientRect(), p = m.latLngToContainerPoint([lat, lon]);
                    const colores = [];
                    for (const t of document.querySelectorAll('.leaflet-tile-pane canvas.leaflet-tile')) {
                        const r = t.getBoundingClientRect(), g = t.getContext('2d', { willReadFrequently: true });
                        for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) {
                            const a = p.x + dx + marco.left - r.left, b = p.y + dy + marco.top - r.top;
                            if (a < 0 || b < 0 || a >= r.width || b >= r.height) continue;
                            const d = g.getImageData(Math.floor(a * t.width / r.width), Math.floor(b * t.height / r.height), 1, 1).data;
                            colores.push([d[0], d[1], d[2]]);
                        }
                    }
                    return colores;
                }""", [lat, lon])
                assert TIERRA_CARTA in vecinos, f"zoom {zoom}: a 2 px de ({lat}, {lon}) hay relleno de tierra, no solo una raya"
            # En su parte más delgada (300 m) la franja lleva relleno y línea de costa a los lados.
            delgada = pg.evaluate("""() => {
                const m = window.pmsMapa, marco = m.getContainer().getBoundingClientRect(), p = m.latLngToContainerPoint([21.34, -86.7925]);
                const fila = [];
                for (let dx = -4; dx <= 4; dx++) for (const t of document.querySelectorAll('.leaflet-tile-pane canvas.leaflet-tile')) {
                    const r = t.getBoundingClientRect(), a = p.x + dx + marco.left - r.left, b = p.y + marco.top - r.top;
                    if (a < 0 || b < 0 || a >= r.width || b >= r.height) continue;
                    const d = t.getContext('2d', { willReadFrequently: true }).getImageData(Math.floor(a * t.width / r.width), Math.floor(b * t.height / r.height), 1, 1).data;
                    fila.push([d[0], d[1], d[2]]);
                }
                return fila;
            }""")
            assert TIERRA_CARTA in delgada and COSTA_CARTA in delgada and MAR_CARTA in delgada, f"zoom {zoom}: {delgada}"
        assert pg.evaluate("window.pmsDepurar.enTierra(-86.7925, 21.34)"), "y es tierra del modelo"
        # Simulación que vara justo ahí.
        pg.fill("#p-lat", "21.400")
        pg.fill("#p-lon", "-86.650")
        pg.dispatch_event("#p-lon", "change")
        assert pg.is_hidden("#aviso-punto")
        pg.click("#btn-a-ajustes")
        pg.click("#btn-simular")
        esperar_estado(pg, "resultado")
        pausar(pg)
        poner_hora(pg, 120)
        zonas = {a["zona"] for a in pg.evaluate("window.pms.sim.reg.resumen.arribos")}
        assert zonas & {"costa_mujeres", "contoy"}, zonas
        for zoom in (9, 10, 11):
            poner_zoom(pg, zoom, [21.38, -86.90])
            pg.wait_for_timeout(300)
            r = pg.evaluate(JS_VARADAS_SOBRE_TIERRA)
            assert r["varadas"] > 300 and r["conTierra"] == r["varadas"], f"zoom {zoom}: {r}"
        assert pg.errores == []
    finally:
        ctx.close()


# --- 5. Escalas ----------------------------------------------------------------------------------

def test_el_radio_inicial_esta_a_escala_del_mapa(pagina):
    for zoom in (9.5, 8):
        poner_zoom(pagina, zoom, [21.12, -86.53])
        ancho, metros_por_px = pagina.evaluate("""() => {
            const c = [...document.querySelectorAll('.leaflet-overlay-pane path')].find((p) => p.getAttribute('stroke-dasharray') === '4 4');
            return [c.getBoundingClientRect().width, window.pms.escala.metrosPorPx];
        }""")
        assert ancho == pytest.approx(2 * 5000 / metros_por_px, abs=2.5), f"círculo de 5 km de radio en zoom {zoom}"


def test_barra_de_escala_en_km_y_millas_nauticas_sigue_al_zoom(pagina):
    lecturas = []
    for zoom in (6.5, 8, 10.5):
        poner_zoom(pagina, zoom, [21.0, -87.0])
        d = pagina.evaluate("""() => {
            const m = window.pmsMapa, t = m.getSize();
            const real = m.distance(m.containerPointToLatLng([t.x / 2 - 100, t.y / 2]), m.containerPointToLatLng([t.x / 2 + 100, t.y / 2])) / 200;
            return { real, e: window.pms.escala, pxKm: document.getElementById('esc-km').getBoundingClientRect().width,
                     pxMn: document.getElementById('esc-mn').getBoundingClientRect().width,
                     km: document.getElementById('esc-km-t').textContent, mn: document.getElementById('esc-mn-t').textContent };
        }""")
        km, mn = float(d["km"].replace(" km", "").replace(" ", "")), float(d["mn"].replace(" MN", "").replace(" ", ""))
        assert d["km"].endswith(" km") and d["mn"].endswith(" MN")
        assert d["pxKm"] * d["real"] == pytest.approx(km * 1000, rel=0.03), f"la barra de {km} km mide lo que dice en zoom {zoom}"
        assert d["pxMn"] * d["real"] == pytest.approx(mn * 1852, rel=0.03), f"la barra de {mn} MN mide lo que dice en zoom {zoom}"
        assert 25 < d["pxKm"] <= 124 and 25 < d["pxMn"] <= 124
        assert str(km)[0] in "125" and str(mn)[0] in "125", "valores redondos"
        lecturas.append((km, mn))
    assert lecturas[0][0] > lecturas[1][0] > lecturas[2][0], "al acercar, la barra representa menos distancia"


# --- 3. Oleaje animado ---------------------------------------------------------------------------

def test_oleaje_animado_fluye_y_su_escala_vale_en_cualquier_zoom(pagina):
    poner_zoom(pagina, 8, [21.0, -86.5])
    assert pagina.evaluate("window.pmsDepurar.animando()") and pagina.is_checked("#ver-animar") is True
    f1 = huella_canvas(pagina, "oleaje")
    pagina.wait_for_timeout(500)
    assert huella_canvas(pagina, "oleaje") != f1, "los trazos se mueven"
    px = pagina.evaluate("window.pmsDepurar.constantes.PX_POR_METRO")
    assert pagina.get_attribute("#ref-ola-svg", "data-px") == str(px)
    assert pagina.evaluate("document.querySelector('#ref-ola-svg path').getTotalLength()") == pytest.approx(px, abs=0.01), \
        "la flecha «1 m» de la leyenda mide PX_POR_METRO"
    for zoom in (8, 10.5, 6.5):
        poner_zoom(pagina, zoom, [21.0, -86.5])
        pagina.wait_for_function("window.pms.flechas.length > 10")
        flechas = pagina.evaluate("window.pms.flechas")
        assert all(f["largo"] == pytest.approx(f["altura"] * px, rel=1e-9) for f in flechas), f"largo = altura × escala en zoom {zoom}"
        assert max(f["altura"] for f in flechas) > min(f["altura"] for f in flechas), "trazos de distinto tamaño según la altura"
    # Más altura, más rapidez: el trazo avanza en proporción a la altura de la ola.
    avance = pagina.evaluate("""() => {
        const o = window.pmsDepurar.oleaje; o.detener(); o.sembrar(); o.avanzar(0);
        const antes = o.trazos.map((t) => [t.x, t.y, t.vivo]);
        const c = o.capa, campos = window.pms.campos, m = new Float64Array(3);
        const alturas = o.trazos.map((t) => (campos.muestrear(c.lon(t.x), c.lat(t.y), window.pms.hora, m) ? m[0] : null));
        o.avanzar(0.05);
        const r = [];
        o.trazos.forEach((t, k) => { if (antes[k][2] && t.vivo && alturas[k] && t.edad > 0.05) r.push([Math.hypot(t.x - antes[k][0], t.y - antes[k][1]), alturas[k]]); });
        o.iniciar();
        return r;
    }""")
    assert len(avance) > 20
    razones = [d / h for d, h in avance]
    assert max(razones) == pytest.approx(min(razones), rel=0.02), "px por segundo proporcionales a la altura"
    assert "constante" in pagina.text_content("#nota-ola") and "idénticos" in pagina.text_content("#nota-ola")


def test_el_oleaje_se_puede_dejar_fijo_o_apagar(pagina):
    poner_zoom(pagina, 8, [21.0, -86.5])
    capas(pagina, True)
    assert pagina.is_visible("#capas")
    pagina.uncheck("#ver-animar")
    assert not pagina.evaluate("window.pmsDepurar.animando()")
    f1 = huella_canvas(pagina, "oleaje")
    pagina.wait_for_timeout(500)
    assert huella_canvas(pagina, "oleaje") == f1, "con la animación apagada las flechas no se mueven"
    nodos = pagina.evaluate("window.pms.flechas.map((f) => [(f.lon + 92.08) / 0.16, (f.lat - 16.92) / 0.16])")
    assert len(nodos) > 20 and all(abs(a - round(a)) < 1e-6 and abs(b - round(b)) < 1e-6 for a, b in nodos), "una flecha por nodo con dato"
    pagina.uncheck("#ver-oleaje")
    assert pagina.evaluate("window.pms.flechas.length") == 0 and pagina.is_hidden("#ref-ola") and pagina.is_hidden("#nota-ola")
    assert pagina.is_disabled("#ver-animar")
    vacio = huella_canvas(pagina, "oleaje")
    assert vacio != f1
    pagina.check("#ver-oleaje")
    assert huella_canvas(pagina, "oleaje") == f1
    pagina.check("#ver-animar")
    assert pagina.evaluate("window.pmsDepurar.animando()")
    pagina.keyboard.press("Escape")
    assert pagina.is_hidden("#capas"), "Escape cierra el panel aunque el foco esté en una casilla"


# --- 6. Localidades y mapa base --------------------------------------------------------------------

def _sin_encimarse(rotulos):
    for i, a in enumerate(rotulos):
        for b in rotulos[i + 1:]:
            if a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"]:
                return (a["nombre"], b["nombre"])
    return None


def test_localidades_aparecen_segun_el_zoom_y_no_se_enciman(pagina):
    pagina.evaluate("window.pmsMapa.fitBounds([[16.92, -92.08], [23, -84.08]], { animate: false, paddingTopLeft: [360, 84], paddingBottomRight: [40, 96] })")
    pagina.wait_for_timeout(300)
    lejos = pagina.evaluate("window.pms.rotulos")
    nombres = {r["nombre"] for r in lejos}
    assert {"Cancún", "Mérida", "Chetumal"} <= nombres, nombres
    assert all(r["rango"] == 1 for r in lejos), "de lejos solo las ciudades principales"
    assert _sin_encimarse(lejos) is None
    assert next(r for r in lejos if r["nombre"] == "Cancún")["puerto"] is True
    poner_zoom(pagina, 9, [20.75, -87.0])
    medio = pagina.evaluate("window.pms.rotulos")
    nombres = {r["nombre"] for r in medio}
    assert {"Cancún", "Isla Mujeres", "Puerto Morelos", "Playa del Carmen", "San Miguel de Cozumel", "Tulum"} <= nombres, nombres
    assert _sin_encimarse(medio) is None
    poner_zoom(pagina, 10.5, [21.2, -86.8])
    cerca = pagina.evaluate("window.pms.rotulos")
    assert any(r["rango"] >= 3 for r in cerca), "al acercar aparecen los poblados y cabos menores"
    assert _sin_encimarse(cerca) is None
    poner_zoom(pagina, 8.5, [18.9, -87.6])
    sur = {r["nombre"] for r in pagina.evaluate("window.pms.rotulos")}
    assert {"Mahahual", "Chetumal"} <= sur, sur
    capas(pagina, True)
    pagina.uncheck("#ver-localidades")
    assert pagina.evaluate("window.pms.rotulos.length") == 0
    pagina.check("#ver-localidades")
    assert pagina.evaluate("window.pms.rotulos.length") > 0
    capas(pagina, False)


def test_selector_de_mapa_base_con_atribuciones(pagina):
    atribucion = lambda: pagina.inner_text(".leaflet-control-attribution")   # noqa: E731
    assert "OpenStreetMap" in atribucion() and "Natural Earth" in atribucion()
    capas(pagina, True)
    pagina.check('input[name="base"][value="satelite"]')
    assert pagina.evaluate("document.body.dataset.base") == "satelite"
    pagina.wait_for_selector(".leaflet-layer.tesela-satelite", state="attached")
    pagina.wait_for_timeout(400)
    assert pagina.locator(".leaflet-tile-pane canvas.leaflet-tile").count() == 0, "la carta propia se retira"
    assert "Sentinel-2 cloudless 2016" in atribucion() and "EOX" in atribucion() and "CC BY 4.0" in atribucion()
    assert "OpenStreetMap" in atribucion(), "la costa y las localidades siguen siendo de OSM"
    assert any("tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/" in u for u in pagina.teselas), "capa 2016, la de licencia CC BY 4.0"
    # Sobre la imagen, las capas cambian a trazo claro y la leyenda muestra esos mismos colores.
    assert pagina.evaluate("getComputedStyle(document.getElementById('leyenda')).getPropertyValue('--ley-tinta').trim()") == "#fbf6ea"
    en_satelite = pagina.evaluate("""async () => { const { PALETAS } = await import('/static/js/paleta.js');
        const e = getComputedStyle(document.getElementById('leyenda'));
        return [e.getPropertyValue('--ley-zona').trim() === PALETAS.satelite.zona, e.getPropertyValue('--ley-varada').trim() === PALETAS.satelite.varada,
                document.querySelector('#ley-densidad i').style.background.includes('repeating-linear-gradient')]; }""")
    assert en_satelite == [True, True, True], "la leyenda usa los colores y la trama del mapa base activo"
    pagina.check('input[name="base"][value="calles"]')
    pagina.wait_for_selector(".leaflet-layer.tesela-calles", state="attached")
    assert pagina.locator(".leaflet-layer.tesela-satelite").count() == 0
    assert "mapa base © colaboradores de OpenStreetMap" in atribucion()
    pagina.check('input[name="base"][value="carta"]')
    pagina.wait_for_selector(".leaflet-tile-pane canvas.leaflet-tile", state="attached")
    assert pagina.locator(".leaflet-layer.tesela-calles").count() == 0 and "Natural Earth" in atribucion()
    assert pagina.evaluate("getComputedStyle(document.getElementById('leyenda')).getPropertyValue('--ley-tinta').trim()") == "#1d3557"
    capas(pagina, False)


# --- Simulación y tabla de arribos -----------------------------------------------------------------

def test_simulacion_de_120_h_frente_a_cancun(pagina):
    poner_zoom(pagina, 9.5, [21.12, -86.53])
    pagina.mouse.click(*punto_en_pantalla(pagina, *CANCUN))
    pagina.click("#btn-a-ajustes")
    assert pagina.input_value("#p-horizonte") == "120"
    pagina.click("#btn-simular")
    esperar_estado(pagina, "resultado")
    assert pagina.get_attribute('#pasos [data-paso="3"]', "aria-current") == "step"
    assert pagina.get_attribute("#lt-slider", "max") == "120"
    assert pagina.evaluate("window.pms.sim.reg.version_modelo") == "pms-browniano-0.4.0"
    assert pagina.is_visible("#ley-sim") and pagina.is_visible("#lt-rapidez")


def test_la_tabla_de_arribos_es_el_resultado_principal(pagina):
    titular = pagina.inner_text('[data-prueba="titular"]')
    assert titular.startswith("Primer arribo: ") and PATRON_FECHA.search(titular) and "de 120" in titular
    filas = pagina.locator('[data-prueba="arribos"] .arribo')
    arribos = pagina.evaluate("window.pms.sim.reg.resumen.arribos")
    assert filas.count() == len(arribos) >= 1
    assert [c.strip() for c in pagina.locator(".arribos-cab span").all_inner_texts()] == ["TRAMO DE COSTA", "PRIMER ARRIBO", "LLEGA", "RECORRE"]
    horas = [int(filas.nth(k).get_attribute("data-hora")) for k in range(filas.count())]
    assert horas == sorted(horas), "en orden cronológico: lo que llega primero, arriba"
    primera = filas.first.inner_text()
    assert PATRON_FECHA.search(primera) and "%" in primera and "km" in primera and "MN" in primera and f"hora {horas[0]}" in primera
    assert "Cancún" in pagina.inner_text('[data-prueba="arribos"]')
    assert pagina.get_attribute("#detalle-resultado", "open") is None, "lo demás, bajo «Ver detalle»"
    assert pagina.is_hidden('[data-prueba="varadas"]')
    pagina.click("#detalle-resultado summary")
    detalle = pagina.inner_text("#detalle-resultado")
    for esperado in ("Varado al final", "Radio P90", "Trayectoria central", "Rapidez media", "kn", "MN", "UTC", "pms-browniano-0.4.0"):
        assert esperado in detalle, esperado
    assert PATRON_GM.search(detalle), "la liberación también en grados y minutos"
    pagina.click("#detalle-resultado summary")


def test_clic_en_un_arribo_lleva_el_mapa_a_ese_tramo_y_a_esa_hora(pagina):
    pausar(pagina)
    arribos = sorted(pagina.evaluate("window.pms.sim.reg.resumen.arribos"), key=lambda a: a["primer_arribo_h"])
    objetivo = arribos[-1]
    fila = pagina.locator(f'.arribo[data-zona="{objetivo["zona"]}"]')
    fila.click()
    pagina.wait_for_timeout(500)
    assert pagina.evaluate("window.pms.hora") == objetivo["primer_arribo_h"]
    assert hora(pagina) == objetivo["primer_arribo_h"]
    assert fila.get_attribute("aria-selected") == "true" and pagina.evaluate("window.pms.arriboElegido") == objetivo["zona"]
    o, s, e, n = objetivo["limites"]
    dentro = pagina.evaluate("([o, s, e, n]) => window.pmsMapa.getBounds().contains([[s, o], [n, e]])", [o, s, e, n])
    assert dentro, "el tramo queda a la vista"
    x, y = punto_en_pantalla(pagina, *reversed(objetivo["punto_primer_arribo"]))
    assert 350 < x < 1366 and 70 < y < 700, "y fuera de los paneles"


# --- 2 y 4. Animación fluida, tierra, estelas y rapidez -----------------------------------------------

def test_la_animacion_avanza_entre_horas_y_la_pausa_conserva_el_instante(pagina):
    poner_hora(pagina, 0)
    pagina.click("#btn-play")
    vistas = set()
    for _ in range(12):
        vistas.add(pagina.evaluate("window.pms.hora"))
        pagina.wait_for_timeout(60)
    fraccionarias = [h for h in vistas if abs(h - round(h)) > 1e-3]
    assert len(fraccionarias) >= 6, f"la hora avanza de forma continua, no a saltos de 1 h: {sorted(vistas)}"
    pagina.click("#btn-play")
    assert not pagina.evaluate("window.pms.reproduciendo")
    assert pagina.evaluate("window.pms.dibujo.tramosEstela") == 6, "al pausar, las estelas se dibujan completas"
    h1, f1 = pagina.evaluate("window.pms.hora"), huella_canvas(pagina, "particulas")
    time.sleep(1.2)
    assert pagina.evaluate("window.pms.hora") == h1 and huella_canvas(pagina, "particulas") == f1
    # Dos instantes dentro de la misma hora se dibujan distinto: hay interpolación de posiciones.
    poner_hora(pagina, 10.2)
    a = huella_canvas(pagina, "particulas")
    poner_hora(pagina, 10.7)
    assert huella_canvas(pagina, "particulas") != a
    assert hora(pagina) == 10
    pagina.click("#btn-play")
    pagina.wait_for_function("window.pms.hora > 11", timeout=10_000)
    pagina.click(".marca h1")              # quita el foco del botón sin tocar el mapa
    pagina.keyboard.press("Space")
    assert not pagina.evaluate("window.pms.reproduciendo")


def test_ninguna_particula_se_dibuja_sobre_tierra_ni_entre_horas(pagina, url_externa):
    """Se recorre toda la simulación a cuartos de hora con la máscara del modelo."""
    r = pagina.evaluate("""() => {
        const d = window.pmsDepurar, s = window.pms.sim;
        let sobreTierra = 0, aFlote = 0, varadas = 0, cuadros = 0, rozan = 0;
        const q = [0, 0];
        for (let h = 0; h < s.H; h++) for (const f of [0, 0.25, 0.5, 0.75]) {
            d.ponerHora(h + f);
            sobreTierra += window.pms.dibujo.sobreTierra; aFlote += window.pms.dibujo.aFlote; cuadros++;
            // Sin la corrección: cuántas rectas entre horas guardadas rozan tierra por el redondeo.
            for (let n = 0; n < s.N; n++) if (s.estado(n, h + f) === 0) { s.pos(n, h + f, q); if (d.enTierra(q[0], q[1])) rozan++; }
        }
        d.ponerHora(s.H);
        const p = [0, 0];
        let varadasEnTierra = 0;
        for (let n = 0; n < s.N; n++) if (s.estado(n, s.H) === 1) { varadas++; s.pos(n, s.H, p); if (d.enTierra(p[0], p[1])) varadasEnTierra++; }
        return { sobreTierra, aFlote, cuadros, varadas, varadasEnTierra, rozan };
    }""")
    assert r["cuadros"] == 480 and r["aFlote"] > 10_000
    assert r["sobreTierra"] == 0, "ninguna partícula, a flote o varada, se dibuja sobre tierra en ningún cuadro"
    assert r["varadas"] > 500 and r["varadasEnTierra"] == 0, "las varadas quedan en el mar, pegadas a la costa"
    if not url_externa:      # con el archivo de prueba hay rectas que rozan tierra; con otros datos puede no haberlas
        assert r["rozan"] > 0, "el caso ejercita la corrección del redondeo de 22 m"


def test_estelas_por_rapidez_y_su_interruptor(pagina):
    poner_hora(pagina, 20.5)
    pagina.wait_for_timeout(500)           # el último cuadro se completa solo si venía simplificado
    assert pagina.evaluate("window.pms.dibujo.tramosEstela") == 6
    con = huella_canvas(pagina, "particulas")
    clases = pagina.evaluate("""() => {
        const s = window.pms.sim, v = [0, 0], c = [0, 0, 0];
        for (let n = 0; n < s.N; n++) { if (s.estado(n, 20.5) !== 0) continue; s.velocidad(n, 20.5, v); const kn = Math.hypot(v[0], v[1]) / 0.514444; c[kn < 0.2 ? 0 : kn < 0.4 ? 1 : 2]++; }
        return c;
    }""")
    assert all(k > 20 for k in clases), f"hay partículas lentas, medias y rápidas: el movimiento no es uniforme ({clases})"
    assert pagina.locator("#ley-estelas i").count() == 3
    # El color que se pinta es el de la paleta (púrpura), no un dorado parecido a la tierra.
    pintado = pagina.evaluate("""async () => {
        const { PALETAS } = await import('/static/js/paleta.js');
        const s = window.pms.sim, c = window.pmsDepurar.capas.particulas, dpr = window.devicePixelRatio || 1, p = [0, 0];
        const hex = (d) => '#' + [d[0], d[1], d[2]].map((v) => v.toString(16).padStart(2, '0')).join('');
        const vistos = {};
        for (let n = 0; n < s.N; n++) {
            if (s.estado(n, 20.5) !== 0) continue;
            s.posVisible(n, 20.5, p, window.pms.costa);
            const d = c.ctx.getImageData(Math.round(c.x(p[0]) * dpr), Math.round(c.y(p[1]) * dpr), 1, 1).data;
            if (d[3] === 255) vistos[hex(d)] = (vistos[hex(d)] || 0) + 1;
        }
        return { vistos, paleta: PALETAS.carta.sargazo, leyenda: [...document.querySelectorAll('#ley-estelas i')].map((i) => i.style.backgroundColor) };
    }""")
    # El centro de la mayoría cae en un píxel entero de su cuadro (color de la paleta); el resto, en
    # un borde suavizado: mezcla de púrpuras o de púrpura con el borde claro. El rasterizado por
    # software (Chromium en Linux, sin GPU) redondea una o dos unidades por canal: #460752 por #470852.
    def rgb(color):
        return tuple(int(color[k:k + 2], 16) for k in (1, 3, 5))

    def de_la_paleta(color, tolerancia=6):
        return any(max(abs(a - b) for a, b in zip(rgb(color), rgb(p))) <= tolerancia for p in pintado["paleta"])

    total = sum(pintado["vistos"].values())
    de_paleta = sum(n for color, n in pintado["vistos"].items() if de_la_paleta(color))
    assert total > 500 and de_paleta > 0.6 * total, pintado
    assert de_la_paleta(max(pintado["vistos"], key=pintado["vistos"].get))
    # Ningún grupo apreciable de partículas con el color de la tierra (los bordes suavizados que
    # mezclan púrpura con el borde claro pueden acercarse en uno o dos píxeles sueltos).
    parecidos_a_tierra = sum(n for color, n in pintado["vistos"].items()
                             if max(abs(a - b) for a, b in zip(rgb(color), TIERRA_CARTA)) <= 25)
    assert parecidos_a_tierra <= 0.01 * total, f"partículas pintadas con un color parecido a la tierra de la carta: {pintado}"
    for color in pintado["paleta"]:
        r, g, b = (int(color[k:k + 2], 16) for k in (1, 3, 5))
        assert b > g + 60 and r > g + 40, f"{color} es púrpura: lejos del ante de la tierra y del crema del mar"
    assert len(pintado["leyenda"]) == 3 and all(c.startswith("rgb") for c in pintado["leyenda"])
    capas(pagina, True)
    pagina.uncheck("#ver-estelas")
    assert huella_canvas(pagina, "particulas") != con
    pagina.check("#ver-estelas")
    pagina.wait_for_timeout(500)
    assert huella_canvas(pagina, "particulas") == con
    capas(pagina, False)


def test_rapidez_del_conglomerado_en_nudos_y_km_h_cambia_con_el_tiempo(pagina):
    lecturas = {}
    for h in (2, 30, 60):
        poner_hora(pagina, h)
        texto = pagina.text_content("#lt-kn")
        m = re.fullmatch(r"(\d\.\d\d) kn · (\d\.\d\d) km/h", texto)
        if m:
            kn, kmh = float(m.group(1)), float(m.group(2))
            assert kmh == pytest.approx(kn * 1.852, abs=0.02)
            assert re.fullmatch(r"rumbo \d{3}° \(\w+\)", pagina.text_content("#lt-rumbo"))
            lecturas[h] = kn
        else:
            assert texto == "sin sargazo a flote"
    assert 2 in lecturas and 0.05 < lecturas[2] < 0.6
    serie = pagina.evaluate("window.pms.sim.series.rapidez_centroide_ms.filter((v) => v !== null)")
    assert max(serie) > 1.15 * min(serie), "la rapidez del conglomerado no es constante"


def test_en_pausa_el_cursor_sobre_una_particula_da_su_rapidez_y_rumbo(pagina):
    poner_hora(pagina, 12.4)
    pagina.evaluate("window.pmsMapa.setView([window.pms.sim.series.centroide[12][1], window.pms.sim.series.centroide[12][0]], 10, { animate: false })")
    pagina.wait_for_timeout(300)
    pt = pagina.evaluate("""() => { const s = window.pms.sim, p = [0, 0];
        for (let n = 0; n < s.N; n++) { if (s.estado(n, 12.4) !== 0) continue; s.pos(n, 12.4, p);
            const q = window.pmsMapa.latLngToContainerPoint([p[1], p[0]]); if (q.x > 420 && q.x < 1000 && q.y > 130 && q.y < 500) return [q.x, q.y]; }
        return null; }""")
    assert pt
    pagina.mouse.move(pt[0] + 1, pt[1] + 1)
    pagina.wait_for_selector('[data-prueba="tt-particula"]')
    texto = pagina.inner_text('[data-prueba="tt-particula"]')
    assert re.search(r"Partícula \d+ · \d\.\d\d kn · \d\.\d\d km/h · rumbo \d{3}° \(\w+\)", texto), texto
    pagina.click("#btn-play")              # reproduciendo: el dato de la partícula desaparece
    pagina.mouse.move(pt[0] + 3, pt[1] + 2)
    pagina.wait_for_timeout(250)
    assert pagina.locator('[data-prueba="tt-particula"]').count() == 0
    pagina.click("#btn-play")


# --- 5. Línea de tiempo, densidad y hover ---------------------------------------------------------------

def test_linea_de_tiempo_con_fechas_saltos_y_velocidad(pagina):
    pausar(pagina)
    pagina.eval_on_selector("#lt-slider", "e => { e.value = 48; e.dispatchEvent(new Event('input')); }")
    pagina.click(".marca h1")
    assert pagina.text_content("#lt-h") == "Hora 48 de 120"
    pagina.keyboard.press("ArrowRight")
    assert hora(pagina) == 49
    pagina.keyboard.press("ArrowLeft")
    pagina.keyboard.press("ArrowLeft")
    assert hora(pagina) == 47
    assert pagina.text_content("#lt-utc") == "vie 02 oct · 23:00 UTC"          # 01 oct 00 UTC + 47 h
    assert pagina.text_content("#lt-local") == "vie 02 oct · 18:00 · Quintana Roo (UTC−5)"
    marcas = pagina.locator("#lt-dias i")
    assert marcas.count() == 6 and marcas.all_inner_texts() == ["01 oct", "02 oct", "03 oct", "04 oct", "05 oct", "06 oct"]
    assert [int(marcas.nth(k).get_attribute("data-hora")) for k in range(6)] == [0, 24, 48, 72, 96, 120]
    # Saltos de 3, 6 y 12 h: botones y Mayús + flechas.
    pagina.click("#btn-adelante")
    assert hora(pagina) == 53
    pagina.keyboard.press("Shift+ArrowLeft")
    assert hora(pagina) == 47
    for salto in ("3", "12"):
        pagina.select_option("#lt-salto", salto)
        assert pagina.inner_text("#btn-atras") == f"−{salto} h" and pagina.inner_text("#btn-adelante") == f"+{salto} h"
        pagina.click("#btn-adelante")
        pagina.click("#btn-adelante")
        pagina.click("#btn-atras")
        assert hora(pagina) == 47 + int(salto)
        poner_hora(pagina, 47)
    poner_hora(pagina, 118)
    pagina.click("#btn-adelante")
    assert hora(pagina) == 120, "no pasa del final"
    pagina.select_option("#lt-salto", "6")
    # Velocidad de reproducción: a 24 h/s se avanza cuatro veces más que a 6 h/s.
    # Se mide en la propia página (horas de pronóstico por segundo de reloj) para no depender
    # de lo que tarde el navegador en atender cada orden de la prueba.
    ritmos = {}
    for velocidad in ("6", "24"):
        pagina.select_option("#lt-velocidad", velocidad)
        poner_hora(pagina, 10)
        pagina.click("#btn-play")
        ritmos[velocidad] = pagina.evaluate("""() => new Promise((listo) => {
            const medir = () => ({ t: performance.now(), h: window.pms.hora });
            setTimeout(() => { const a = medir(); setTimeout(() => { const b = medir(); listo((1000 * (b.h - a.h)) / (b.t - a.t)); }, 900); }, 150);
        })""")
        pausar(pagina)
    assert ritmos["6"] == pytest.approx(6, rel=0.25) and ritmos["24"] == pytest.approx(24, rel=0.25), ritmos
    pagina.select_option("#lt-velocidad", "6")


def test_leyenda_de_densidad_con_unidades_y_sin_pintar_tierra(pagina):
    assert pagina.locator("#ley-densidad .clase").all_inner_texts() == ["0.2–1", "1–5", "5–20", "≥ 20"]
    unidad = pagina.inner_text(".ley-unidad")
    assert "% del sargazo liberado" in unidad and "0.04°" in unidad and "km" in unidad
    r = pagina.evaluate("""() => {
        const d = window.pmsDepurar, s = window.pms.sim;
        d.ponerHora(s.H);
        const dens = s.densidad(s.H);
        const suma = dens.celdas.reduce((a, c) => a + c.pct, 0);
        const zona = dens.celdas.filter((c) => c.p90).reduce((a, c) => a + c.pct, 0);
        return { suma, zona, dentro: (100 * dens.dentro) / s.N, celdas: dens.celdas.length };
    }""")
    assert r["suma"] == pytest.approx(r["dentro"], abs=1e-6), "los porcentajes suman el sargazo que sigue en el dominio"
    assert 0.9 * r["dentro"] <= r["zona"] + 1e-9, "el contorno encierra al menos el 90 %"
    # En una celda que toca la costa, el sombreado llega al mar y no entra a tierra.
    centro = pagina.evaluate("(() => { const a = window.pms.sim.reg.resumen.arribos[0].punto_primer_arribo; return [a[1], a[0]]; })()")
    poner_zoom(pagina, 10.5, centro)
    pagina.wait_for_timeout(300)
    muestra = pagina.evaluate("""() => {
        const d = window.pmsDepurar, s = window.pms.sim, c = d.capas.densidad, dpr = window.devicePixelRatio || 1;
        const alfa = (lon, lat) => c.ctx.getImageData(Math.round(c.x(lon) * dpr), Math.round(c.y(lat) * dpr), 1, 1).data[3];
        const dentro = (lon, lat, m) => [[m, 0], [-m, 0], [0, m], [0, -m], [0, 0]].every(([a, b]) => d.enTierra(lon + a, lat + b));
        const afuera = (lon, lat, m) => [[m, 0], [-m, 0], [0, m], [0, -m], [0, 0]].every(([a, b]) => !d.enTierra(lon + a, lat + b));
        for (const k of s.densidad(s.H).celdas) {
            if (k.pct < 1) continue;
            const lon0 = s.lon0 + k.j * 0.04, lat0 = s.lat0 + k.i * 0.04;
            let tierra = null, mar = null;
            for (let a = 0.5; a < 20; a++) for (let b = 0.5; b < 20; b++) {
                const lon = lon0 + a * 0.002, lat = lat0 + b * 0.002;
                if (!tierra && dentro(lon, lat, 0.006)) tierra = alfa(lon, lat);
                if (!mar && afuera(lon, lat, 0.006)) mar = alfa(lon, lat);
            }
            if (tierra !== null && mar !== null) return { tierra, mar, pct: k.pct };
        }
        return null;
    }""")
    assert muestra, "hay una celda de densidad que toca la costa"
    assert muestra["mar"] > 0 and muestra["tierra"] == 0, muestra
    # No son bloques: la opacidad cambia de forma gradual (muchos niveles), lleva trama y la
    # costa la recorta píxel a píxel.
    forma = pagina.evaluate("""() => {
        const c = window.pmsDepurar.capas.densidad, d = window.pms.densidadDibujada, dpr = window.devicePixelRatio || 1;
        const [x0, y0, x1, y1] = d.rect;
        const px = c.ctx.getImageData(Math.round(x0 * dpr), Math.round(y0 * dpr), Math.round((x1 - x0) * dpr), Math.round((y1 - y0) * dpr)).data;
        const niveles = new Set();
        let maximo = 0;
        for (let k = 3; k < px.length; k += 4) { niveles.add(px[k]); if (px[k] > maximo) maximo = px[k]; }
        return { niveles: niveles.size, maximo, ...d };
    }""")
    assert forma["niveles"] > 40, f"bordes suaves, no cuadros de un solo tono: {forma}"
    assert forma["maximo"] < 240, "siempre con transparencia (lo más opaco es la línea de la zona sobre la trama)"
    assert forma["recortados"] > 0 and forma["pintados"] > forma["recortados"], "recortada a la costa"
    assert forma["tramosZona"] > 0, "la zona con el 90 % solo se traza sobre el mar"
    poner_hora(pagina, 12)
    en_el_mar = pagina.evaluate("window.pms.densidadDibujada")
    assert en_el_mar["tramosZona"] >= 8 and en_el_mar["pintados"] > 500, f"mar adentro, una línea cerrada alrededor de la mancha: {en_el_mar}"
    poner_hora(pagina, 120)
    con = huella_canvas(pagina, "densidad")
    capas(pagina, True)
    pagina.uncheck("#ver-densidad")
    assert huella_canvas(pagina, "densidad") != con
    pagina.check("#ver-densidad")
    capas(pagina, False)


def test_hover_muestra_coordenadas_en_dos_formatos_y_la_ola_del_modelo(pagina):
    poner_hora(pagina, 0)
    poner_zoom(pagina, 9.5, [21.0, -86.5])
    pagina.mouse.move(*punto_en_pantalla(pagina, 21.0, -86.30))
    pagina.wait_for_selector("#tooltip:not([hidden])")
    texto = pagina.inner_text("#tooltip")
    assert PATRON_COORD.search(texto) and PATRON_GM.search(texto), texto
    m = re.search(r"Ola (\d+\.\d{2}) m · desde (\d+)° \((\w+)\)", texto)
    assert m, texto
    lat, lon = pagina.evaluate("(() => { const p = window.pmsMapa.containerPointToLatLng(window.pmsMapa.latLngToContainerPoint([21.0, -86.30])); return [p.lat, p.lng]; })()")
    modelo = pagina.evaluate("([lon, lat]) => fetch(`/api/ola?lon=${lon}&lat=${lat}&hora=0`).then((r) => r.json())", [lon, lat])
    assert float(m.group(1)) == pytest.approx(modelo["altura_m"], abs=0.02)
    assert float(m.group(2)) == pytest.approx(modelo["direccion_desde"], abs=1.5)
    pagina.mouse.move(*punto_en_pantalla(pagina, 21.16, -86.86))     # tierra: ciudad de Cancún
    pagina.wait_for_timeout(300)
    assert "Tierra (costa del modelo)" in pagina.inner_text("#tooltip")


# --- Exportar ----------------------------------------------------------------------------------------

def test_exportar_la_imagen_del_mapa(pagina, tmp_path):
    pausar(pagina)
    poner_hora(pagina, 12)
    with pagina.expect_download() as descarga:
        pagina.click("#btn-exportar-imagen")
    ruta = tmp_path / descarga.value.suggested_filename
    descarga.value.save_as(str(ruta))
    assert re.fullmatch(r"pms_sim-\d{8}-\d{6}-[0-9a-f]{4}_h012\.png", ruta.name)
    crudo = ruta.read_bytes()
    assert crudo[:8] == b"\x89PNG\r\n\x1a\n" and len(crudo) > 60_000
    ancho, alto = int.from_bytes(crudo[16:20], "big"), int.from_bytes(crudo[20:24], "big")
    assert (ancho, alto) == (1366, 768)
    exp = pagina.evaluate("window.pms.ultimaExportacion")
    assert exp["tipo"] == "imagen" and exp["sustituido"] is False and exp["bytes"] == len(crudo)


def test_resumen_de_una_pagina_con_parametros_arribos_escalas_y_limites(pagina):
    pausar(pagina)
    # Como función: si la expresión evaluada fuera la propia flecha, Playwright la ejecutaría.
    pagina.evaluate("() => { window.__impreso = 0; window.print = () => { window.__impreso += 1; }; }")
    pagina.click("#btn-imprimir")
    pagina.wait_for_function("window.__impreso === 1")
    arribos = pagina.evaluate("window.pms.sim.reg.resumen.arribos.length")
    assert pagina.locator('[data-prueba="informe-arribos"] tbody tr').count() == arribos
    assert pagina.is_hidden("#informe"), "en pantalla no se ve"
    pagina.emulate_media(media="print")
    try:
        assert pagina.is_visible("#informe") and pagina.is_hidden("#hoja") and pagina.is_hidden("#mapa")
        texto = pagina.inner_text("#informe")
        for esperado in ("Resumen de la simulación sim-", "generado el", "Punto de liberación", "Parámetros", "γ = 1.0",
                         "Arribos por tramo de costa", "Primer arribo", "MN", "kn", "Escalas", "flecha de ola de 1 m",
                         "Límites del modelo", "sin viento ni corrientes", "Fuentes", "OpenStreetMap", "/validacion"):
            assert esperado.lower() in texto.lower(), esperado
        assert PATRON_GM.search(texto)
        pagina.wait_for_function("(() => { const i = document.querySelector('#informe img'); return i.complete && i.naturalWidth === 1366; })()")
        pdf = pagina.pdf(format="A4", print_background=True)
        assert pdf[:5] == b"%PDF-"
        assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 1, "cabe en una página"
    finally:
        pagina.emulate_media(media="screen")


# --- Historial y errores -----------------------------------------------------------------------------

def test_historial_guarda_y_reabre(pagina):
    primera = pagina.evaluate("window.pms.sim.id")
    pagina.click('#pasos [data-paso="2"]')
    pagina.click("#avanzado summary")
    pagina.fill("#p-semilla", "7")
    pagina.click("#btn-simular")
    pagina.wait_for_function(f"window.pms.sim && window.pms.sim.id !== '{primera}' && window.pms.estado === 'resultado'", timeout=60_000)
    assert pagina.is_hidden("#historial"), "el historial está plegado"
    pagina.click("#btn-historial")
    pagina.wait_for_function("document.querySelectorAll('#lista-hist li[data-id]').length >= 2", timeout=5_000)
    pagina.click(f'#lista-hist li[data-id="{primera}"] button')
    pagina.wait_for_function(f"window.pms.sim.id === '{primera}'", timeout=10_000)
    assert pagina.input_value("#p-semilla") == "2026"
    assert pagina.is_hidden("#historial")
    pausar(pagina)


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


# --- 3. prefers-reduced-motion ------------------------------------------------------------------------

def test_con_movimiento_reducido_el_oleaje_no_se_anima(navegador, app_url):
    ctx, pg = abrir(navegador, app_url, reduced_motion="reduce")
    try:
        esperar_lista(pg)
        pg.wait_for_function("window.pms.flechas.length > 10")
        assert not pg.evaluate("window.pmsDepurar.animando()") and pg.evaluate("window.pms.ver.oleaje")
        f1 = huella_canvas(pg, "oleaje")
        pg.wait_for_timeout(600)
        assert huella_canvas(pg, "oleaje") == f1, "flechas fijas"
        capas(pg, True)
        assert not pg.is_checked("#ver-animar")
        assert "reducir el movimiento" in pg.inner_text("#nota-animar")
        pg.check("#ver-animar")                    # la persona puede encenderlo a propósito
        assert pg.evaluate("window.pmsDepurar.animando()")
        assert pg.errores == []
    finally:
        ctx.close()


# --- 2. Oleaje que cambia entre bloques: la interfaz interpola como el modelo --------------------------

def test_con_bloques_distintos_el_oleaje_cambia_con_la_hora_y_coincide_con_el_modelo(navegador, tmp_path, url_externa):
    _solo_local(url_externa)
    datos = crear_fixture(tmp_path / "semar", completo=True, identicos=False)
    servidor, url = _levantar(datos, tmp_path / "sims")
    try:
        ctx, pg = abrir(navegador, url, reduced_motion="reduce")
        esperar_lista(pg)
        assert "bloque +0 h" in pg.inner_text("#nota-ola") and "idénticos" not in pg.inner_text("#nota-ola")
        en_cero = huella_canvas(pg, "oleaje")
        poner_hora(pg, 61)
        assert "bloque +60 h" in pg.inner_text("#nota-ola")
        assert huella_canvas(pg, "oleaje") != en_cero, "si el archivo cambia entre bloques, se nota"
        poner_hora(pg, 61.5)
        a = huella_canvas(pg, "oleaje")
        poner_hora(pg, 62.5)
        assert huella_canvas(pg, "oleaje") != a, "y también dentro de un mismo bloque: se interpola en el tiempo"
        # La misma ola que el modelo, en puntos entre nodos y en horas entre bloques.
        comparacion = pg.evaluate("""async () => {
            const filas = [];
            for (const [lon, lat] of [[-86.47, 21.03], [-86.05, 19.31], [-85.2, 22.4], [-90.3, 22.1], [-87.31, 20.02], [-86.71, 21.19]]) {
                for (const hora of [0, 1.5, 37.25, 119.9]) {
                    const m = await (await fetch(`/api/ola?lon=${lon}&lat=${lat}&hora=${hora}`)).json();
                    const j = window.pmsDepurar.olaEn(lon, lat, hora);
                    filas.push([lon, lat, hora, m.altura_m, j && j.altura, m.direccion_desde, j && j.desde, m.rapidez_ms, j && j.deriva]);
                }
            }
            return filas;
        }""")
        assert len(comparacion) == 24
        for lon, lat, h, alt_m, alt_j, dir_m, dir_j, vel_m, vel_j in comparacion:
            assert alt_j == pytest.approx(alt_m, abs=0.011), (lon, lat, h)          # la altura viaja en centímetros
            assert abs((dir_j - dir_m + 180) % 360 - 180) < 0.2, (lon, lat, h)      # la dirección, en décimas de grado
            assert vel_j == pytest.approx(vel_m, abs=0.001), (lon, lat, h)
        alturas = [c[3] for c in comparacion if c[0] == -86.47]
        assert len(set(alturas)) == 4, "la ola cambia con la hora"
        assert pg.errores == []
        ctx.close()
    finally:
        servidor.should_exit = True


# --- Recorrido guiado completo, en un navegador «nuevo» -----------------------------------------

def test_recorrido_guiado_completo(navegador, app_url):
    ctx, pg = abrir(navegador, app_url, visto=False)
    esperar_lista(pg)
    pg.wait_for_selector(RECORRIDO)
    siguiente(pg)                                                     # 2: datos y oleaje
    assert "dirmarea.txt" in pg.text_content(RECORRIDO) and "1 m" in pg.text_content(RECORRIDO)
    siguiente(pg)                                                     # 3: carta, localidades y mapa base
    assert pg.is_visible("#capas") and "satélite" in pg.text_content(RECORRIDO)
    siguiente(pg)                                                     # 4: fijar el punto (espera el clic)
    assert pg.is_hidden("#capas")
    assert pg.is_disabled("#rec-siguiente")
    pg.mouse.click(*punto_en_pantalla(pg, *CANCUN))
    pg.wait_for_function("!document.getElementById('rec-siguiente').disabled")
    assert "Punto fijado" in pg.text_content("#rec-espera")
    siguiente(pg)                                                     # 5: horizonte
    assert pg.is_visible("#campo-horizonte")
    siguiente(pg)                                                     # 6: γ y K_h
    assert pg.get_attribute("#avanzado", "open") is not None
    siguiente(pg)                                                     # 7: simular (espera el resultado)
    assert pg.is_disabled("#rec-siguiente")
    pg.click("#btn-simular")
    pg.wait_for_function("!document.getElementById('rec-siguiente').disabled", timeout=60_000)
    assert "Simulación lista" in pg.text_content("#rec-espera")
    esperados = ["Cómo leer el mapa", "Escalas y leyenda", "línea de tiempo", "tabla de arribos", "Exportar", "historial", "Listo"]
    textos = {"Cómo leer el mapa": "estela", "Escalas y leyenda": "millas náuticas", "línea de tiempo": "Quintana Roo",
              "tabla de arribos": "Toque una fila", "Exportar": "PDF"}
    for esperado in esperados:
        siguiente(pg)
        assert esperado.lower() in pg.text_content(f"{RECORRIDO} h2").lower()
        if esperado in textos:
            assert textos[esperado] in pg.text_content(RECORRIDO), esperado
        foco = pg.evaluate("(() => { const f = document.querySelector('.rec-foco'); return f && f.style.display !== 'none' ? f.getBoundingClientRect().width : 0; })()")
        assert (foco > 20) == (esperado != "Listo"), f"el paso «{esperado}» ilumina su elemento"
    assert pg.text_content('[data-prueba="rec-contador"]') == f"Paso {PASOS_RECORRIDO} de {PASOS_RECORRIDO}"
    pg.click("#rec-atras")
    assert paso_recorrido(pg) == PASOS_RECORRIDO - 1
    siguiente(pg)
    pg.click("#rec-siguiente")                                        # «Terminar»
    assert pg.locator(RECORRIDO).count() == 0
    assert pg.evaluate(f"localStorage.getItem('{CLAVE_VISTO}')") == "1"
    pg.click("#btn-recorrido")                                        # siempre disponible
    pg.wait_for_selector(RECORRIDO)
    pg.keyboard.press("Escape")
    assert pg.locator(RECORRIDO).count() == 0
    assert pg.errores == []
    ctx.close()


# --- Datos inválidos y sin datos ------------------------------------------------------------

def test_datos_invalidos_muestran_error(navegador, tmp_path, url_externa):
    _solo_local(url_externa)
    malo = crear_fixture(tmp_path / "semar")
    editar_lineas(malo / ARCHIVO_OLEAJE, lambda l: [l[0], "01OCTU2026 00 0"] + l[2:])   # fecha ilegible
    servidor, url = _levantar(malo, tmp_path / "sims")
    try:
        ctx, pg = abrir(navegador, url, visto=False)
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


def test_estado_sin_datos(navegador, tmp_path, url_externa):
    _solo_local(url_externa)
    servidor, url = _levantar(tmp_path / "vacio", tmp_path / "sims")
    try:
        ctx, pg = abrir(navegador, url, visto=False)
        esperar_estado(pg, "sin-datos", timeout=15_000)
        assert "data/semar/" in pg.text_content("#velo")
        assert pg.is_disabled("#btn-simular")
        ctx.close()
    finally:
        servidor.should_exit = True


def test_pagina_validacion_desde_el_enlace_de_la_leyenda(navegador, app_url, url_externa):
    """El enlace discreto de la leyenda abre /validacion con conclusión, tabla y figuras."""
    from src.config import DIR_VALIDACION
    if not url_externa and not (DIR_VALIDACION / "index.html").is_file():
        pytest.skip("Aún no hay resultados de validación en docs/validacion/")
    ctx, pagina = abrir(navegador, app_url)
    enlace = pagina.locator("#enlace-validacion")
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
    assert not pagina.errores
    ctx.close()
