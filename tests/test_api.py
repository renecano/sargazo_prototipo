"""API: validación, campos, simulación guardada en el historial y errores con causa y acción."""
import time
import warnings

import numpy as np
import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

from src.api.almacen import decodificar_posiciones
from src.api.app import crear_app
from src.config import ARCHIVO_OLEAJE, ARCHIVO_VIENTO
from tests.conftest import editar_lineas

PEQUENA = {"lon": -86.66, "lat": 21.12, "particulas": 200, "horizonte_h": 24, "radio_km": 3, "semilla": 11}


@pytest.fixture
def cliente(semar, tmp_path):
    return TestClient(crear_app(semar, tmp_path / "sims"))


def test_post_simulacion_pequena_devuelve_200_y_se_guarda(cliente, tmp_path):
    r = cliente.post("/api/simulaciones", json=PEQUENA)
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["parametros"]["semilla"] == 11
    assert reg["version_modelo"] == "pms-lagrangiano-0.2.0"
    # Huella SHA-256 de ambos archivos de SEMAR en el registro
    huellas = {a["nombre"]: a["huella_sha256"] for a in reg["datos"]["archivos"]}
    assert set(huellas) == {ARCHIVO_VIENTO, ARCHIVO_OLEAJE} and all(len(h) == 64 for h in huellas.values())
    assert reg["datos"]["corrientes"] is False and reg["datos"]["viento_estacionario"] is True
    assert any("u_c = 0" in l for l in reg["bitacora"])
    assert any("una sola hora" in a for a in reg["resumen"]["advertencias"])
    # Persistido como JSON y visible en el historial
    assert (tmp_path / "sims" / f"{reg['id']}.json").is_file()
    historial = cliente.get("/api/simulaciones").json()
    assert [h["id"] for h in historial] == [reg["id"]]
    assert historial[0]["parametros"]["particulas"] == 200
    completo = cliente.get(f"/api/simulaciones/{reg['id']}").json()
    lon, lat = decodificar_posiciones(completo["resultados"]["particulas"])
    assert lon.shape == lat.shape == (25, 200)
    assert np.allclose(lon[0].mean(), -86.66, atol=0.05)


def test_misma_semilla_reproduce_el_resultado(cliente):
    a = cliente.post("/api/simulaciones", json=PEQUENA).json()
    b = cliente.post("/api/simulaciones", json=PEQUENA).json()
    assert a["id"] != b["id"]
    assert a["resultados"]["particulas"]["lon"] == b["resultados"]["particulas"]["lon"]
    assert len(cliente.get("/api/simulaciones").json()) == 2


def test_trabajo_en_segundo_plano_reporta_progreso(cliente):
    tid = cliente.post("/api/trabajos/simulacion", json=PEQUENA).json()["trabajo_id"]
    for _ in range(200):
        t = cliente.get(f"/api/trabajos/{tid}").json()
        if t["estado"] != "en_curso":
            break
        time.sleep(0.05)
    assert t["estado"] == "terminado"
    assert t["avance"] == t["total"] == 24
    assert t["resultado"]["id"].startswith("sim-")


def test_punto_en_tierra_responde_422_con_causa_y_accion(cliente):
    r = cliente.post("/api/simulaciones", json={**PEQUENA, "lon": -86.95, "lat": 21.05})  # Cancún, tierra adentro
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "tierra" in d["causa"] and d["accion"]


@pytest.mark.parametrize("campo, valor", [("particulas", 6000), ("alpha_pct", 5), ("horizonte_h", 12),
                                          ("horizonte_h", 121), ("lat", 30)])
def test_parametros_fuera_de_rango_422(cliente, campo, valor):
    assert cliente.post("/api/simulaciones", json={**PEQUENA, campo: valor}).status_code == 422


def test_datos_invalidos_responden_409(semar, tmp_path):
    editar_lineas(semar / ARCHIVO_VIENTO, lambda l: [l[0], "FECHA ROTA"] + l[2:])
    c = TestClient(crear_app(semar, tmp_path / "sims"))
    r = c.post("/api/simulaciones", json=PEQUENA)
    assert r.status_code == 409
    assert r.json()["detail"]["accion"]
    assert c.get("/api/validacion").json()["valido"] is False
    assert c.get("/api/campos").status_code == 409


def test_sin_datos(tmp_path):
    c = TestClient(crear_app(tmp_path / "vacio", tmp_path / "sims"))
    assert c.get("/api/salud").json()["datos_disponibles"] is False
    rep = c.get("/api/validacion").json()
    assert rep["valido"] is False and rep["verificaciones"][0]["hallazgos"][0]["archivo"] == ARCHIVO_VIENTO


def test_validacion_y_campos(cliente):
    rep = cliente.get("/api/validacion").json()
    assert rep["valido"] and rep["resumen_conjunto"]["viento_estacionario"]
    campos = cliente.get("/api/campos").json()
    assert campos["malla"]["resolucion_grados"] == 0.16
    assert campos["tiempos_viento_utc"] == ["2026-08-19T00:00Z"]
    assert campos["ola_horas"] == list(range(0, 121, 3))
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


def test_interfaz_y_salud(cliente):
    salud = cliente.get("/api/salud").json()
    assert salud["estado"] == "ok" and salud["version_app"] == "0.2.0" and salud["datos_disponibles"] is True
    assert salud["trabajos_en_segundo_plano"] is True and salud["almacenamiento_efimero"] is False
    html = cliente.get("/")
    assert html.status_code == 200 and "Predicción de Movimiento del Sargazo" in html.text
    js = cliente.get("/static/js/main.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
