"""Pruebas rápidas del módulo de validación (sin red).

Usan recortes pequeños guardados en tests/fixtures (ver tests/fixtures/README.md) y casos
sintéticos con respuesta analítica conocida.
"""
from __future__ import annotations

import json
import re
import urllib.error
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

from src.config import DIR_SEMAR
from src.ingestion.validador import validar_conjunto
from src.model.campos import CamposOleaje, OleajeUniforme
from validacion import afai, casos, copernicus, dirmarea, documento, ejecutar, experimentos, metricas, openmeteo
from validacion import config as cfg
from validacion.campos import CamposEncadenados, CamposSuma, CamposVectoriales, vectoriales_desde_serie

FIXTURES = Path(__file__).parent / "fixtures"
SEMAR = DIR_SEMAR / "dirmarea.txt"


# ---------------------------------------------------------------------------
# Lector del ERDDAP y detección
# ---------------------------------------------------------------------------
def test_lector_erddap_recorte_real():
    r = afai.leer_nc_erddap(FIXTURES / "afai_recorte_2025-06-01.nc")
    assert r.fechas == [date(2025, 6, 1), date(2025, 6, 2)]
    assert r.afai.shape == (2, 21, 21)
    assert np.all(np.diff(r.lats) > 0) and np.all(np.diff(r.lons) > 0)
    assert r.lons[0] == pytest.approx(-86.90, abs=0.01) and r.lats[0] == pytest.approx(20.90, abs=0.01)
    assert np.isnan(r.afai).any() and np.isfinite(r.afai).any()      # nube/tierra = NaN
    validos = r.afai[np.isfinite(r.afai)]
    assert validos.min() >= -0.0021 and validos.max() <= 0.0041       # actual_range del dataset
    assert r.dia(date(2025, 6, 2)) is r.afai[1] or np.array_equal(r.dia(date(2025, 6, 2)), r.afai[1], equal_nan=True)
    assert r.dia(date(2025, 6, 3)) is None


def test_lector_erddap_desde_bytes_igual_que_desde_archivo():
    ruta = FIXTURES / "afai_recorte_2025-06-01.nc"
    a, b = afai.leer_nc_erddap(ruta), afai.leer_nc_erddap(ruta.read_bytes())
    assert np.array_equal(a.afai, b.afai, equal_nan=True) and a.fechas == b.fechas


def test_url_afai_pide_solo_el_recorte_y_las_fechas():
    u = afai.url_afai(date(2024, 5, 1), date(2024, 5, 31))
    assert cfg.DATASET_AFAI_1D in u and "AFAI%5B(2024-05-01T12:00:00Z):1:(2024-05-31T12:00:00Z)%5D" in u
    assert f"({cfg.RECUADRO[2]}):1:({cfg.RECUADRO[3]})" in u and f"({cfg.RECUADRO[0]}):1:({cfg.RECUADRO[1]})" in u


def _imagen_sintetica(semilla=0, n=160, ruido=4e-5):
    rng = np.random.default_rng(semilla)
    a = -1.2e-3 + ruido * rng.standard_normal((n, n))
    return a.astype(np.float32)


def test_deteccion_encuentra_una_franja_y_no_el_ruido():
    a = _imagen_sintetica()
    a[80, 30:130] += 1.5e-3          # franja de sargazo
    mar = np.ones(a.shape, bool)
    d = afai.detectar(a, mar)
    assert d.sargazo[80, 35:125].mean() > 0.95
    fuera = d.sargazo.copy()
    fuera[78:83] = False
    assert fuera.mean() < 0.002


def test_deteccion_respeta_nubes_y_su_borde():
    a = _imagen_sintetica()
    a[40:60, 40:60] = np.nan          # nube
    a[50, 61:70] += 2e-3             # sargazo pegado a la nube: el borde se descarta
    d = afai.detectar(a, np.ones(a.shape, bool))
    assert not d.valido[40:60, 40:60].any()
    assert not d.valido[50, 60:62].any()           # 2 píxeles de borde
    assert d.sargazo[50, 63:70].all()


def test_deteccion_umbral_adaptativo_al_ruido():
    """Con ruido del orden de T0, solo T0 marcaría muchos píxeles; con 3σ casi ninguno."""
    a = _imagen_sintetica(ruido=2e-4)
    mar = np.ones(a.shape, bool)
    solo_t0 = afai.detectar(a, mar, k_sigma=0.0).sargazo.mean()
    adaptativo = afai.detectar(a, mar).sargazo.mean()
    assert solo_t0 > 0.15 and adaptativo < 0.01


