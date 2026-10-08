"""API: simulación, persistencia en el historial, validación y errores con causa y acción."""
import time
import warnings

import numpy as np
import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

from scripts.generar_datos_demo import sembrar_errores
from src.api.almacen import decodificar_posiciones
from src.api.app import crear_app

PEQUENA = {"lon": -86.66, "lat": 21.12, "particulas": 200, "horizonte_h": 24, "radio_km": 3, "semilla": 11}


@pytest.fixture
def cliente(conjunto, tmp_path):
    sembrar_errores(conjunto, conjunto.parent / "demo_errores")
    return TestClient(crear_app(conjunto.parent, tmp_path / "sims"))


def test_post_simulacion_pequena_devuelve_200_y_se_guarda(cliente, tmp_path):
    r = cliente.post("/api/simulaciones", json=PEQUENA)
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["parametros"]["semilla"] == 11
    assert reg["version_modelo"].startswith("pms-")
    assert reg["conjunto"]["archivos"] == 120 and len(reg["conjunto"]["huella_sha256"]) == 64
    # Persistido como JSON y visible en el historial
    assert (tmp_path / "sims" / f"{reg['id']}.json").is_file()
    historial = cliente.get("/api/simulaciones").json()
    assert [h["id"] for h in historial] == [reg["id"]]
    assert historial[0]["parametros"]["particulas"] == 200
    # Se puede reabrir con todas las posiciones
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


@pytest.mark.parametrize("campo, valor", [("particulas", 6000), ("alpha_pct", 5), ("horizonte_h", 12), ("lat", 30)])
def test_parametros_fuera_de_rango_422(cliente, campo, valor):
    assert cliente.post("/api/simulaciones", json={**PEQUENA, campo: valor}).status_code == 422


def test_conjunto_con_errores_responde_409(cliente):
    r = cliente.post("/api/simulaciones", json={**PEQUENA, "conjunto": "demo_errores"})
    assert r.status_code == 409
    assert r.json()["detail"]["accion"]
    rep = cliente.get("/api/conjuntos/demo_errores/validacion").json()
    assert rep["valido"] is False


def test_validacion_y_campos(cliente):
    rep = cliente.get("/api/conjuntos/demo/validacion").json()
    assert rep["valido"] and rep["archivos_encontrados"] == 120
    campos = cliente.get("/api/conjuntos/demo/campos").json()
    assert campos["horas"] == 120 and campos["malla"]["resolucion_grados"] == 0.16
    assert len(campos["tiempos_utc"]) == 120


def test_conjuntos_listados(cliente):
    ids = [c["id"] for c in cliente.get("/api/conjuntos").json()]
    assert ids[:2] == ["demo", "demo_errores"]


@pytest.mark.parametrize("sim_id", ["no-existe", "..%2F..%2Fsecreto", "sim-20260101-000000-zzzz"])
def test_ids_invalidos_404(cliente, sim_id):
    assert cliente.get(f"/api/simulaciones/{sim_id}").status_code == 404


def test_interfaz_y_salud(cliente):
    salud = cliente.get("/api/salud").json()
    assert salud["estado"] == "ok"
    assert salud["trabajos_en_segundo_plano"] is True and salud["almacenamiento_efimero"] is False
    html = cliente.get("/")
    assert html.status_code == 200 and "Predicción de Movimiento del Sargazo" in html.text
    js = cliente.get("/static/js/main.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
