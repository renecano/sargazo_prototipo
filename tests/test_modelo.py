"""Modelo pms-browniano-0.4.0: deriva de Stokes analítica, γ, movimiento browniano, interpolación,
reproducibilidad, costa, dominio y métricas."""
import math
from datetime import datetime, timezone

import numpy as np
import pytest

from scripts.generar_fixtures import escribir_dirmarea
from src.config import ARCHIVO_OLEAJE, COEF_PERIODO, GRAVEDAD, PASO_SEGUNDOS, RADIO_TIERRA_M
from src.ingestion.lector import ConjuntoDatos
from src.ingestion.validador import validar_conjunto
from src.model import costa
from src.model.campos import CamposOleaje, OleajeUniforme, deriva_hacia, magnitud_stokes
from src.model.metricas import resumir
from src.model.simulacion import A_FLOTE, FUERA, VARADA, Parametros, PuntoInvalido, simular
from tests.conftest import sin_tierra

DOMINIO_ABIERTO = (-100.0, -70.0, 5.0, 35.0)
LIBERACION = dict(lon=-86.0, lat=21.0)


def grados_lon(m, lat):
    return np.degrees(m / (RADIO_TIERRA_M * np.cos(np.radians(lat))))


def grados_lat(m):
    return np.degrees(m / RADIO_TIERRA_M)


def stokes_analitico(h):
    """|u_s| = 2π³·H² / (g·T³) con T = 4.0·√H, escrito tal cual, sin simplificar."""
    t = COEF_PERIODO * math.sqrt(h)
    return 2 * math.pi ** 3 * h ** 2 / (GRAVEDAD * t ** 3)


def correr(campos, **kw):
    p = Parametros(**{**LIBERACION, "radio_km": 3.0, "particulas": 300, "kh_m2s": 0.0, "horizonte_h": 48, **kw})
    return simular(campos, p, en_tierra=sin_tierra, dominio=DOMINIO_ABIERTO)


# --- Deriva de Stokes ---------------------------------------------------------

@pytest.mark.parametrize("h", [0.25, 1.0, 1.25, 2.78])
def test_magnitud_de_stokes_coincide_con_la_formula(h):
    assert magnitud_stokes(h) == pytest.approx(stokes_analitico(h), rel=1e-12)


def test_valor_de_referencia_h_125():
    assert magnitud_stokes(1.25) == pytest.approx(0.110, abs=0.001)   # ≈ 0.11 m/s, documentado en config y README


def test_sin_ola_no_hay_deriva():
    assert magnitud_stokes(0.0) == 0.0 and magnitud_stokes(np.nan) == 0.0


@pytest.mark.parametrize("desde, signo", [(0, (0, -1)), (90, (-1, 0)), (180, (0, 1)), (270, (1, 0))],
                         ids=["del N", "del E", "del S", "del O"])
def test_la_deriva_va_hacia_donde_viaja_la_ola(desde, signo):
    u, v = deriva_hacia(1.0, desde)
    mag = magnitud_stokes(1.0)
    assert u == pytest.approx(signo[0] * mag, abs=1e-12) and v == pytest.approx(signo[1] * mag, abs=1e-12)


# --- Solución analítica con K_h = 0 y ola constante -----------------------------

def test_ola_del_sur_lleva_al_norte_la_distancia_analitica():
    r = correr(OleajeUniforme(altura=1.25, direccion_desde=180.0))
    esperado = grados_lat(stokes_analitico(1.25) * PASO_SEGUNDOS * 48)
    assert np.allclose(r.lat[-1] - r.lat[0], esperado, rtol=1e-12)
    assert np.allclose(r.lon[-1], r.lon[0], atol=1e-12)


def test_ola_del_este_lleva_al_oeste_con_cos_lat():
    r = correr(OleajeUniforme(altura=1.0, direccion_desde=90.0))
    esperado = -grados_lon(stokes_analitico(1.0) * PASO_SEGUNDOS * 48, r.lat[0])
    assert np.allclose(r.lon[-1] - r.lon[0], esperado, rtol=1e-9)
    assert np.allclose(r.lat[-1], r.lat[0], atol=1e-12)


def test_gamma_escala_la_deriva():
    ola = OleajeUniforme(altura=1.25, direccion_desde=180.0)
    r1, r25 = correr(ola, gamma=1.0), correr(ola, gamma=2.5)
    assert np.allclose(r25.lat[-1] - r25.lat[0], 2.5 * (r1.lat[-1] - r1.lat[0]), rtol=1e-12)
    r0 = correr(ola, gamma=0.0)
    assert np.array_equal(r0.lat[-1], r0.lat[0]) and np.array_equal(r0.lon[-1], r0.lon[0])