def test_deteccion_por_region_evita_la_costura_del_producto():
    """Un escalón de fondo entre dos regiones del producto da una franja falsa de "sargazo"
    si el fondo mezcla ambas regiones; calculándolo por región, no."""
    a = _imagen_sintetica()
    a[:80] += 6e-4                                  # región norte más brillante
    mar = np.ones(a.shape, bool)
    regiones = np.zeros(a.shape, np.int8)
    regiones[:80] = 1
    mezclado = afai.detectar(a, mar).sargazo
    separado = afai.detectar(a, mar, regiones=regiones).sargazo
    assert mezclado[55:80].mean() > 0.2
    assert separado.mean() < 0.002


def test_regiones_del_producto_de_aoml():
    lons = np.array([-90.5, -90.0, -89.5])
    lats = np.array([21.5, 22.0, 22.5])
    r = afai.regiones_producto(lons, lats)
    assert r.tolist() == [[0, 0, 1], [0, 0, 0], [0, 0, 0]]


# ---------------------------------------------------------------------------
# generar_dirmarea: formato idéntico y aceptado por el lector del producto
# ---------------------------------------------------------------------------
def _rejilla_uniforme(desde: datetime, horas: int, altura=1.23, direccion=45.0, paso=1 / 12):
    """Rejilla sintética como la de Copernicus Marine (0.083°, cada 3 h) con ola uniforme."""
    lons = np.arange(-92.5, -83.6, paso)
    lats = np.arange(16.5, 23.4, paso)
    t = [desde + timedelta(hours=h) for h in range(0, horas + 1, 3)]
    forma = (len(t), lats.size, lons.size)
    val = {"VHM0_WW": np.full(forma, altura, np.float32), "VMDR_WW": np.full(forma, direccion, np.float32),
           "VTM01_WW": np.full(forma, 4.4, np.float32), "VSDX": np.zeros(forma, np.float32),
           "VSDY": np.zeros(forma, np.float32)}
    return copernicus.Rejilla("prueba", lons, lats, t, val, "2026-10-31T00:00Z")


@pytest.fixture(scope="module")
def dirmarea_generado(tmp_path_factory):
    rej = _rejilla_uniforme(datetime(2025, 6, 1, tzinfo=timezone.utc), 120)
    destino = tmp_path_factory.mktemp("dirmarea")
    ruta, resumen = dirmarea.generar(date(2025, 6, 1), destino, rejilla=rej)
    return ruta, resumen


def test_generar_dirmarea_formato_identico_al_de_semar(dirmarea_generado):
    ruta, _ = dirmarea_generado
    gen = ruta.read_text(encoding="utf-8").split("\n")
    sem = SEMAR.read_text(encoding="utf-8").split("\n")
    assert len(gen) == len(sem)
    assert gen[0] == sem[0] == "LON;LAT;dirolavto;alturaolavto"
    bloques = [k for k, l in enumerate(gen) if re.fullmatch(r"\d{2}[A-Z]{3}\d{4} \d{2} \d+", l)]
    assert bloques == [k for k, l in enumerate(sem) if re.fullmatch(r"\d{2}[A-Z]{3}\d{4} \d{2} \d+", l)]
    assert gen[1] == "01JUN2025 00 0" and gen[bloques[-1]] == "01JUN2025 00 120"
    for g, s in zip(gen, sem):
        if ";" in s and not s.startswith("LON"):
            assert g.split(";")[:2] == s.split(";")[:2]          # LON;LAT byte a byte
            for v in g.split(";")[2:]:
                assert v == "-9.99e+08" or re.fullmatch(r"\d+(\.\d{1,2})?", v)
    assert ruta.read_bytes().endswith(b"\n") and b"\r" not in ruta.read_bytes()


def test_generar_dirmarea_lo_acepta_el_validador_y_el_lector_sin_cambios(dirmarea_generado):
    ruta, resumen = dirmarea_generado
    reporte, conjunto = validar_conjunto(ruta.parent)
    assert reporte.valido, [h.detalle for v in reporte.verificaciones for h in v.hallazgos]
    assert conjunto.fecha_base == datetime(2025, 6, 1, tzinfo=timezone.utc)
    assert list(conjunto.horas) == list(range(0, 121, 3))
    # Mismos nodos de mar que el archivo de SEMAR y los valores escritos.
    _, semar = validar_conjunto(DIR_SEMAR)
    assert np.array_equal(conjunto.mar, semar.mar)
    assert np.allclose(conjunto.altura[:, conjunto.mar], 1.23)
    assert np.allclose(conjunto.direccion[:, conjunto.mar], 45.0)
    assert resumen["nodos_con_dato"] == int(semar.mar.sum())
    # Y el modelo del producto lo usa: ola de 1.23 m desde el NE → deriva hacia el SO.
    u, v = CamposOleaje(conjunto).velocidades(np.array([-86.3]), np.array([21.0]), 10.0)
    assert u[0] < 0 and v[0] < 0


