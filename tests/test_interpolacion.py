"""Las tres interpolaciones del modelo contra casos analíticos (observación 2 de SEMAR).

  a) Espacial: del nodo de la malla de 0.16° a la posición de la partícula.
  b) Temporal: entre bloques de 3 h del dirmarea.txt.
  c) Integración en el tiempo (RK2) contra soluciones exactas.

La interpolación visual entre horas guardadas se prueba en tests/test_costa.py (no cruza
tierra) y en tests/e2e (la interfaz usa las mismas reglas que el modelo).
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from src.config import COEF_STOKES, PASO_SEGUNDOS, RADIO_TIERRA_M
from src.ingestion.lector import ConjuntoDatos
from src.model.campos import CamposOleaje, deriva_hacia, extender_a_la_costa, magnitud_stokes
from src.model.simulacion import integrar
from tests.conftest import sin_tierra

LON0, LAT0, PASO = -86.08, 20.12, 0.16     # nodos como los de SEMAR: múltiplos de 0.16° más un residuo
DOMINIO_ABIERTO = (-100.0, -70.0, 5.0, 35.0)


def conjunto(altura, direccion, horas=(0.0,)):
    """ConjuntoDatos mínimo: arreglos [bloque, lat, lon] sobre una malla de 0.16°."""
    altura = np.asarray(altura, dtype=float)
    direccion = np.broadcast_to(np.asarray(direccion, dtype=float), altura.shape).copy()
    nb, ny, nx = altura.shape
    return ConjuntoDatos(
        lons=LON0 + PASO * np.arange(nx), lats=LAT0 + PASO * np.arange(ny),
        fecha_base=datetime(2026, 10, 1, tzinfo=timezone.utc), horas=np.asarray(horas, dtype=float),
        altura=altura, direccion=direccion, mar=np.isfinite(altura[0]), archivo="prueba",
        huella_sha256="0" * 64, bloques_identicos=False)


def malla(nx=6, ny=5):
    return np.meshgrid(LON0 + PASO * np.arange(nx), LAT0 + PASO * np.arange(ny))


def plano(x, y):
    return 1.0 + 0.8 * (x - LON0) + 0.5 * (y - LAT0)


# --- a) Espacial ---------------------------------------------------------------------------

def test_bilineal_reproduce_exactamente_un_campo_lineal():
    x, y = malla()
    campos = CamposOleaje(conjunto(plano(x, y)[None], 100.0))
    rng = np.random.default_rng(7)
    px = LON0 + rng.random(500) * PASO * 5
    py = LAT0 + rng.random(500) * PASO * 4
    h, d = campos.ola(px, py, 0.0)
    assert np.allclose(h, plano(px, py), rtol=0, atol=1e-12)
    assert np.allclose(d, 100.0, atol=1e-9)


def test_en_los_nodos_devuelve_el_valor_del_nodo_sin_desfase():
    """Los valores están EN (LON, LAT): en un nodo no se mezcla nada de sus vecinos."""
    rng = np.random.default_rng(3)
    x, y = malla()
    altura = 0.5 + rng.random(x.shape)
    direccion = 80.0 + 40.0 * rng.random(x.shape)
    campos = CamposOleaje(conjunto(altura[None], direccion[None]))
    h, d = campos.ola(x, y, 0.0)
    assert np.allclose(h, altura, atol=1e-12) and np.allclose(d, direccion, atol=1e-9)
    # A media celda (0.08°) el valor es el promedio de los dos nodos: no hay desfase de media celda.
    h_medio, _ = campos.ola(x[:, :-1] + PASO / 2, y[:, :-1], 0.0)
    assert np.allclose(h_medio, 0.5 * (altura[:, :-1] + altura[:, 1:]), atol=1e-12)


def test_es_continua_al_cruzar_de_una_celda_a_otra():
    rng = np.random.default_rng(5)
    x, y = malla()
    campos = CamposOleaje(conjunto((0.5 + rng.random(x.shape))[None], (90 + 30 * rng.random(x.shape))[None]))
    borde = LON0 + 2 * PASO
    py = LAT0 + rng.random(200) * PASO * 4
    ha, da = campos.ola(np.full(200, borde - 1e-9), py, 0.0)
    hb, db = campos.ola(np.full(200, borde + 1e-9), py, 0.0)
    assert np.allclose(ha, hb, atol=1e-6) and np.allclose(da, db, atol=1e-4)


def test_fuera_de_la_malla_usa_el_nodo_del_borde():
    x, y = malla()
    campos = CamposOleaje(conjunto(plano(x, y)[None], 100.0))
    h, _ = campos.ola(np.array([LON0 - 1.0, LON0 + 99.0]), np.array([LAT0 + 0.1, LAT0 - 5.0]), 0.0)
    assert h[0] == pytest.approx(plano(LON0, LAT0 + 0.1), abs=1e-12)
    assert h[1] == pytest.approx(plano(LON0 + 5 * PASO, LAT0), abs=1e-12)


def test_la_direccion_se_promedia_por_seno_y_coseno():
    x, _ = malla(2, 2)
    campos = CamposOleaje(conjunto(np.ones((1, 2, 2)), np.array([[[350.0, 10.0], [350.0, 10.0]]])))
    _, d = campos.ola(np.array([LON0 + PASO / 2, LON0 + PASO / 4]), np.array([LAT0, LAT0]), 0.0)
    assert min(d[0], 360 - d[0]) == pytest.approx(0.0, abs=1e-9), "350° y 10° promedian 0°, no 180°"
    esperado = np.degrees(np.arctan2(0.75 * np.sin(np.radians(350)) + 0.25 * np.sin(np.radians(10)),
                                     0.75 * np.cos(np.radians(350)) + 0.25 * np.cos(np.radians(10)))) % 360
    assert d[1] == pytest.approx(esperado, abs=1e-9)


def test_direcciones_opuestas_no_inventan_un_rumbo():
    """90° y 270° a partes iguales se cancelan: no hay dirección y la deriva es cero (antes
    salía 0°, «del norte», con la rapidez completa)."""
    campos = CamposOleaje(conjunto(np.ones((1, 2, 2)), np.array([[[90.0, 270.0], [90.0, 270.0]]])))
    medio = (np.array([LON0 + PASO / 2]), np.array([LAT0 + PASO / 2]))
    h, d = campos.ola(*medio, 0.0)
    assert h[0] == pytest.approx(1.0) and np.isnan(d[0])
    u, v = campos.velocidades(*medio, 0.0)
    assert u[0] == 0.0 and v[0] == 0.0
    # A un cuarto de celda sí hay rumbo: gana el nodo más cercano, con la rapidez de H = 1 m.
    u, v = campos.velocidades(np.array([LON0 + PASO / 4]), np.array([LAT0]), 0.0)
    assert u[0] == pytest.approx(-COEF_STOKES, rel=1e-9) and v[0] == pytest.approx(0.0, abs=1e-12)


def test_la_deriva_usa_la_altura_y_la_direccion_interpoladas():
    rng = np.random.default_rng(11)
    x, y = malla()
    campos = CamposOleaje(conjunto((0.3 + rng.random(x.shape))[None], (60 + 80 * rng.random(x.shape))[None]))
    px, py = LON0 + rng.random(300) * PASO * 5, LAT0 + rng.random(300) * PASO * 4
    h, d = campos.ola(px, py, 0.0)
    u, v = campos.velocidades(px, py, 0.0)
    ue, ve = deriva_hacia(h, d)
    assert np.allclose(u, ue, atol=1e-12) and np.allclose(v, ve, atol=1e-12)
    assert np.allclose(np.hypot(u, v), magnitud_stokes(h), atol=1e-12)


# --- Nodos de tierra y franja costera ----------------------------------------------------------

def test_los_nodos_sin_dato_no_diluyen_la_altura():
    altura = np.full((1, 3, 3), 2.0)
    altura[0, :, 2] = np.nan                       # columna de tierra al este
    campos = CamposOleaje(conjunto(altura, 100.0), nodos_extrapolacion=0)
    h, _ = campos.ola(np.array([LON0 + 1.75 * PASO]), np.array([LAT0 + 0.5 * PASO]), 0.0)
    assert h[0] == pytest.approx(2.0), "a un cuarto de celda de la tierra la ola sigue siendo de 2 m, no de 0.5 m"


def test_sin_extender_la_celda_entre_cuatro_nodos_de_tierra_no_tiene_ola():
    altura = np.full((1, 4, 5), 1.0)
    altura[0, :, 2:] = np.nan
    campos = CamposOleaje(conjunto(altura, 90.0), nodos_extrapolacion=0)
    dentro = (np.array([LON0 + 2.5 * PASO]), np.array([LAT0 + 1.5 * PASO]))
    assert np.isnan(campos.ola(*dentro, 0.0)[0][0])
    assert campos.velocidades(*dentro, 0.0)[0][0] == 0.0, "sin ola la partícula se quedaba sin deriva"


def test_la_ola_se_extiende_dos_nodos_hacia_la_costa_y_no_mas():
    altura = np.full((1, 4, 7), np.nan)
    altura[0, :, 0] = 1.0
    altura[0, :, 1] = 2.0                           # mar: columnas 0 y 1; «tierra»: 2 a 6
    direccion = np.full((1, 4, 7), 90.0)
    c = conjunto(altura, direccion)
    campos = CamposOleaje(c)
    assert campos.extrapolado[0, :, 2].all() and campos.extrapolado[0, :, 3].all()
    assert not campos.extrapolado[0, :, :2].any() and not campos.extrapolado[0, :, 4:].any()
    assert np.allclose(campos.altura[0, :, 2], 2.0), "primer nodo: promedio de sus vecinos con dato"
    assert np.allclose(campos.altura[0, :, 3], 2.0), "segundo nodo: promedio del primero"
    assert np.isnan(campos.altura[0, :, 4:]).all(), "más allá de dos nodos no se inventa ola"
    assert np.allclose(campos.altura[0, :, :2], altura[0, :, :2]), "los nodos con dato no cambian"
    y = np.array([LAT0 + 1.5 * PASO])
    u, _ = campos.velocidades(np.array([LON0 + 2.5 * PASO]), y, 0.0)
    assert u[0] == pytest.approx(-COEF_STOKES * np.sqrt(2.0)), "en la franja costera sigue habiendo deriva"
    u, v = campos.velocidades(np.array([LON0 + 5.5 * PASO]), y, 0.0)
    assert u[0] == 0.0 and v[0] == 0.0


def test_extender_promedia_la_direccion_por_seno_y_coseno():
    altura = np.array([[[1.0, np.nan, 3.0]]])
    rad = np.radians(np.array([[[350.0, 0.0, 10.0]]]))
    h, s, c, extr = extender_a_la_costa(altura, np.sin(rad), np.cos(rad), pasadas=1)
    assert extr[0, 0].tolist() == [False, True, False] and h[0, 0, 1] == pytest.approx(2.0)
    assert np.degrees(np.arctan2(s[0, 0, 1], c[0, 0, 1])) == pytest.approx(0.0, abs=1e-9)
    assert np.hypot(s[0, 0, 1], c[0, 0, 1]) == pytest.approx(1.0)


# --- b) Temporal -------------------------------------------------------------------------------

def test_lineal_entre_bloques_exacta_para_una_rampa():
    x, y = malla()
    horas = [0.0, 3.0, 6.0, 9.0]
    altura = np.stack([plano(x, y) + 0.1 * t for t in horas])
    campos = CamposOleaje(conjunto(altura, 100.0, horas))
    px, py = np.array([LON0 + 0.37, LON0 + 0.5]), np.array([LAT0 + 0.21, LAT0 + 0.4])
    for t in (0.0, 0.5, 1.5, 2.999, 3.0, 4.25, 7.75, 9.0):
        assert np.allclose(campos.ola(px, py, t)[0], plano(px, py) + 0.1 * t, atol=1e-12), t


def test_bloques_con_espaciado_irregular_y_horas_que_no_empiezan_en_cero():
    altura = np.stack([np.full((2, 2), v) for v in (1.0, 2.0, 4.0)])
    campos = CamposOleaje(conjunto(altura, 100.0, horas=[12.0, 15.0, 21.0]))     # 3 h y luego 6 h
    p = (np.array([LON0 + 0.05]), np.array([LAT0 + 0.05]))
    assert campos.ola(*p, 1.5)[0][0] == pytest.approx(1.5)       # t se mide desde el primer bloque
    assert campos.ola(*p, 6.0)[0][0] == pytest.approx(3.0)       # a media rampa del tramo de 6 h


def test_antes_del_primer_bloque_y_despues_del_ultimo_se_mantiene_el_mas_cercano():
    altura = np.stack([np.full((2, 2), v) for v in (1.0, 2.0)])
    campos = CamposOleaje(conjunto(altura, 100.0, horas=[0.0, 3.0]))
    p = (np.array([LON0 + 0.05]), np.array([LAT0 + 0.05]))
    assert campos.ola(*p, -4.0)[0][0] == 1.0 and campos.ola(*p, 3.0)[0][0] == 2.0 and campos.ola(*p, 50.0)[0][0] == 2.0


def test_la_direccion_gira_por_el_camino_corto_entre_bloques():
    direccion = np.stack([np.full((2, 2), 350.0), np.full((2, 2), 10.0)])
    campos = CamposOleaje(conjunto(np.ones((2, 2, 2)), direccion, horas=[0.0, 3.0]))
    _, d = campos.ola(np.array([LON0 + 0.05]), np.array([LAT0 + 0.05]), 1.5)
    assert min(d[0], 360 - d[0]) == pytest.approx(0.0, abs=1e-9)


def test_si_un_bloque_no_tiene_dato_en_el_punto_se_usa_el_otro():
    altura = np.stack([np.full((2, 2), 1.0), np.full((2, 2), np.nan)])
    campos = CamposOleaje(conjunto(altura, 100.0, horas=[0.0, 3.0]), nodos_extrapolacion=0)
    h, d = campos.ola(np.array([LON0 + 0.05]), np.array([LAT0 + 0.05]), 1.5)
    assert h[0] == pytest.approx(1.0) and d[0] == pytest.approx(100.0)


def test_bloques_identicos_no_cambian_con_la_hora():
    x, y = malla()
    campos = CamposOleaje(conjunto(np.stack([plano(x, y)] * 3), 100.0, horas=[0.0, 3.0, 6.0]))
    p = (np.array([LON0 + 0.3]), np.array([LAT0 + 0.3]))
    assert len({float(campos.velocidades(*p, t)[0][0]) for t in (0.0, 0.7, 3.0, 4.4, 6.0)}) == 1


# --- c) Integración: RK2 contra soluciones exactas -------------------------------------------------

class Analitico:
    """Campos con velocidades dadas por una función (u, v) = f(lon, lat, t_horas) en m/s."""

    def __init__(self, funcion):
        self.funcion = funcion

    def velocidades(self, lon, lat, t_horas):
        return self.funcion(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float), float(t_horas))


def _integrar(funcion, lon0, lat0, horas):
    return integrar(Analitico(funcion), np.array([lon0]), np.array([lat0]), horas, gamma=1.0, kh_m2s=0.0,
                    rng=np.random.default_rng(0), en_tierra=sin_tierra, dominio=DOMINIO_ABIERTO)


def test_rk2_exacto_si_la_velocidad_crece_linealmente_en_el_tiempo():
    """v(t) = a·t → Δy = a·T²/2. El punto medio evalúa en t + Δt/2 y lo integra sin error;
    con Euler faltaría a·T·Δt/2 (2 % en 24 h)."""
    a = 0.01                                           # m/s por hora
    tr = _integrar(lambda x, y, t: (np.zeros_like(x), np.full_like(y, a * t)), -86.0, 21.0, 24)
    esperado = np.degrees(a * 24 ** 2 / 2 * PASO_SEGUNDOS / RADIO_TIERRA_M)
    assert tr.lat[-1, 0] - 21.0 == pytest.approx(esperado, rel=1e-12)
    assert tr.lon[-1, 0] == pytest.approx(-86.0, abs=1e-12)


def test_rk2_segundo_orden_en_un_campo_con_cizalla():
    """u = k·(lat − lat0), v = v0: la partícula sube a rapidez constante y su deriva al este
    crece linealmente → Δx = k·v0·T²/2 (en metros, a la latitud inicial salvo el cos(lat))."""
    lat0, v0, k = 21.0, 0.05, 0.4                      # k en (m/s) por grado de latitud
    tr = _integrar(lambda x, y, t: (k * (y - lat0), np.full_like(y, v0)), -86.0, lat0, 48)
    dy_m = v0 * 48 * PASO_SEGUNDOS
    assert np.radians(tr.lat[-1, 0] - lat0) * RADIO_TIERRA_M == pytest.approx(dy_m, rel=1e-9)
    dx_m = k * np.degrees(v0 / RADIO_TIERRA_M) * (48 * PASO_SEGUNDOS) ** 2 / 2
    medido = np.radians(tr.lon[-1, 0] + 86.0) * RADIO_TIERRA_M * np.cos(np.radians(lat0 + np.degrees(dy_m / RADIO_TIERRA_M) / 2))
    assert medido == pytest.approx(dx_m, rel=2e-3)     # el residuo es el cos(lat) que cambia en el trayecto


def test_la_simulacion_con_un_campo_real_lineal_en_el_tiempo_sigue_la_integral():
    """De punta a punta con CamposOleaje: H(t) crece entre bloques, |u| = c·√H(t) y el
    desplazamiento es la integral, que el punto medio aproxima con error de segundo orden."""
    horas = [0.0, 3.0, 6.0, 9.0, 12.0]
    altura = np.stack([np.full((3, 3), 0.5 + 0.25 * t) for t in horas])
    campos = CamposOleaje(conjunto(altura, 180.0, horas))                # del sur: viaja al norte
    tr = integrar(campos, np.array([LON0 + 0.2]), np.array([LAT0 + 0.05]), 12, 1.0, 0.0, np.random.default_rng(0),
                  en_tierra=sin_tierra, dominio=DOMINIO_ABIERTO)
    exacto = COEF_STOKES * 3600 * ((0.5 + 0.25 * 12) ** 1.5 - 0.5 ** 1.5) / (1.5 * 0.25)   # ∫ c·√(0.5 + 0.25 t) dt
    assert np.radians(tr.lat[-1, 0] - (LAT0 + 0.05)) * RADIO_TIERRA_M == pytest.approx(exacto, rel=5e-4)
    assert tr.lon[-1, 0] == pytest.approx(LON0 + 0.2, abs=1e-12)