# --- Movimiento browniano -------------------------------------------------------------

def test_misma_semilla_mismo_resultado():
    ola = OleajeUniforme(altura=1.0, direccion_desde=120.0)
    a, b, c = (correr(ola, kh_m2s=10.0, semilla=s) for s in (42, 42, 43))
    assert np.array_equal(a.lon, b.lon) and np.array_equal(a.lat, b.lat)
    assert not np.array_equal(a.lon, c.lon)


def test_dispersion_browniana_sigue_raiz_de_2kt():
    k_h = 10.0
    p = Parametros(**LIBERACION, radio_km=0.5, particulas=5000, kh_m2s=k_h, horizonte_h=120, semilla=1)
    r = simular(OleajeUniforme(altura=1.0, direccion_desde=90.0), p, en_tierra=sin_tierra, dominio=DOMINIO_ABIERTO)
    km_y = np.radians(r.lat - r.lat[0].mean()) * RADIO_TIERRA_M / 1000
    std = km_y.std(axis=1)
    assert std[24] < std[48] < std[72] < std[120]
    # σ = √(2·K_h·t) por eje, más la varianza del disco inicial de 0.5 km (R²/4).
    teorico = np.sqrt(2 * k_h * 120 * 3600 + (500.0 ** 2) / 4) / 1000
    assert std[120] == pytest.approx(teorico, rel=0.05)


# --- Campos de oleaje: interpolación ----------------------------------------------------

@pytest.fixture(scope="module")
def conjunto(semar_base):
    return validar_conjunto(semar_base)[1]


def test_interpolacion_lineal_entre_bloques(semar):
    escribir_dirmarea(semar / ARCHIVO_OLEAJE, identicos=False)
    campos = CamposOleaje(validar_conjunto(semar)[1])
    lon, lat = np.array([-86.5]), np.array([21.0])
    h0, d0 = campos.ola(lon, lat, 0.0)
    h3, d3 = campos.ola(lon, lat, 3.0)
    h15, d15 = campos.ola(lon, lat, 1.5)
    assert h0[0] != h3[0]
    assert h15[0] == pytest.approx(0.5 * (h0[0] + h3[0]), rel=1e-9)
    assert d15[0] == pytest.approx(0.5 * (d0[0] + d3[0]), abs=1e-3)   # ángulos cercanos: seno/coseno ≈ promedio


def test_bloques_identicos_dan_deriva_estacionaria(conjunto):
    campos = CamposOleaje(conjunto)
    lon, lat = np.array([-86.5, -86.3]), np.array([21.0, 20.5])
    assert np.array_equal(campos.velocidades(lon, lat, 0.0)[0], campos.velocidades(lon, lat, 120.0)[0])


def test_direccion_por_seno_y_coseno():
    c = ConjuntoDatos(lons=np.array([0.0, 0.16]), lats=np.array([0.0, 0.16]), fecha_base=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      horas=np.array([0.0]), altura=np.ones((1, 2, 2)), direccion=np.array([[[350.0, 10.0], [350.0, 10.0]]]),
                      mar=np.ones((2, 2), bool), archivo="x", huella_sha256="0" * 64, bloques_identicos=False)
    _, d = CamposOleaje(c).ola(np.array([0.08]), np.array([0.0]), 0.0)
    assert min(d[0], 360 - d[0]) == pytest.approx(0.0, abs=1e-9), "350° y 10° promedian a 0°, no a 180°"


def test_interpolacion_ignora_nodos_de_tierra(conjunto):
    campos = CamposOleaje(conjunto)
    d = conjunto
    i, j = next((i, j) for i in range(d.lats.size - 1) for j in range(d.lons.size - 1) if d.mar[i, j] and not d.mar[i, j + 1])
    lon = d.lons[j] + 0.25 * (d.lons[1] - d.lons[0])
    h, _ = campos.ola(np.array([lon]), np.array([d.lats[i]]), 0.0)
    assert h[0] == pytest.approx(float(d.altura[0, i, j]), rel=0.05), "la altura no se diluye con los nodos sin dato"


# --- Costa y dominio --------------------------------------------------------------------

