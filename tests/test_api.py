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
    assert reg["version_modelo"] == "pms-browniano-0.3.0"
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
    assert salud["estado"] == "ok" and salud["version_app"] == "0.3.0" and salud["version_modelo"] == "pms-browniano-0.3.0"
    assert salud["datos_disponibles"] is True and salud["trabajos_en_segundo_plano"] is True
    html = cliente.get("/")
    assert html.status_code == 200 and "Predicción de Movimiento del Sargazo" in html.text and "Recorrido guiado" in html.text
    for ruta in ("/static/js/main.js", "/static/js/recorrido.js"):
        js = cliente.get(ruta)
        assert js.status_code == 200 and "javascript" in js.headers["content-type"]
