"""Modelo lagrangiano: solución analítica, reproducibilidad, dispersión, costa y métricas."""
import numpy as np
import pytest

from src.config import ARCHIVO_VIENTO, PASO_SEGUNDOS, RADIO_TIERRA_M
from src.ingestion.validador import validar_conjunto
from src.model import costa
from src.model.campos import CamposMalla, CamposUniformes
from src.model.conversiones import desde_a_vector
from src.model.metricas import resumir
from src.model.simulacion import A_FLOTE, FUERA, VARADA, Parametros, PuntoInvalido, simular
from tests.conftest import sin_tierra

DOMINIO_ABIERTO = (-100.0, -70.0, 5.0, 35.0)
LIBERACION = dict(lon=-86.0, lat=21.0)


def grados_lon(m, lat):
    return np.degrees(m / (RADIO_TIERRA_M * np.cos(np.radians(lat))))


def grados_lat(m):
    return np.degrees(m / RADIO_TIERRA_M)


def correr(campos, **kw):
    p = Parametros(**{**LIBERACION, "radio_km": 3.0, "particulas": 300, "kh_m2s": 0.0, "horizonte_h": 48, **kw})
    return simular(campos, p, en_tierra=sin_tierra, dominio=DOMINIO_ABIERTO)


# --- Solución analítica con K_h = 0 y viento constante (modelo 0.2.0: u_c = 0) ----
# X(t+Δt) = X(t) + α·u_w·Δt  ⇒  desplazamiento = α·|u_w|·t en la dirección HACIA la que sopla.

def test_viento_del_sur_empuja_al_norte():
    # 8 m/s DESDE el sur (180°) con α = 1.5 % → 0.12 m/s hacia el norte.
    uw, vw = desde_a_vector(8.0, 180.0)
    r = correr(CamposUniformes(uw=float(uw), vw=float(vw)), alpha_pct=1.5)
    assert np.allclose(r.lat[-1] - r.lat[0], grados_lat(0.12 * PASO_SEGUNDOS * 48), rtol=1e-12, atol=1e-12)
    assert np.allclose(r.lon[-1], r.lon[0], atol=1e-12)


def test_viento_del_oeste_empuja_al_este():
    # 10 m/s DESDE el oeste (270°) con α = 2 % → 0.2 m/s hacia el este (con cos(lat) de cada partícula).
    uw, vw = desde_a_vector(10.0, 270.0)
    r = correr(CamposUniformes(uw=float(uw), vw=float(vw)), alpha_pct=2.0)
    assert np.allclose(r.lon[-1] - r.lon[0], grados_lon(0.2 * PASO_SEGUNDOS * 48, r.lat[0]), rtol=1e-9)
    assert np.allclose(r.lat[-1], r.lat[0], atol=1e-12)


def test_viento_diagonal_distancia_analitica():
    # 6 m/s DESDE el SO (225°) con α = 1 % → 0.06 m/s hacia el NE durante 24 h.
    uw, vw = desde_a_vector(6.0, 225.0)
    r = correr(CamposUniformes(uw=float(uw), vw=float(vw)), alpha_pct=1.0, horizonte_h=24)
    componente = 0.06 / np.sqrt(2) * PASO_SEGUNDOS * 24
    assert np.allclose(r.lat[-1] - r.lat[0], grados_lat(componente), rtol=1e-12)
    este_m = np.radians(r.lon[-1] - r.lon[0]) * RADIO_TIERRA_M * np.cos(np.radians(0.5 * (r.lat[0] + r.lat[-1])))
    assert np.allclose(este_m, componente, rtol=1e-3)


def test_alpha_cero_sin_corriente_no_hay_movimiento():
    uw, vw = desde_a_vector(12.0, 90.0)
    r = correr(CamposUniformes(uw=float(uw), vw=float(vw)), alpha_pct=0.0)
    assert np.array_equal(r.lon[-1], r.lon[0]) and np.array_equal(r.lat[-1], r.lat[0])


def test_corriente_opcional_se_suma_al_viento():
    # El término u_c sigue implementado para conectar CMEMS/HYCOM: 0.3 m/s al N + 0.08 m/s de viento al N.
    uw, vw = desde_a_vector(8.0, 180.0)
    r = correr(CamposUniformes(vc=0.3, uw=float(uw), vw=float(vw)), alpha_pct=1.0, horizonte_h=24)
    assert np.allclose(r.lat[-1] - r.lat[0], grados_lat(0.38 * PASO_SEGUNDOS * 24), rtol=1e-12)
    assert any("u_c del conjunto" in l for l in r.bitacora)


def test_sin_forzamiento_ni_difusion_no_hay_movimiento():
    r = correr(CamposUniformes(), alpha_pct=4.0)
    assert np.array_equal(r.lon[-1], r.lon[0]) and np.array_equal(r.lat[-1], r.lat[0])


