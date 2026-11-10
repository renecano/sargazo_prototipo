"""Costa del modelo (máscara de ~105 m derivada de OpenStreetMap), varamiento y tramos.

Regresión de la observación 1 de SEMAR: el modelo marcaba contacto con tierra donde no la
hay porque su costa era un polígono dibujado a mano. Aquí se fija que (a) los puntos de mar
que antes eran «tierra» ya son mar, (b) las islas existen y tienen su propio tramo, (c) lo
que vara queda pegado a la costa de la máscara y nunca sobre tierra, y (d) ninguna partícula
salta una franja angosta de tierra ni la cruza al animar entre horas guardadas.
"""
import hashlib

import numpy as np
import pytest

from src.api.almacen import codificar_posiciones, decodificar_posiciones
from src.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from src.ingestion.validador import validar_conjunto
from src.model import costa
from src.model.campos import CamposOleaje, OleajeUniforme
from src.model.metricas import resumir
from src.model.simulacion import A_FLOTE, VARADA, Parametros, simular, validar_punto
from tests.conftest import solo_con_datos_reales

# (lat, lon). Mar real que la costa manual de la v0.4.0 marcaba como tierra.
MAR_QUE_ANTES_ERA_TIERRA = {
    "Bahía de Mujeres": (21.188, -86.768),
    "Bahía de la Ascensión": (19.70, -87.55),
    "Bahía de Chetumal": (18.40, -88.10),
    "Laguna de Yalahau": (21.48, -87.30),
}
MAR = {
    "canal de Cozumel": (20.50, -87.10),
    "canal entre Isla Mujeres y el continente": (21.24, -86.77),
    "frente a Punta Cancún": (21.13, -86.72),
    "frente a Tulum": (20.20, -87.40),
    "frente a Mahahual": (18.71, -87.68),
    "Caribe abierto": (20.00, -85.50),
    "Golfo de México": (22.50, -90.00),
}
TIERRA = {
    "Mérida": (20.97, -89.62),
    "centro de Cancún": (21.16, -86.83),
    "Cozumel": (20.43, -86.90),
    "Isla Mujeres": (21.235, -86.737),
    "Holbox": (21.535, -87.30),
    "Chetumal": (18.51, -88.31),
    "Cayo Centro (Banco Chinchorro)": (18.59, -87.32),
    "Isla Pérez (Arrecife Alacranes)": (22.383, -89.683),
    "Cuba": (22.20, -84.20),
}


def _en_tierra(lat, lon):
    return bool(costa.en_tierra(np.array([lon]), np.array([lat]))[0])


# --- La máscara -----------------------------------------------------------------------

def test_la_mascara_es_la_que_dice_su_procedencia():
    m, p = costa.mascara(), costa.procedencia()
    assert (m.ny, m.nx, m.paso) == (6320, 8240, 0.001) and m.bits.shape == (6320, 1030)
    assert hashlib.sha256(m.bits.tobytes()).hexdigest() == p["costa"]["sha256_bits"]
    assert p["costa"]["licencia"] == "ODbL 1.0" and "OpenStreetMap" in p["costa"]["atribucion"]
    assert hashlib.sha256(costa.mascara_contexto().bits.tobytes()).hexdigest() == p["contexto"]["sha256_bits"]


def test_la_mascara_cubre_el_dominio_con_margen():
    m = costa.mascara()
    assert m.lon0 < LON_MIN and m.lat0 < LAT_MIN
    assert m.lon0 + m.nx * m.paso > LON_MAX and m.lat0 + m.ny * m.paso > LAT_MAX


@pytest.mark.parametrize("nombre", MAR_QUE_ANTES_ERA_TIERRA)
def test_mar_que_la_costa_anterior_marcaba_como_tierra(nombre):
    lat, lon = MAR_QUE_ANTES_ERA_TIERRA[nombre]
    assert not _en_tierra(lat, lon), f"{nombre} es mar"
    validar_punto(lon, lat)      # ya se puede liberar ahí: no lanza PuntoInvalido