def test_a_malla_fina_interpola_y_usa_vecino_cerca_de_la_costa():
    destino = np.zeros((dirmarea.NLAT, dirmarea.NLON), bool)
    destino[10:13, 40:43] = True
    ii = np.array([10, 10, 12, 12])
    jj = np.array([40, 42, 40, 42])
    vals = np.array([[0.0, 2.0, 0.0, 2.0]])
    (f,) = dirmarea.a_malla_fina(vals, ii, jj, 2, destino)
    assert f[11, 41] == pytest.approx(1.0) and f[10, 40] == 0.0 and f[12, 42] == 2.0
    # Nodo cuyos vecinos de submalla no tienen dato: toma el más cercano a ≤ 1.5 celdas.
    destino2 = np.zeros_like(destino)
    destino2[14, 41] = True
    (g,) = dirmarea.a_malla_fina(np.array([[5.0]]), np.array([12]), np.array([40]), 2, destino2)
    assert g[14, 41] == 5.0


# ---------------------------------------------------------------------------
# Open-Meteo (sin red)
# ---------------------------------------------------------------------------
def test_openmeteo_convierte_unidades_y_guarda_cache(monkeypatch, tmp_path):
    def falsa(grupo, lons, lats, desde, hasta, registrar=print):
        return [{"latitude": la, "longitude": lo, "hourly_units": {"wind_speed_10m": "km/h",
                                                                   "wind_direction_10m": "°"},
                 "hourly": {"time": ["2025-06-01T00:00", "2025-06-01T01:00"],
                            "wind_speed_10m": [36.0, None], "wind_direction_10m": [90, 180]}}
                for lo, la in zip(lons, lats)]
    monkeypatch.setattr(openmeteo, "_peticion", falsa)
    s = openmeteo.descargar_serie(openmeteo.VIENTO, np.array([-86.0, -85.84]), np.array([21.0, 21.0]),
                                  date(2025, 6, 1), date(2025, 6, 1), tmp_path, registrar=lambda *_: None)
    assert s.valores["wind_speed_10m"][0] == pytest.approx([10.0, 10.0])          # km/h → m/s
    assert np.isnan(s.valores["wind_speed_10m"][1]).all()
    assert s.tiempos[1] == datetime(2025, 6, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(openmeteo, "_peticion", lambda *a, **k: pytest.fail("debió leer la caché"))
    s2 = openmeteo.descargar_serie(openmeteo.VIENTO, np.array([-86.0, -85.84]), np.array([21.0, 21.0]),
                                   date(2025, 6, 1), date(2025, 6, 1), tmp_path)
    assert np.array_equal(s2.valores["wind_speed_10m"], s.valores["wind_speed_10m"], equal_nan=True)


def test_openmeteo_cuota_diaria_se_reporta(monkeypatch):
    def urlopen(*a, **k):
        raise urllib.error.HTTPError("u", 429, "x", {}, BytesIO(b'{"error":true,"reason":"Daily API request limit exceeded."}'))
    monkeypatch.setattr(openmeteo.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(openmeteo, "LIMITADOR", openmeteo.Limitador())
    with pytest.raises(openmeteo.CuotaAgotada, match="Daily"):
        openmeteo._peticion(openmeteo.VIENTO, np.array([-86.0]), np.array([21.0]), date(2025, 6, 1),
                            date(2025, 6, 2), registrar=lambda *_: None)


# ---------------------------------------------------------------------------
# Campos de los experimentos
# ---------------------------------------------------------------------------
def test_campos_encadenados_eligen_el_tramo_por_hora():
    c = CamposEncadenados([(0.0, OleajeUniforme(1.0, 0.0)), (120.0, OleajeUniforme(1.0, 90.0))])
    x, y = np.array([-86.0]), np.array([21.0])
    assert c.velocidades(x, y, 10)[1][0] < 0            # ola del norte → hacia el sur
    assert c.velocidades(x, y, 130)[0][0] < 0           # ola del este → hacia el oeste


def test_convenciones_corriente_hacia_y_viento_desde():
    base = dirmarea.plantilla()
    destino = np.zeros((dirmarea.NLAT, dirmarea.NLON), bool)
    destino[30:34, 70:74] = True
    ii, jj = np.meshgrid(np.arange(30, 36, 2), np.arange(70, 76, 2), indexing="ij")
    ii, jj = ii.ravel(), jj.ravel()
    inicio = datetime(2025, 6, 1, tzinfo=timezone.utc)
    t = [inicio + timedelta(hours=h) for h in range(4)]

    def serie(nombre, var_v, var_d, vel, direc):
        return openmeteo.Serie(nombre, "m", base.lons[jj], base.lats[ii], t,
                               {var_v: np.full((4, ii.size), vel), var_d: np.full((4, ii.size), direc)},
                               {var_v: "m/s", var_d: "°"}, np.zeros((ii.size, 2)), "")
    cor = vectoriales_desde_serie(serie("corriente", "ocean_current_velocity", "ocean_current_direction", 0.5, 90.0),
                                  ii, jj, 2, destino, base.lons, base.lats, inicio, 3, "hacia")
    vie = vectoriales_desde_serie(serie("viento", "wind_speed_10m", "wind_direction_10m", 10.0, 90.0),
                                  ii, jj, 2, destino, base.lons, base.lats, inicio, 3, "desde")
    x, y = np.array([base.lons[71]]), np.array([base.lats[31]])
    assert cor.velocidades(x, y, 1.5)[0][0] == pytest.approx(0.5)      # corriente hacia el este
    assert vie.velocidades(x, y, 1.5)[0][0] == pytest.approx(-10.0)    # viento del este → hacia el oeste
    suma = CamposSuma([(1.0, cor), (0.02, vie)])
    assert suma.velocidades(x, y, 0)[0][0] == pytest.approx(0.5 - 0.2)


# ---------------------------------------------------------------------------
# Métricas con respuesta analítica
# ---------------------------------------------------------------------------
def test_fss_identicos_es_uno_y_disjuntos_es_cero():
    o = np.zeros((40, 40))
    o[10:14, 10:14] = 1
    v = np.ones(o.shape, bool)
    assert metricas.fss(o, o, v, 1) == pytest.approx(1.0)
    assert metricas.fss(o, o, v, 9) == pytest.approx(1.0)
    assert metricas.fss(o, np.zeros_like(o), v, 9) == pytest.approx(0.0)
    assert np.isnan(metricas.fss(np.zeros_like(o), np.zeros_like(o), v, 3))


def test_fss_un_pixel_desplazado_vale_dos_tercios_con_ventana_de_3():
    """O y M de un píxel, separados 1 px; ventana 3 × 3 sin bordes: 6 celdas comparten
    1/9, 3 solo O y 3 solo M → MSE = 6/81, ref = 18/81 → FSS = 1 − 6/18 = 2/3."""
    o = np.zeros((21, 21))
    m = np.zeros((21, 21))
    o[10, 10] = 1
    m[10, 11] = 1
    assert metricas.fss(o, m, np.ones(o.shape, bool), 3) == pytest.approx(2 / 3)
    assert metricas.fss(o, m, np.ones(o.shape, bool), 1) == pytest.approx(0.0)


def test_fss_crece_con_la_escala_y_ignora_nubes():
    o = np.zeros((60, 60))
    m = np.zeros((60, 60))
    o[30, 20] = 1
    m[30, 26] = 1
    v = np.ones(o.shape, bool)
    vals = [metricas.fss(o, m, v, n) for n in (1, 5, 7, 13, 17, 25)]
    assert vals == sorted(vals) and vals[0] == 0 and vals[1] == 0
    # Lejos de los bordes, dos puntos separados d < n dan FSS = 1 − d/n.
    for n in (7, 13, 17):
        assert metricas.fss(o, m, v, n) == pytest.approx(1 - 6 / n)
    # Si el píxel simulado cae bajo una nube, no cuenta.
    v2 = v.copy()
    v2[30, 26] = False
    assert metricas.fss(o, m, v2, 1) == pytest.approx(0.0) and metricas.fss(o, o, v2, 5) == pytest.approx(1.0)


def test_suma_ventana_contra_fuerza_bruta():
    rng = np.random.default_rng(1)
    a = rng.random((17, 23))
    s = metricas.suma_ventana(a, 5)
    p = np.pad(a, 2)
    bruta = np.array([[p[i:i + 5, j:j + 5].sum() for j in range(23)] for i in range(17)])
    assert np.allclose(s, bruta)


def test_ventana_impar_aproxima_la_escala():
    assert metricas.ventana_impar(10, 1.617) == 7
    assert metricas.ventana_impar(25, 1.617) == 15
    assert metricas.ventana_impar(50, 1.617) == 31


def _campo_parches(semilla, n=200):
    rng = np.random.default_rng(semilla)
    f = np.zeros((n, n))
    for _ in range(40):
        i, j = rng.integers(10, n - 10, 2)
        f[i - 2:i + 3, j - rng.integers(3, 9):j + rng.integers(3, 9)] = rng.uniform(4e-4, 1e-3)
    return f


@pytest.mark.parametrize("di,dj", [(3, -5), (-7, 2), (0, 0), (10, 9)])
def test_mcc_recupera_un_desplazamiento_sintetico(di, dj):
    a = _campo_parches(2)
    b = np.roll(np.roll(a, di, axis=0), dj, axis=1)
    sarg = a > 0
    v = np.ones(a.shape, bool)
    vec = metricas.mcc(a, v, sarg, b, v, plantilla_px=21, busqueda_px=15, min_sargazo=10, min_validos=0.7,
                       min_correlacion=0.5)
    assert len(vec) >= 3
    for x in vec:
        assert x.di == pytest.approx(di, abs=0.5) and x.dj == pytest.approx(dj, abs=0.5)
        assert x.correlacion > 0.95


def test_mcc_con_nubes_en_la_segunda_imagen():
    a = _campo_parches(3)
    b = np.roll(a, 4, axis=1)
    va = np.ones(a.shape, bool)
    vb = np.ones(a.shape, bool)
    vb[::7, :] = False                       # franjas sin dato
    vec = metricas.mcc(a, va, a > 0, np.where(vb, b, 0), vb, 21, 12, 10, 0.7, 0.5)
    assert vec and all(x.dj == pytest.approx(4, abs=0.5) and abs(x.di) < 0.5 for x in vec)


def test_liu_weisberg_analitico():
    assert metricas.liu_weisberg(np.array([0.0]), np.array([10.0])) == 1.0
    assert metricas.liu_weisberg(np.array([5.0]), np.array([10.0])) == pytest.approx(0.5)
    assert metricas.liu_weisberg(np.array([30.0]), np.array([10.0])) == 0.0
    assert np.isnan(metricas.liu_weisberg(np.array([1.0]), np.array([0.0])))


def test_diferencia_angular_y_rumbo():
    assert metricas.diferencia_angular((1, 0), (0, 1)) == pytest.approx(90)
    assert metricas.diferencia_angular((1, 0), (-1, 0)) == pytest.approx(180)
    assert metricas.diferencia_angular((0, 1), (-0.01, 1)) < 1
    assert metricas.rumbo((0, -1)) == pytest.approx(180) and metricas.rumbo((-1, 0)) == pytest.approx(270)


def test_bootstrap_intervalo_contiene_la_media_e_ignora_nan():
    m, lo, hi, n = metricas.bootstrap_media(np.array([0.1, 0.2, np.nan, 0.3, 0.4]), 500, 0.95)
    assert n == 4 and m == pytest.approx(0.25) and lo <= m <= hi
    assert metricas.bootstrap_media(np.array([np.nan]), 10, 0.95)[3] == 0


def test_contingencia_pod_far_csi():
    c = metricas.Contingencia()
    for p, o in [(True, True), (True, True), (False, True), (True, False), (False, False)]:
        c.sumar(p, o)
    assert (c.aciertos, c.fallos, c.falsas_alarmas, c.negativos) == (2, 1, 1, 1)
    assert c.pod == pytest.approx(2 / 3) and c.far == pytest.approx(1 / 3) and c.csi == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Persistencia, siembra y selección de casos
# ---------------------------------------------------------------------------
def _rejilla_caribe():
    lons = np.arange(-86.6, -85.6, 0.015)
    lats = np.arange(20.6, 21.4, 0.015)
    return lons, lats


def test_siembra_proporcional_y_cada_pixel_pesa_uno():
    lons, lats = _rejilla_caribe()
    sarg = np.zeros((lats.size, lons.size), bool)
    sarg[20:23, 30:40] = True                              # 30 píxeles en mar abierto
    s = experimentos.sembrar(sarg, lons, lats, n=100)
    assert s.lon.size == 100 and s.pixeles == 30
    campo = experimentos.a_pixeles(s.lon, s.lat, s.peso, lons, lats)
    assert np.array_equal(campo > 0, sarg) and np.allclose(campo[sarg], 1.0)
    assert s.peso.sum() == pytest.approx(30)
    # Reproducible con la misma semilla.
    s2 = experimentos.sembrar(sarg, lons, lats, n=100)
    assert np.array_equal(s.lon, s2.lon)


def test_persistencia_da_fss_uno_cuando_nada_se_mueve():
    lons, lats = _rejilla_caribe()
    sarg = np.zeros((lats.size, lons.size), bool)
    sarg[10:14, 5:25] = True
    sarg[30, 40:60] = True
    s = experimentos.sembrar(sarg, lons, lats, n=500)
    e0 = experimentos.correr(experimentos.Experimento("E0", "Persistencia", mover=False), s, None)
    valido = np.ones(sarg.shape, bool)
    valido[0:5] = False                                   # nubes en otra parte
    for h in (72, 120, 168):
        campo = experimentos.a_pixeles(e0.lon[h], e0.lat[h], s.peso, lons, lats)
        for n in (1, 7, 15, 31):
            assert metricas.fss(sarg.astype(float), campo, valido, n) == pytest.approx(1.0)


def test_simulacion_de_validacion_usa_el_integrador_del_producto():
    """Con ola uniforme y K_h = 0, E2 desplaza todo igual: u_s·t (sin varar en mar abierto)."""
    lons, lats = _rejilla_caribe()
    sarg = np.zeros((lats.size, lons.size), bool)
    sarg[25, 25] = True
    s = experimentos.sembrar(sarg, lons, lats, n=10)
    f = experimentos.Forzamientos(OleajeUniforme(1.0, 180.0), None, None, None, {})      # ola del sur → al norte
    corr = experimentos.correr(experimentos.Experimento("E2", "v0.3", gamma=1.0, kh=0.0), s, f)
    from src.model.campos import magnitud_stokes
    esperado = magnitud_stokes(1.0) * 72 * 3600 / 111_195.0
    assert np.allclose(corr.lat[72] - s.lat, esperado, rtol=1e-3) and np.allclose(corr.lon[72], s.lon)
    assert experimentos.correr(experimentos.Experimento("E4", "c", corriente=1.0), s, f) is None   # sin corriente


class _Det:
    """Detecciones sintéticas: todo despejado salvo los días nublados indicados."""

    def __init__(self, forma, nublados=()):
        self.forma, self.nublados = forma, set(nublados)

    def dia(self, f):
        v = np.zeros(self.forma, bool) if f in self.nublados else np.ones(self.forma, bool)
        s = np.zeros(self.forma, bool)
        s[5:10, 5:10] = True
        return v, s


class _Masc:
    def __init__(self, forma):
        self.lons = np.arange(forma[1]) * 0.015 - 86.0
        self.lats = np.arange(forma[0]) * 0.015 + 20.0
        self.mar_util = np.ones(forma, bool)


def _inventario(desde, dias, sargazo=500, claro=0.9, excepciones=None):
    excepciones = excepciones or {}
    filas = []
    for k in range(dias):
        f = desde + timedelta(days=k)
        fila = {"fecha": f, "mar_util": 1000, "validos": 900, "claro": claro, "sargazo": sargazo}
        fila.update(excepciones.get(f, {}))
        if fila.get("sin_imagen"):
            continue
        filas.append(fila)
    return filas


def test_seleccion_de_casos_reproducible_y_sin_traslape(monkeypatch):
    monkeypatch.setattr(cfg, "BUSQUEDA_DESDE", date(2024, 12, 1))
    monkeypatch.setattr(cfg, "BUSQUEDA_HASTA", date(2025, 1, 31))
    forma = (30, 30)
    exc = {date(2024, 12, 3): {"sargazo": 10}, date(2024, 12, 4): {"claro": 0.1},
           date(2024, 12, 20): {"sin_imagen": True}}
    filas = _inventario(date(2024, 12, 1), 62, excepciones=exc)
    a = casos.seleccionar(filas, _Det(forma), _Masc(forma))
    b = casos.seleccionar(filas, _Det(forma), _Masc(forma))
    assert [c.t0 for c in a.casos] == [c.t0 for c in b.casos] and a.descartes == b.descartes
    t0s = [c.t0 for c in a.casos]
    assert all((y - x).days > 7 for x, y in zip(t0s, t0s[1:]))
    assert {c.conjunto for c in a.casos if c.t0 < date(2025, 1, 1)} <= {"calibracion"}
    assert {c.conjunto for c in a.casos if c.t0 >= date(2025, 1, 1)} <= {"evaluacion"}
    assert a.descartes["poco_sargazo"] == 1 and a.descartes["nube_t0"] == 1
    # 20 dic sin imagen: descarta ese día como t0 y los días cuyo +3/+5/+7 cae ahí.
    assert a.descartes["sin_imagen"] == 1 and a.descartes["sin_destino"] >= 3
    assert sum(a.descartes.values()) + len(a.casos) == a.dias_revisados


def test_seleccion_descarta_si_la_zona_del_sargazo_esta_nublada(monkeypatch):
    monkeypatch.setattr(cfg, "BUSQUEDA_DESDE", date(2025, 3, 1))
    monkeypatch.setattr(cfg, "BUSQUEDA_HASTA", date(2025, 3, 20))
    forma = (30, 30)
    filas = _inventario(date(2025, 3, 1), 20)
    det = _Det(forma, nublados={date(2025, 3, 8)})          # +7 del 1 de marzo, +5 del 3, +3 del 5
    sel = casos.seleccionar(filas, det, _Masc(forma))
    assert date(2025, 3, 1) not in [c.t0 for c in sel.casos]
    assert sel.descartes["nube_zona"] >= 3


def test_veredicto_contra_persistencia_usa_el_intervalo_y_exige_casos():
    from validacion.reporte import veredicto
    base = {"casos_comparados": 10}
    assert veredicto({**base, "dif_ic_inf": 0.01, "dif_ic_sup": 0.05}) == "mejor"
    assert veredicto({**base, "dif_ic_inf": -0.05, "dif_ic_sup": -0.01}) == "peor"
    assert veredicto({**base, "dif_ic_inf": -0.02, "dif_ic_sup": 0.03}) == "indistinguible"
    assert veredicto({"casos_comparados": 1, "dif_ic_inf": -0.1, "dif_ic_sup": -0.1}) == "sin datos suficientes"
    assert veredicto(None) == "sin datos"


def test_franja_de_costura_solo_del_lado_caribe():
    from validacion.inventario import franja_costura
    lons = np.arange(-91.0, -88.0, 0.015)
    lats = np.arange(21.0, 23.0, 0.015)
    f = franja_costura(lons, lats, px=25)
    i = lambda lat: int(np.argmin(abs(lats - lat)))
    j = lambda lon: int(np.argmin(abs(lons - lon)))
    assert f[i(21.9), j(-89.0)] and f[i(21.5), j(-89.9)]          # junto a 22° N y junto a 90° O, lado Caribe
    assert not f[i(21.5), j(-89.0)]                                # Caribe lejos de la costura
    assert not f[i(22.1), j(-89.0)] and not f[i(21.9), j(-90.1)]   # región «Golfo»



# ---------------------------------------------------------------------------
# Copernicus Marine (sin red)
# ---------------------------------------------------------------------------
def test_copernicus_a_puntos_bilineal_y_vecino_cerca_de_la_costa():
    lons = np.array([-87.0, -86.9, -86.8])
    lats = np.array([21.0, 21.1, 21.2])
    c = np.array([[0.0, 1.0, np.nan], [0.0, 1.0, np.nan], [np.nan, np.nan, np.nan]])
    (v,) = copernicus.a_puntos([c], lons, lats, np.array([-86.95, -86.8]), np.array([21.05, 21.1]))
    assert v[0] == pytest.approx(0.5)            # bilineal entre nodos con dato
    assert v[1] == pytest.approx(1.0)            # sin vecinos con dato: el más cercano (≤ 1.5 celdas)


def test_copernicus_elige_analisis_o_reanalisis_segun_la_cobertura(tmp_path):
    hoy = date.today().isoformat()
    ms = lambda d: datetime(*d, tzinfo=timezone.utc).timestamp() * 1000
    catalogo = {copernicus.OLEAJE_ANFC: {"inicio_ms": ms((2022, 11, 1, 3)), "fin_ms": ms((2026, 11, 10)), "consultado": hoy},
                copernicus.OLEAJE_MY: {"inicio_ms": ms((1980, 1, 1)), "fin_ms": ms((2026, 8, 31, 21)), "consultado": hoy},
                copernicus.CORRIENTE_SMOC: {"inicio_ms": ms((2020, 11, 1)), "fin_ms": ms((2026, 11, 9, 23)), "consultado": hoy}}
    (tmp_path / "copernicus").mkdir()
    (tmp_path / "copernicus" / "catalogo.json").write_text(json.dumps(catalogo), encoding="utf-8")
    u = lambda *a: datetime(*a, tzinfo=timezone.utc)
    assert copernicus.elegir_oleaje(u(2025, 4, 22), u(2025, 5, 2), tmp_path) == copernicus.OLEAJE_ANFC
    assert copernicus.elegir_oleaje(u(2022, 6, 23), u(2022, 7, 3), tmp_path) == copernicus.OLEAJE_MY
    assert copernicus.elegir_oleaje(u(2022, 10, 25), u(2022, 11, 4), tmp_path) == copernicus.OLEAJE_MY
    assert copernicus.elegir_corriente(u(2022, 3, 4), u(2022, 3, 14), tmp_path) == copernicus.CORRIENTE_SMOC
    with pytest.raises(copernicus.SinCobertura):
        copernicus.elegir_corriente(u(2019, 1, 1), u(2019, 1, 11), tmp_path)


def test_e4_usa_corriente_total_y_e5_la_corriente_sin_stokes():
    """E5 suma la ola del modelo: debe usar la corriente SIN Stokes para no contarla dos veces."""
    def campo(u):
        return CamposVectoriales(-88.0, 20.0, 0.1, 0.1, np.array([0.0, 200.0]), np.full((2, 30, 30), u),
                                 np.zeros((2, 30, 30)))
    f = experimentos.Forzamientos(OleajeUniforme(0.0, 0.0), campo(0.5), campo(0.3), campo(10.0), {})
    x, y = np.array([-87.0]), np.array([21.0])
    c4, g4 = experimentos.campos_de(experimentos.Experimento("E4", "", corriente=1.0), f)
    c5, g5 = experimentos.campos_de(experimentos.Experimento("E5-1", "", gamma=1.0, corriente=1.0, viento=0.01), f)
    assert c4.velocidades(x, y, 10)[0][0] == pytest.approx(0.5)
    assert c5.velocidades(x, y, 10)[0][0] == pytest.approx(0.3 + 0.01 * 10.0)
    assert g4 == g5 == 1.0


def test_e3_queda_pendiente_sin_calibracion_completa(tmp_path):
    lista = experimentos.experimentos(None, None)
    assert "E3" not in [e.id for e in lista] and {"E0", "E1", "E2", "E4"} <= {e.id for e in lista}
    assert "E3" in [e.id for e in experimentos.experimentos(0.0, 1.0)]

    class C:
        def __init__(self, i):
            self.id = i
    cal = [C("A"), C("B")]
    (tmp_path / "casos" / "A").mkdir(parents=True)
    (tmp_path / "casos" / "A" / "calibracion.json").write_text(json.dumps(
        [{"caso": "A", "gamma": 0.0, "kh": 1.0, "fss_3d": 0.3, "fss_5d": 0.2, "fss_7d": 0.2}]), encoding="utf-8")
    g, k, tabla, filas, faltan = ejecutar.calibracion_completa(cal, tmp_path)
    assert g is None and k is None and tabla == [] and faltan == ["B"] and len(filas) == 1


# ---------------------------------------------------------------------------
# Consistencia del reporte
# ---------------------------------------------------------------------------
def _reporte_sintetico(tmp_path, calibracion, con_resultado, md_casos=None, filas_csv=None):
    salida = tmp_path / "validacion"
    salida.mkdir(exist_ok=True)
    filas_csv = filas_csv or [
        {"id": "C1", "conjunto": "calibracion", "con_resultado": "True"},
        {"id": "C2", "conjunto": "calibracion", "con_resultado": "False"},
        {"id": "E1", "conjunto": "evaluacion", "con_resultado": "True"},
    ]
    import csv
    with (salida / "casos.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "conjunto", "con_resultado"])
        w.writeheader()
        w.writerows(filas_csv)
    resumen = {"casos": {"seleccionados": {"calibracion": 2, "evaluacion": 1},
                         "con_resultado": con_resultado,
                         "faltan": {"calibracion": ["C2"], "evaluacion": []}},
               "calibracion": calibracion}
    (salida / "resumen.json").write_text(json.dumps(resumen), encoding="utf-8")
    md = tmp_path / "validacion.md"
    n = con_resultado["evaluacion"] if md_casos is None else md_casos
    md.write_text(f"Medido en {n} casos de evaluación\n", encoding="utf-8")
    return salida, md


def test_reporte_consistente_pasa(tmp_path):
    salida, md = _reporte_sintetico(tmp_path, {"estado": "pendiente", "gamma": None, "kh": None, "casos": 1},
                                    {"calibracion": 1, "evaluacion": 1})
    documento.verificar_consistencia(salida, md)


def test_reporte_falla_con_parametros_calibrados_y_casos_faltantes(tmp_path):
    salida, md = _reporte_sintetico(tmp_path, {"estado": "completa", "gamma": 0.0, "kh": 1.0, "casos": 1},
                                    {"calibracion": 1, "evaluacion": 1})
    with pytest.raises(ValueError, match="E3 tiene parámetros calibrados"):
        documento.verificar_consistencia(salida, md)


def test_reporte_falla_con_cero_casos_y_parametros(tmp_path):
    filas = [{"id": "E1", "conjunto": "evaluacion", "con_resultado": "False"}]
    salida, md = _reporte_sintetico(tmp_path, {"estado": "completa", "gamma": 0.5, "kh": 10.0, "casos": 0},
                                    {"calibracion": 0, "evaluacion": 0}, filas_csv=filas)
    with pytest.raises(ValueError, match="E3 tiene parámetros calibrados con 0"):
        documento.verificar_consistencia(salida, md)


def test_reporte_falla_si_los_conteos_no_cuadran_con_casos_csv(tmp_path):
    salida, md = _reporte_sintetico(tmp_path, {"estado": "pendiente", "gamma": None, "kh": None, "casos": 1},
                                    {"calibracion": 2, "evaluacion": 1})
    with pytest.raises(ValueError, match="con resultado"):
        documento.verificar_consistencia(salida, md)
    salida, md = _reporte_sintetico(tmp_path, {"estado": "pendiente", "gamma": None, "kh": None, "casos": 1},
                                    {"calibracion": 1, "evaluacion": 1}, md_casos=13)
    with pytest.raises(ValueError, match="Medido en 1 casos"):
        documento.verificar_consistencia(salida, md)


def test_reporte_publicado_es_consistente():
    """El reporte que está en docs/ (el que se publica) no se contradice."""
    salida = cfg.DIR_RESULTADOS
    if not (salida / "resumen.json").is_file():
        pytest.skip("Aún no hay resultados de validación en docs/validacion/")
    documento.verificar_consistencia(salida, salida.parent / "validacion.md")