def test_ninguna_particula_queda_sobre_tierra(conjunto):
    d = conjunto
    dominio = (float(d.lons[0]), float(d.lons[-1]), float(d.lats[0]), float(d.lats[-1]))
    p = Parametros(lon=-86.62, lat=21.10, radio_km=8.0, particulas=2000, gamma=2.0, kh_m2s=30.0, horizonte_h=120, semilla=3)
    r = simular(CamposOleaje(d), p, dominio=dominio)
    varadas = r.estado == VARADA
    assert varadas.mean() > 0.2, "la ola viaja hacia la costa: una parte debe varar"
    for h in range(r.horas + 1):
        assert not costa.en_tierra(r.lon[h], r.lat[h]).any(), f"partícula sobre tierra en +{h} h"
    assert costa.distancia_costa_km(r.lon[-1, varadas], r.lat[-1, varadas]).max() < 1.0
    n = np.flatnonzero(varadas)[0]
    hv = r.hora_varada[n]
    assert np.all(r.lon[hv:, n] == r.lon[hv, n]), "una partícula varada ya no se mueve"


def test_particulas_que_salen_del_dominio_se_congelan_en_el_borde():
    dominio = (-86.5, -85.5, 20.5, 21.5)
    p = Parametros(lon=-86.0, lat=21.0, radio_km=2.0, particulas=200, gamma=3.0, kh_m2s=0.0, horizonte_h=120)
    r = simular(OleajeUniforme(altura=2.0, direccion_desde=180.0), p, en_tierra=sin_tierra, dominio=dominio)
    assert np.all(r.estado == FUERA)
    assert np.allclose(r.lat[-1], 21.5) and np.all(r.hora_fuera > 0)


def test_punto_en_tierra_o_fuera_del_dominio_es_invalido():
    with pytest.raises(PuntoInvalido, match="tierra"):
        simular(OleajeUniforme(), Parametros(lon=-88.5, lat=20.5))
    with pytest.raises(PuntoInvalido, match="fuera del dominio"):
        simular(OleajeUniforme(), Parametros(lon=-80.0, lat=20.5))


def test_particulas_iniciales_en_tierra_se_reubican():
    p = Parametros(lon=-86.72, lat=21.14, radio_km=15.0, particulas=1000, horizonte_h=24, kh_m2s=0.0)
    r = simular(OleajeUniforme(), p)
    assert r.reubicadas_inicio > 0 and not costa.en_tierra(r.lon[0], r.lat[0]).any()


# --- Métricas y bitácora --------------------------------------------------------------------

def test_resumen_consistente(conjunto):
    d = conjunto
    dominio = (float(d.lons[0]), float(d.lons[-1]), float(d.lats[0]), float(d.lats[-1]))
    r = simular(CamposOleaje(d), Parametros(lon=-86.30, lat=21.0, particulas=1000, horizonte_h=120), dominio=dominio)
    s = resumir(r)
    assert s["a_flote_pct"] + s["varadas_pct"] + s["fuera_pct"] == pytest.approx(100.0, abs=0.2)
    assert sum(a["particulas"] for a in s["arribos"]) == int((r.estado == VARADA).sum())
    assert all(a["etiqueta"] in ("Alta", "Media", "Baja", "Muy baja") for a in s["arribos"])
    assert len(s["series"]["centroide"]) == 121
    assert set(s["radio_p90_km"]) == {"24", "48", "72", "96", "120"}
    assert any("probabilístico" in a for a in s["advertencias"])
    assert any("4.0·√H" in a for a in s["advertencias"])
    a_flote = r.estado_en(24) == A_FLOTE
    cx, cy = s["series"]["centroide"][24]
    assert cx == pytest.approx(r.lon[24, a_flote].mean(), abs=1e-4) and cy == pytest.approx(r.lat[24, a_flote].mean(), abs=1e-4)
    assert any("pms-browniano-0.4.0" in l for l in r.bitacora) and any("γ = 1" in l for l in r.bitacora)


def test_costa_reconoce_tierra_y_mar():
    lon = np.array([-86.62, -88.50, -86.90, -84.50, -89.60])
    lat = np.array([21.15, 20.50, 20.42, 22.30, 20.90])
    assert costa.en_tierra(lon, lat).tolist() == [False, True, True, False, True]
    assert costa.zona_costera(np.array([-86.75, -86.95, -87.42]), np.array([21.10, 20.60, 20.20])).tolist() == \
        ["cancun", "cozumel", "tulum"]