@pytest.mark.parametrize("nombre", MAR)
def test_puntos_claramente_en_el_mar(nombre):
    assert not _en_tierra(*MAR[nombre]), nombre


@pytest.mark.parametrize("nombre", TIERRA)
def test_puntos_claramente_en_tierra_incluidas_las_islas(nombre):
    assert _en_tierra(*TIERRA[nombre]), nombre


def test_fuera_de_la_mascara_todo_es_mar_y_admite_arreglos():
    lon = np.array([[-100.0, -86.83], [-86.0, -70.0]])
    lat = np.array([[20.0, 21.16], [21.0, 30.0]])
    assert costa.en_tierra(lon, lat).tolist() == [[False, True], [False, False]]


def test_la_tierra_del_dominio_mide_lo_que_la_referencia_independiente():
    """GSHHG (resolución completa) da 189 183 km² de tierra en el dominio; la máscara, ±1 %."""
    m = costa.mascara()
    lon, lat = m.centros()
    fil, col = (lat >= LAT_MIN) & (lat <= LAT_MAX), (lon >= LON_MIN) & (lon <= LON_MAX)
    km = m.paso * 111.195
    area = float((m.a_bool()[np.ix_(fil, col)].sum(axis=1) * km * km * np.cos(np.radians(lat[fil]))).sum())
    assert area == pytest.approx(189_183, rel=0.01)
    assert round(area) == costa.procedencia()["costa"]["area_tierra_dominio_km2"]


def test_distancia_a_la_costa():
    d = costa.distancia_costa_km(np.array([-86.83, -86.72, -85.50]), np.array([21.16, 21.13, 20.00]))
    assert d[0] == 0.0, "en tierra la distancia es 0"
    assert 1.0 < d[1] < 3.5, "Punta Cancún queda a ~2 km"
    assert d[2] > 100


# --- Tramos de costa -------------------------------------------------------------------

def test_cada_isla_tiene_su_tramo_y_el_continente_el_suyo():
    lon = np.array([-86.95, -86.737, -86.79, -87.32, -89.68, -86.76, -87.07, -87.46, -87.71, -88.30, -84.50, -90.54])
    lat = np.array([20.51, 21.235, 21.49, 18.59, 22.38, 21.13, 20.63, 20.21, 18.71, 18.50, 22.00, 19.84])
    assert costa.zona_costera(lon, lat).tolist() == [
        "cozumel", "isla_mujeres", "contoy", "chinchorro", "banco_campeche", "cancun", "playa_del_carmen",
        "tulum", "mahahual", "bahia_chetumal", "cuba", "campeche"]
    assert costa.zona_costera([], []).size == 0
    assert len({z["id"] for z in costa.ZONAS}) == len(costa.ZONAS) and all(z["limites"] for z in costa.ZONAS)


def test_los_recuadros_de_las_islas_no_se_llevan_costa_del_continente():
    """Con la máscara real: en los tramos de isla no hay ni una celda de costa del continente,
    y la costa de Cozumel, Isla Mujeres y Contoy cae entera en su tramo."""
    from scipy import ndimage

    m = costa.mascara()
    etiquetas, _ = ndimage.label(m.a_bool())
    continente = int(np.bincount(etiquetas.ravel())[1:].argmax()) + 1
    lon, lat = costa.celdas_de_costa()
    en_dominio = (lon >= LON_MIN) & (lon <= LON_MAX) & (lat >= LAT_MIN) & (lat <= LAT_MAX)
    lon, lat = lon[en_dominio], lat[en_dominio]
    componente = etiquetas[np.floor((lat - m.lat0) / m.paso).astype(int), np.floor((lon - m.lon0) / m.paso).astype(int)]
    zona = costa.zona_costera(lon, lat)
    for isla in ("cuba", "banco_campeche", "chinchorro", "cozumel", "isla_mujeres", "contoy"):
        assert (zona == isla).sum() > 50, isla
        assert not ((zona == isla) & (componente == continente)).any(), f"{isla} incluye costa del continente"
    for isla, (la, lo) in {"cozumel": (20.43, -86.90), "isla_mujeres": (21.235, -86.737), "contoy": (21.48, -86.791)}.items():
        c = etiquetas[int((la - m.lat0) / m.paso), int((lo - m.lon0) / m.paso)]
        assert c not in (0, continente)
        assert set(zona[componente == c]) == {isla}
    for tramo in ("cancun", "puerto_morelos", "akumal", "tulum"):
        assert (componente[zona == tramo] == continente).all(), f"{tramo} es costa del continente"