# --- Reproducibilidad y estocástica ------------------------------------------

def test_misma_semilla_mismo_resultado():
    campos = CamposUniformes(uw=20.0, vw=10.0)  # α = 1 % → 0.2 y 0.1 m/s
    a = correr(campos, kh_m2s=10.0, semilla=42)
    b = correr(campos, kh_m2s=10.0, semilla=42)
    c = correr(campos, kh_m2s=10.0, semilla=43)
    assert np.array_equal(a.lon, b.lon) and np.array_equal(a.lat, b.lat)
    assert not np.array_equal(a.lon, c.lon)


def test_dispersion_crece_con_el_tiempo_y_sigue_a_la_teoria():
    k_h = 10.0
    p = Parametros(**LIBERACION, radio_km=0.5, particulas=5000, kh_m2s=k_h, horizonte_h=120, semilla=1)
    r = simular(CamposUniformes(uw=10.0), p, en_tierra=sin_tierra, dominio=DOMINIO_ABIERTO)
    km_x = np.radians(r.lon - r.lon[0].mean()) * RADIO_TIERRA_M * np.cos(np.radians(21.0)) / 1000
    std = km_x.std(axis=1)
    assert std[24] < std[48] < std[72] < std[120]
    # Difusión pura: σ = √(2·K_h·t) por eje (más la varianza del disco inicial, R²/4).
    teorico = np.sqrt(2 * k_h * 120 * 3600 + (500.0 ** 2) / 4) / 1000
    assert std[120] == pytest.approx(teorico, rel=0.05)


def test_difusion_cero_no_dispersa():
    r = correr(CamposUniformes(uw=30.0), kh_m2s=0.0, radio_km=0.5)
    # Sin difusión el conglomerado solo se traslada; el ancho en grados cambia apenas
    # (< 0.1 %) porque cada partícula usa el cos(lat) de su propia latitud.
    ancho0 = np.ptp(r.lon[0])
    assert np.ptp(r.lon[-1]) == pytest.approx(ancho0, rel=1e-3)
    assert np.ptp(r.lat[-1]) == pytest.approx(np.ptp(r.lat[0]), rel=1e-12)


# --- Costa y dominio ---------------------------------------------------------

@pytest.fixture(scope="module")
def campos_cancun(semar_base):
    _reporte, datos = validar_conjunto(semar_base)
    return datos


# --- Campos de SEMAR: estacionarios, interpolación y corriente opcional --------

def test_viento_estacionario_igual_en_t0_y_t120(campos_cancun):
    campos = CamposMalla(campos_cancun)
    lon, lat = np.array([-86.6, -86.4]), np.array([21.1, 20.8])
    v0 = campos.velocidades(lon, lat, 0.0)
    v120 = campos.velocidades(lon, lat, 120.0)
    assert np.array_equal(np.hypot(v0[2], v0[3]), np.hypot(v120[2], v120[3]))
    assert np.hypot(v0[2], v0[3]).min() > 3.0


def test_sin_corrientes_uc_es_cero(campos_cancun):
    campos = CamposMalla(campos_cancun)
    uc, vc, uw, _ = campos.velocidades(np.array([-86.6]), np.array([21.1]), 10.0)
    assert not campos.hay_corriente and uc[0] == 0.0 and vc[0] == 0.0 and uw[0] != 0.0
    r = simular(campos, Parametros(lon=-86.5, lat=21.0, particulas=100, horizonte_h=24),
                dominio=(-87.52, -86.08, 20.12, 21.72))
    assert any("u_c = 0" in l for l in r.bitacora)


def test_viento_con_varias_horas_se_interpola_en_el_tiempo(semar):
    from scripts.generar_fixtures import escribir_salidadatos
    escribir_salidadatos(semar / ARCHIVO_VIENTO, horas=(0, 60, 120))
    _r, datos = validar_conjunto(semar)
    campos = CamposMalla(datos)
    lon, lat = np.array([-86.6]), np.array([21.1])
    v0, v30, v60 = (campos.velocidades(lon, lat, t)[2] for t in (0.0, 30.0, 60.0))
    assert v30[0] == pytest.approx(0.5 * (v0[0] + v60[0]), rel=1e-9)
    assert v0[0] != v60[0]


def test_interpolacion_ignora_nodos_de_tierra(campos_cancun):
    """Junto a la costa el viento no se diluye con los nodos sin dato (tierra = NaN)."""
    d = campos_cancun
    campos = CamposMalla(d)
    i, j = next((i, j) for i in range(d.lats.size - 1) for j in range(d.lons.size - 1)
                if d.mar[i, j] and not d.mar[i, j + 1])  # nodo de mar con vecino de tierra al este
    lon = d.lons[j] + 0.25 * (d.lons[1] - d.lons[0])
    _, _, uw, vw = campos.velocidades(np.array([lon]), np.array([d.lats[i]]), 0.0)
    assert np.hypot(uw, vw)[0] == pytest.approx(float(d.viento_vel[0, i, j]), rel=0.02)


