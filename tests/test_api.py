"""API: validación, campos de oleaje, simulación guardada en el historial y errores 409/422/404."""
import time
import warnings

import numpy as np
import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

from src.api.almacen import decodificar_posiciones
from src.api.app import crear_app
from src.config import ARCHIVO_OLEAJE
from tests.conftest import editar_lineas

PEQUENA = {"lon": -86.30, "lat": 21.00, "particulas": 200, "horizonte_h": 24, "radio_km": 3, "semilla": 11}


@pytest.fixture
def cliente(semar, tmp_path):
    return TestClient(crear_app(semar, tmp_path / "sims"))


def test_post_simulacion_pequena_devuelve_200_y_se_guarda(cliente, tmp_path):
    r = cliente.post("/api/simulaciones", json={**PEQUENA, "gamma": 1.5, "kh_m2s": 5})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["version_modelo"] == "pms-browniano-0.4.0"
    assert reg["parametros"]["gamma"] == 1.5 and reg["parametros"]["kh_m2s"] == 5
    assert "alpha_pct" not in reg["parametros"]
    assert reg["datos"]["archivo"] == ARCHIVO_OLEAJE and len(reg["datos"]["huella_sha256"]) == 64
    assert any("Stokes" in l for l in reg["bitacora"])
    assert (tmp_path / "sims" / f"{reg['id']}.json").is_file()
    historial = cliente.get("/api/simulaciones").json()
    assert [h["id"] for h in historial] == [reg["id"]]
    completo = cliente.get(f"/api/simulaciones/{reg['id']}").json()
    lon, lat = decodificar_posiciones(completo["resultados"]["particulas"])
    assert lon.shape == lat.shape == (25, 200)
    assert np.allclose(lon[0].mean(), -86.30, atol=0.05)


def test_misma_semilla_reproduce_el_resultado(cliente):
    a = cliente.post("/api/simulaciones", json=PEQUENA).json()
    b = cliente.post("/api/simulaciones", json=PEQUENA).json()
    assert a["id"] != b["id"]
    assert a["resultados"]["particulas"]["lon"] == b["resultados"]["particulas"]["lon"]


def test_trabajo_en_segundo_plano_reporta_progreso(cliente):
    tid = cliente.post("/api/trabajos/simulacion", json=PEQUENA).json()["trabajo_id"]
    for _ in range(200):
        t = cliente.get(f"/api/trabajos/{tid}").json()
        if t["estado"] != "en_curso":
            break
        time.sleep(0.05)
    assert t["estado"] == "terminado" and t["avance"] == t["total"] == 24


def test_punto_en_tierra_responde_422_con_causa_y_accion(cliente):
    r = cliente.post("/api/simulaciones", json={**PEQUENA, "lon": -86.95, "lat": 21.05})  # Cancún, tierra adentro
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "tierra" in d["causa"] and d["accion"]


@pytest.mark.parametrize("campo, valor", [("particulas", 6000), ("gamma", 3.5), ("gamma", -1), ("kh_m2s", 101),
                                          ("horizonte_h", 12), ("horizonte_h", 121), ("lat", 30), ("lon", -84.0)])
def test_parametros_fuera_de_rango_422(cliente, campo, valor):
    assert cliente.post("/api/simulaciones", json={**PEQUENA, campo: valor}).status_code == 422


def test_datos_invalidos_responden_409(semar, tmp_path):
    editar_lineas(semar / ARCHIVO_OLEAJE, lambda l: [l[0], "FECHA ROTA"] + l[2:])
    c = TestClient(crear_app(semar, tmp_path / "sims"))
    r = c.post("/api/simulaciones", json=PEQUENA)
    assert r.status_code == 409 and r.json()["detail"]["accion"]
    assert c.get("/api/validacion").json()["valido"] is False
    assert c.get("/api/campos").status_code == 409


def test_los_avisos_de_validacion_quedan_en_la_api_y_en_el_registro(cliente, semar, tmp_path, caplog):
    """La interfaz ya no los muestra al operador (solo con ?tecnico=1): siguen en la API y en el log."""
    with caplog.at_level("INFO", logger="pms.datos"):
        rep = cliente.get("/api/validacion").json()
    avisos = [h["detalle"] for v in rep["verificaciones"] for h in v["hallazgos"] if h["nivel"] == "advertencia"]
    assert avisos, "el archivo de prueba tiene bloques idénticos: hay al menos un aviso"
    registrados = [r for r in caplog.records if r.name == "pms.datos"]
    assert {r.getMessage().removeprefix("dirmarea.txt: ").split(" → ")[0] for r in registrados if r.levelname == "WARNING"} == set(avisos)
    assert any("validado" in r.getMessage() and r.levelname == "INFO" for r in registrados)
    editar_lineas(semar / ARCHIVO_OLEAJE, lambda l: [l[0], "FECHA ROTA"] + l[2:])
    with caplog.at_level("INFO", logger="pms.datos"):
        TestClient(crear_app(semar, tmp_path / "sims2")).get("/api/validacion")
    assert any(r.levelname == "ERROR" and r.name == "pms.datos" for r in caplog.records), "los errores también"