# --- Varamiento ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    conjunto = validar_conjunto(__import__("src.config", fromlist=["DIR_SEMAR"]).DIR_SEMAR)[1]
    dominio = (float(conjunto.lons[0]), float(conjunto.lons[-1]), float(conjunto.lats[0]), float(conjunto.lats[-1]))
    return CamposOleaje(conjunto), dominio


@solo_con_datos_reales
def test_caso_de_semar_lo_varado_queda_en_la_costa_y_no_en_el_mar(real):
    """El caso que reprodujo el error: Cancún, 2 000 partículas, 120 h. Antes el 41.5 % de las
    «varadas» quedaba a más de 1 km de tierra (hasta 3.8 km, en la Bahía de Mujeres)."""
    campos, dominio = real
    r = simular(campos, Parametros(lon=-86.66, lat=21.12), dominio=dominio)
    varadas = r.estado == VARADA
    assert varadas.mean() > 0.95, "la ola empuja hacia la costa: casi todo debe varar"
    x, y = r.lon[-1, varadas], r.lat[-1, varadas]
    assert not costa.en_tierra(x, y).any(), "varada = último punto en el mar"
    assert costa.distancia_costa_km(x, y).max() < 0.15, "a menos de 150 m de una celda de tierra"
    # Ninguna se queda en medio de la Bahía de Mujeres, donde estaba la costa manual.
    assert not ((np.abs(x + 86.768) < 0.01) & (np.abs(y - 21.188) < 0.01)).any()
    s = resumir(r)
    assert s["arribos"][0]["zona"] == "cancun"
    assert {a["zona"] for a in s["arribos"]} <= {"cancun", "costa_mujeres", "isla_mujeres", "puerto_morelos"}


@solo_con_datos_reales
def test_isla_mujeres_y_cozumel_reciben_arribos_propios(real):
    campos, dominio = real
    s = resumir(simular(campos, Parametros(lon=-86.40, lat=21.10), dominio=dominio))
    assert "isla_mujeres" in {a["zona"] for a in s["arribos"]}
    r = simular(campos, Parametros(lon=-86.60, lat=20.40, horizonte_h=72), dominio=dominio)   # al este de Cozumel
    s = resumir(r)
    assert s["arribos"][0]["zona"] == "cozumel" and s["arribos"][0]["probabilidad"] > 0.5
    en_la_isla = r.estado == VARADA
    assert (r.lon[-1, en_la_isla] > -87.06).all(), "lo que vara en Cozumel no aparece en el continente"


def test_mar_abierto_con_ola_hacia_afuera_no_vara():
    p = Parametros(lon=-85.80, lat=20.00, particulas=500, horizonte_h=48)
    r = simular(OleajeUniforme(altura=1.0, direccion_desde=270.0), p)      # la ola viaja al este
    assert not (r.estado == VARADA).any()