def test_ninguna_particula_queda_sobre_tierra(campos_cancun):
    d = campos_cancun
    dominio = (float(d.lons[0]), float(d.lons[-1]), float(d.lats[0]), float(d.lats[-1]))
    p = Parametros(lon=-86.70, lat=21.08, radio_km=8.0, particulas=2000, alpha_pct=4.0, kh_m2s=30.0, horizonte_h=120, semilla=3)
    r = simular(CamposMalla(d), p, dominio=dominio)
    varadas = r.estado == VARADA
    assert varadas.mean() > 0.2, "con α = 4 % y viento del E una parte debe varar"
    for h in range(r.horas + 1):
        assert not costa.en_tierra(r.lon[h], r.lat[h]).any(), f"partícula sobre tierra en +{h} h"
    # Las varadas quedan pegadas a la costa (< 1 km) y no se mueven después de varar.
    assert costa.distancia_costa_km(r.lon[-1, varadas], r.lat[-1, varadas]).max() < 1.0
    n = np.flatnonzero(varadas)[0]
    hv = r.hora_varada[n]
    assert np.all(r.lon[hv:, n] == r.lon[hv, n])


def test_particulas_que_salen_del_dominio_se_congelan_en_el_borde():
    dominio = (-86.5, -85.5, 20.5, 21.5)
    p = Parametros(lon=-86.0, lat=21.0, radio_km=2.0, particulas=200, alpha_pct=4.0, kh_m2s=0.0, horizonte_h=48)
    r = simular(CamposUniformes(vw=25.0), p, en_tierra=sin_tierra, dominio=dominio)
    assert np.all(r.estado == FUERA)
    assert np.allclose(r.lat[-1], 21.5)
    assert np.all(r.hora_fuera > 0)


def test_punto_en_tierra_o_fuera_del_dominio_es_invalido():
    with pytest.raises(PuntoInvalido, match="tierra"):
        simular(CamposUniformes(), Parametros(lon=-88.5, lat=20.5))
    with pytest.raises(PuntoInvalido, match="fuera del dominio"):
        simular(CamposUniformes(), Parametros(lon=-80.0, lat=20.5))


def test_particulas_iniciales_en_tierra_se_reubican():
    # Liberación pegada a la costa de Cancún con radio grande: parte del disco cae en tierra.
    p = Parametros(lon=-86.72, lat=21.14, radio_km=15.0, particulas=1000, horizonte_h=24, kh_m2s=0.0)
    r = simular(CamposUniformes(), p)
    assert r.reubicadas_inicio > 0
    assert not costa.en_tierra(r.lon[0], r.lat[0]).any()


def test_costa_reconoce_tierra_y_mar():
    lon = np.array([-86.62, -88.50, -86.90, -84.50, -89.60])
    lat = np.array([21.15, 20.50, 20.42, 22.30, 20.90])
    assert costa.en_tierra(lon, lat).tolist() == [False, True, True, False, True]
    assert costa.zona_costera(np.array([-86.75, -86.95, -87.42]), np.array([21.10, 20.60, 20.20])).tolist() == \
        ["cancun", "cozumel", "tulum"]


# --- Métricas ----------------------------------------------------------------

def test_resumen_consistente(campos_cancun):
    d = campos_cancun
    dominio = (float(d.lons[0]), float(d.lons[-1]), float(d.lats[0]), float(d.lats[-1]))
    p = Parametros(lon=-86.66, lat=21.12, particulas=1000, horizonte_h=120)
    r = simular(CamposMalla(d), p, dominio=dominio)
    s = resumir(r)
    assert s["a_flote_pct"] + s["varadas_pct"] + s["fuera_pct"] == pytest.approx(100.0, abs=0.2)
    assert sum(a["particulas"] for a in s["arribos"]) == int((r.estado == VARADA).sum())
    assert all(0 <= a["probabilidad"] <= 1 for a in s["arribos"])
    assert len(s["series"]["centroide"]) == 121
    assert set(s["radio_p90_km"]) == {"24", "48", "72", "96", "120"}
    assert any("probabilístico" in a for a in s["advertencias"])
    a_flote_final = r.estado == A_FLOTE
    if a_flote_final.mean() > 0.01:
        cx, cy = s["series"]["centroide"][-1]
        assert cx == pytest.approx(r.lon[-1, a_flote_final].mean(), abs=1e-4)
        assert cy == pytest.approx(r.lat[-1, a_flote_final].mean(), abs=1e-4)