def test_sin_datos(tmp_path):
    c = TestClient(crear_app(tmp_path / "vacio", tmp_path / "sims"))
    assert c.get("/api/salud").json()["datos_disponibles"] is False
    rep = c.get("/api/validacion").json()
    assert rep["valido"] is False and rep["verificaciones"][0]["hallazgos"][0]["archivo"] == ARCHIVO_OLEAJE


def test_validacion_y_campos_de_oleaje(cliente):
    rep = cliente.get("/api/validacion").json()
    assert rep["valido"] and rep["resumen_conjunto"]["bloques_identicos"]
    campos = cliente.get("/api/campos").json()
    assert campos["horas"] == list(range(0, 121, 3))
    assert campos["malla"]["resolucion_grados"] == 0.16 and campos["malla"]["nx"] == 11
    assert "ola_dir" in campos and "ola_altura" in campos and "viento_u" not in campos
    tid = cliente.post("/api/validacion").json()["trabajo_id"]
    for _ in range(100):
        t = cliente.get(f"/api/trabajos/{tid}").json()
        if t["estado"] != "en_curso":
            break
        time.sleep(0.05)
    assert t["estado"] == "terminado" and t["resultado"]["valido"]


@pytest.mark.parametrize("sim_id", ["no-existe", "..%2F..%2Fsecreto", "sim-20260101-000000-zzzz"])
def test_ids_invalidos_404(cliente, sim_id):
    assert cliente.get(f"/api/simulaciones/{sim_id}").status_code == 404


def test_trabajo_inexistente_404(cliente):
    assert cliente.get("/api/trabajos/no-existe").status_code == 404


def test_interfaz_y_salud(cliente):
    salud = cliente.get("/api/salud").json()
    assert salud["estado"] == "ok" and salud["version_app"] == "0.5.1" and salud["version_modelo"] == "pms-browniano-0.4.0"
    assert salud["datos_disponibles"] is True and salud["trabajos_en_segundo_plano"] is True
    html = cliente.get("/")
    assert html.status_code == 200 and "Predicción de Movimiento del Sargazo" in html.text and "Recorrido guiado" in html.text
    for ruta in ("/static/js/main.js", "/static/js/recorrido.js"):
        js = cliente.get(ruta)
        assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_pagina_validacion_y_sus_figuras(cliente):
    """La página /validacion sale de docs/validacion/ (scripts/validar.py) con sus figuras."""
    from src.config import DIR_VALIDACION
    if not (DIR_VALIDACION / "index.html").is_file():
        pytest.skip("Aún no hay resultados de validación en docs/validacion/")
    r = cliente.get("/validacion")
    assert r.status_code == 200 and "¿El modelo se mueve como el sargazo real?" in r.text
    # Las rutas relativas se resuelven contra <base href="/validacion/"> (la página se sirve sin "/" final).
    assert '<base href="/validacion/">' in r.text
    for src in __import__("re").findall(r"src=['\"]([^'\"]+)", r.text):
        assert cliente.get("/validacion/" + src).status_code == 200, src
    assert cliente.get("/validacion/figuras/fss_por_horizonte.png").headers["content-type"] == "image/png"
    assert cliente.get("/validacion/fss_resumen.csv").status_code == 200


# --- v0.5.0: costa del modelo, localidades, ola en un punto y tabla de arribos ---------------------