def test_ninguna_particula_salta_una_franja_angosta_de_tierra():
    """Franja de 150 m. Con γ = 3 y H = 2 m el paso es de ~1.5 km: revisando 4 puntos por paso
    (cada ~375 m, como en la v0.4.0) parte de las partículas la saltaba."""
    borde_este = -86.000

    def franja(lon, lat):
        return (np.asarray(lon) <= borde_este) & (np.asarray(lon) > borde_este - 0.0015)

    p = Parametros(lon=-85.95, lat=21.0, radio_km=3.0, particulas=1500, gamma=3.0, kh_m2s=0.0, horizonte_h=12)
    r = simular(OleajeUniforme(altura=2.0, direccion_desde=90.0), p, en_tierra=franja, dominio=(-100.0, -70.0, 5.0, 35.0))
    assert (r.estado == VARADA).all()
    assert (r.lon[-1] > borde_este).all(), "todas quedan del lado de donde venían"
    assert (r.lon[-1] - borde_este).max() < 1e-4, "y pegadas a la franja (bisección)"


@solo_con_datos_reales
def test_la_animacion_en_linea_recta_entre_horas_no_cruza_tierra(real):
    """La interfaz interpola posiciones entre las horas guardadas. Ese segmento es el mismo que
    revisó el integrador, así que ningún punto intermedio de una partícula a flote o que está
    por varar cae en tierra."""
    campos, dominio = real
    r = simular(campos, Parametros(lon=-86.66, lat=21.12, particulas=1500, kh_m2s=30.0), dominio=dominio)
    for h in range(r.horas):
        mueve = r.estado_en(h) == A_FLOTE
        for f in np.linspace(0.0, 1.0, 9):
            x = r.lon[h, mueve] + f * (r.lon[h + 1, mueve] - r.lon[h, mueve])
            y = r.lat[h, mueve] + f * (r.lat[h + 1, mueve] - r.lat[h, mueve])
            assert not costa.en_tierra(x, y).any(), f"cruza tierra entre +{h} y +{h + 1} h (fracción {f})"


@solo_con_datos_reales
def test_las_posiciones_guardadas_no_se_meten_a_tierra_al_cuantizarse(real):
    """El registro guarda las posiciones cada 0.0002° (~22 m). Una partícula varada queda a
    centímetros de la costa y el redondeo simple metía en tierra a 1 de cada 10: ahora lo
    que la interfaz dibuja sigue en el mar, a no más de un escalón de donde estaba."""
    campos, dominio = real
    r = simular(campos, Parametros(lon=-86.66, lat=21.12, particulas=1000), dominio=dominio)
    assert not costa.en_tierra(r.lon, r.lat).any()
    redondeo_simple = costa.en_tierra(np.round((r.lon + 92.08) * 5000) / 5000 - 92.08, np.round((r.lat - 16.92) * 5000) / 5000 + 16.92)
    assert redondeo_simple.any(), "el caso sí ejercita la corrección"
    lon, lat = decodificar_posiciones(codificar_posiciones(r.lon, r.lat))
    assert not costa.en_tierra(lon, lat).any()
    assert np.abs(lon - r.lon).max() <= 0.0002 + 1e-9 and np.abs(lat - r.lat).max() <= 0.0002 + 1e-9
    assert np.median(np.abs(lon - r.lon)) <= 0.0001


# --- Localidades -----------------------------------------------------------------------

def test_localidades_con_fuente_y_en_el_dominio():
    locs = costa.localidades()
    nombres = {l["nombre"] for l in locs}
    for esperado in ("Cancún", "Isla Mujeres", "Puerto Morelos", "Playa del Carmen", "San Miguel de Cozumel", "Tulum",
                     "Mahahual", "Chetumal", "Holbox", "Xcalak", "Progreso", "Mérida"):
        assert esperado in nombres, esperado
    for l in locs:
        assert l["osm"].split("/")[0] in ("node", "way", "relation") and l["osm"].split("/")[1].isdigit(), l
        assert LON_MIN <= l["lon"] <= LON_MAX and LAT_MIN <= l["lat"] <= LAT_MAX
        assert l["rango"] in (1, 2, 3, 4)
    cancun = next(l for l in locs if l["nombre"] == "Cancún")
    assert cancun["lat"] == pytest.approx(21.15, abs=0.05) and cancun["lon"] == pytest.approx(-86.84, abs=0.05)
    assert costa.procedencia()["localidades"]["licencia"] == "ODbL 1.0"
