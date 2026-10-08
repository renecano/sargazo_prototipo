"""Conversiones de dirección (meteorológica "desde" → vector "hacia") y de unidades."""
import numpy as np
import pytest

from src.model.conversiones import (
    NUDO_A_MS, desde_a_vector, diferencia_angular, distancia_km, metros_a_grados, nombre_rumbo,
    normalizar_longitud, nudos_a_ms, vector_a_desde, vector_a_hacia,
)


@pytest.mark.parametrize(
    "desde, esperado",
    [
        (0.0, (0.0, -1.0)),    # viento del N empuja hacia el S
        (90.0, (-1.0, 0.0)),   # viento del E empuja hacia el O
        (180.0, (0.0, 1.0)),   # viento del S empuja hacia el N
        (270.0, (1.0, 0.0)),   # viento del O empuja hacia el E
        (360.0, (0.0, -1.0)),
    ],
    ids=["N", "E", "S", "O", "N-360"],
)
def test_desde_a_vector_cardinales(desde, esperado):
    u, v = desde_a_vector(1.0, desde)
    assert u == pytest.approx(esperado[0], abs=1e-12)
    assert v == pytest.approx(esperado[1], abs=1e-12)


def test_desde_a_vector_escala_con_la_velocidad():
    u, v = desde_a_vector(5.3, 45.0)  # del NE, hacia el SO
    assert u == pytest.approx(-5.3 / np.sqrt(2))
    assert v == pytest.approx(-5.3 / np.sqrt(2))


def test_ida_y_vuelta_desde_vector():
    rng = np.random.default_rng(0)
    vel = rng.uniform(0.1, 17, 500)
    dirs = rng.uniform(0, 360, 500)
    v2, d2 = vector_a_desde(*desde_a_vector(vel, dirs))
    assert np.allclose(v2, vel)
    assert np.all(diferencia_angular(d2, dirs) < 1e-9)


def test_rumbo_hacia_es_opuesto_a_desde():
    u, v = desde_a_vector(1.0, 110.0)
    _, hacia = vector_a_hacia(u, v)
    assert hacia == pytest.approx(290.0)


@pytest.mark.parametrize("nudos, ms", [(1, 0.514444), (10, 5.14444), (0, 0.0), (33.0, 16.976652)])
def test_nudos_a_ms(nudos, ms):
    assert nudos_a_ms(nudos) == pytest.approx(ms)
    assert NUDO_A_MS == 0.514444


def test_normalizar_longitud_0_360():
    assert normalizar_longitud(273.5) == pytest.approx(-86.5)
    assert normalizar_longitud(-86.5) == pytest.approx(-86.5)
    assert normalizar_longitud(180.0) == pytest.approx(-180.0)


def test_metros_a_grados_corrige_por_cos_lat():
    # 1° de latitud ≈ 111.195 km en todas partes
    _, dlat = metros_a_grados(0.0, 111_194.93, 21.0)
    assert dlat == pytest.approx(1.0, rel=1e-6)
    # a 60° de latitud, 1° de longitud mide la mitad
    dlon_ecuador, _ = metros_a_grados(111_194.93, 0.0, 0.0)
    dlon_60, _ = metros_a_grados(111_194.93, 0.0, 60.0)
    assert dlon_ecuador == pytest.approx(1.0, rel=1e-6)
    assert dlon_60 == pytest.approx(2.0, rel=1e-6)


def test_distancia_km_haversine():
    assert distancia_km(-86.0, 21.0, -86.0, 22.0) == pytest.approx(111.19, rel=1e-3)
    assert distancia_km(-86.0, 21.0, -86.0, 21.0) == pytest.approx(0.0)


def test_diferencia_angular_cruza_el_norte():
    assert diferencia_angular(359.0, 1.0) == pytest.approx(2.0)
    assert diferencia_angular(10.0, 190.0) == pytest.approx(180.0)


@pytest.mark.parametrize("g, nombre", [(0, "N"), (22.5, "NNE"), (90, "E"), (112, "ESE"), (270, "O"), (350, "N")])
def test_nombre_rumbo(g, nombre):
    assert nombre_rumbo(g) == nombre