def test_costa_la_interfaz_recibe_la_misma_mascara_que_usa_el_modelo(cliente):
    import gzip
    import hashlib

    from src.model import costa

    info = cliente.get("/api/costa").json()
    assert info["malla"] == costa.MALLA_COSTA and info["sha256"] == costa.procedencia()["costa"]["sha256_bits"]
    assert [z["id"] for z in info["zonas"]] == [z["id"] for z in costa.ZONAS]
    assert "OpenStreetMap" in info["fuentes"]["costa"]["atribucion"] and info["fuentes"]["contexto"]["atribucion"] == "Natural Earth"
    r = cliente.get(info["mascara_url"])
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip" and len(r.content) == 6320 * 1030
    assert hashlib.sha256(r.content).hexdigest() == info["sha256"]
    crudo = cliente.get(info["mascara_url"], headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in crudo.headers and crudo.content == r.content
    contexto = cliente.get(info["contexto_url"])
    assert len(contexto.content) == 2000 * 350
    assert len(gzip.compress(r.content)) < 200_000, "viaja en decenas de KB"
    assert cliente.get("/api/costa/otra.bin").status_code == 404


def test_localidades_con_fuente(cliente):
    d = cliente.get("/api/localidades").json()
    assert d["fuente"]["licencia"] == "ODbL 1.0" and "OpenStreetMap" in d["fuente"]["atribucion"]
    cancun = next(l for l in d["localidades"] if l["nombre"] == "Cancún")
    assert cancun["osm"].startswith("node/") and cancun["rango"] == 1


def test_ola_en_un_punto_es_la_del_modelo(cliente, semar):
    from src.ingestion.validador import validar_conjunto
    from src.model.campos import CamposOleaje

    campos = CamposOleaje(validar_conjunto(semar)[1])
    lon, lat = -86.47, 21.03
    d = cliente.get("/api/ola", params={"lon": lon, "lat": lat, "hora": 37.5}).json()
    h, direccion = campos.ola(np.array([lon]), np.array([lat]), 37.5)
    u, v = campos.velocidades(np.array([lon]), np.array([lat]), 37.5)
    assert d["altura_m"] == pytest.approx(float(h[0])) and d["direccion_desde"] == pytest.approx(float(direccion[0]))
    assert d["u_ms"] == pytest.approx(float(u[0])) and d["v_ms"] == pytest.approx(float(v[0]))
    assert d["en_tierra"] is False and d["rumbo_hacia"] == pytest.approx((d["direccion_desde"] + 180) % 360, abs=1e-6)
    tierra = cliente.get("/api/ola", params={"lon": -86.95, "lat": 21.05}).json()
    assert tierra["en_tierra"] is True
    assert cliente.get("/api/ola", params={"lon": -86.47, "lat": 21.03, "hora": 500}).status_code == 422


def test_campos_incluyen_la_franja_costera_extendida(cliente):
    import base64

    c = cliente.get("/api/campos").json()
    n = len(c["horas"]) * c["malla"]["ny"] * c["malla"]["nx"]
    altura = np.frombuffer(base64.b64decode(c["ola_altura"]), dtype="<u2")
    direccion = np.frombuffer(base64.b64decode(c["ola_dir"]), dtype="<u2")
    extrapolado = np.frombuffer(base64.b64decode(c["extrapolado"]), dtype=np.uint8)
    assert altura.size == direccion.size == extrapolado.size == n
    assert c["modelo"]["nodos_extrapolacion"] == 2
    assert extrapolado.sum() > 0 and (altura[extrapolado == 1] != 65535).all(), "los nodos extendidos traen ola"
    assert ((altura == 65535) == (direccion == 65535)).all() and direccion[direccion != 65535].max() < 3600


def test_tabla_de_arribos_y_rapidez_del_conglomerado(cliente):
    reg = cliente.post("/api/simulaciones", json={"lon": -86.66, "lat": 21.12, "particulas": 300, "horizonte_h": 72}).json()
    s = reg["resumen"]
    assert s["arribos"], "frente a Cancún hay arribos"
    for a in s["arribos"]:
        assert set(a) >= {"zona", "nombre", "particulas", "probabilidad", "etiqueta", "primer_arribo_h", "arribo_mediano_h",
                          "distancia_km", "distancia_mn", "punto_primer_arribo", "limites"}
        assert 0 < a["primer_arribo_h"] <= a["arribo_mediano_h"] <= 72
        assert a["distancia_mn"] == pytest.approx(a["distancia_km"] / 1.852, abs=0.06)
        o, sur, e, n = a["limites"]
        assert o <= a["punto_primer_arribo"][0] <= e and sur <= a["punto_primer_arribo"][1] <= n
    assert [a["probabilidad"] for a in s["arribos"]] == sorted((a["probabilidad"] for a in s["arribos"]), reverse=True)
    assert sum(a["particulas"] for a in s["arribos"]) == round(s["varadas_pct"] * 3)
    series = reg["resultados"]["series"]
    assert len(series["rapidez_centroide_ms"]) == len(series["rumbo_centroide_grados"]) == 73
    rapidez = [v for v in series["rapidez_centroide_ms"] if v is not None]
    assert rapidez and 0.0 < max(rapidez) < 0.5 and max(rapidez) > min(rapidez), "la rapidez cambia con el tiempo"
    assert s["distancia_centroide_mn"] == pytest.approx(s["distancia_centroide_km"] / 1.852, abs=0.06)
    assert [z["id"] for z in reg["resultados"]["zonas"]][:4] == ["cuba", "banco_campeche", "chinchorro", "cozumel"]


def test_el_historial_solo_lista_simulaciones_del_modelo_actual(cliente, tmp_path):
    import json

    reg = cliente.post("/api/simulaciones", json=PEQUENA).json()
    viejo = {**reg, "id": "sim-20261001-000000-abcd", "version_modelo": "pms-browniano-0.3.0"}
    (tmp_path / "sims" / f"{viejo['id']}.json").write_text(json.dumps(viejo), encoding="utf-8")
    assert [h["id"] for h in cliente.get("/api/simulaciones").json()] == [reg["id"]]
