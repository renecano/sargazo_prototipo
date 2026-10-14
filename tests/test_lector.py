"""Lectura de los dos formatos de SEMAR: fechas, bloques, relleno, malla e interpolación."""
from datetime import datetime, timezone

import numpy as np
import pytest

from scripts.generar_fixtures import CANCUN, escribir_dirmarea, escribir_salidadatos, nodos
from src.config import ARCHIVO_OLEAJE, ARCHIVO_VIENTO, COLUMNAS_OLEAJE, COLUMNAS_VIENTO
from src.ingestion.lector import (
    construir_malla, formatear_fecha, interpolar_bilineal, interpolar_direccion, leer_archivo_semar, parsear_fecha,
)

UTC = timezone.utc


@pytest.mark.parametrize("texto, fecha, hora", [
    ("19AUG2026 00", datetime(2026, 8, 19, 0, tzinfo=UTC), 0),
    ("01OCT2026 00 0", datetime(2026, 10, 1, 0, tzinfo=UTC), 0),
    ("01OCT2026 00 3", datetime(2026, 10, 1, 0, tzinfo=UTC), 3),
    ("01OCT2026 00 120 h", datetime(2026, 10, 1, 0, tzinfo=UTC), 120),
    ("05jan2027 18", datetime(2027, 1, 5, 18, tzinfo=UTC), 0),
    ("31DEC2026 23 117", datetime(2026, 12, 31, 23, tzinfo=UTC), 117),
])
def test_parsear_fecha_semar(texto, fecha, hora):
    assert parsear_fecha(texto) == (fecha, hora)


@pytest.mark.parametrize("texto", ["19AGO2026 00", "32AUG2026 00", "19AUG2026", "2026-08-19 00", "19AUG2026 25"])
def test_fecha_ilegible_devuelve_none(texto):
    assert parsear_fecha(texto) is None


def test_formatear_fecha_es_inverso():
    f = datetime(2026, 8, 19, 0, tzinfo=UTC)
    assert formatear_fecha(f) == "19AUG2026 00"
    assert parsear_fecha(formatear_fecha(f, 9)) == (f, 9)


def test_lee_salidadatos_un_bloque_con_relleno(tmp_path):
    ruta = escribir_salidadatos(tmp_path / ARCHIVO_VIENTO)
    a = leer_archivo_semar(ruta)
    assert a.columnas == list(COLUMNAS_VIENTO)
    assert len(a.bloques) == 1
    b = a.bloques[0]
    lons, lats = nodos(*CANCUN)
    assert b.datos.shape == (lons.size * lats.size, 8)
    assert b.fecha_base == datetime(2026, 8, 19, tzinfo=UTC) and b.hora_pronostico == 0
    assert b.rellenos > 0
    assert np.nanmin(b.datos) > -1e8, "el relleno −9.99e+08 debe quedar como NaN"
    assert np.isnan(b.datos[:, a.indice("U")]).sum() > 0
    assert len(a.huella_sha256) == 64


def test_relleno_exacto_a_nan(tmp_path):
    ruta = tmp_path / "x.txt"
    ruta.write_text("LON;LAT;U\n19AUG2026 00\n-86;21.;-9.99e+08\n-85.84;21;3.5\n-85.68;21.;-999000000\n", encoding="utf-8")
    b = leer_archivo_semar(ruta).bloques[0]
    assert np.isnan(b.datos[0, 2]) and b.datos[1, 2] == 3.5 and np.isnan(b.datos[2, 2])
    assert b.rellenos == 2


def test_lee_dirmarea_41_bloques(tmp_path):
    a = leer_archivo_semar(escribir_dirmarea(tmp_path / ARCHIVO_OLEAJE))
    assert a.columnas == list(COLUMNAS_OLEAJE)
    assert [b.hora_pronostico for b in a.bloques] == list(range(0, 121, 3))
    assert len({b.huella for b in a.bloques}) == 1, "por defecto los bloques son idénticos, como en la muestra"
    assert a.bloques[5].fecha_valida == datetime(2026, 10, 1, 15, tzinfo=UTC)
    distintos = leer_archivo_semar(escribir_dirmarea(tmp_path / "d2.txt", identicos=False))
    assert len({b.huella for b in distintos.bloques}) == 41


def test_lector_tolerante_reporta_filas_defectuosas(tmp_path):
    ruta = tmp_path / "x.txt"
    ruta.write_text("LON;LAT;U\n19AUG2026 00\n-86;21;1\n-85.84;21\n-85.68;21;abc\n-85.52;21;2\n", encoding="utf-8")
    a = leer_archivo_semar(ruta)
    assert a.bloques[0].datos.shape == (2, 3)
    assert [linea for linea, _ in a.filas_invalidas] == [4, 5]


def test_lector_reporta_fecha_ilegible_y_datos_sin_fecha(tmp_path):
    ruta = tmp_path / "x.txt"
    ruta.write_text("LON;LAT;U\n-86;21;1\nAGOSTO 19 DE 2026\n-85.84;21;2\n", encoding="utf-8")
    a = leer_archivo_semar(ruta)
    descripciones = " ".join(p for _, p in a.problemas)
    assert "antes de la línea de fecha" in descripciones and "fecha ilegible" in descripciones


def test_malla_regular_y_orden_norte_sur():
    lons, lats = nodos(-87.0, -86.36, 20.0, 20.48)
    X, Y = np.meshgrid(lons, lats[::-1])  # filas de norte a sur, como SEMAR
    m = construir_malla(X.ravel(), Y.ravel())
    assert m.rectangular and m.forma == (lats.size, lons.size)
    assert np.allclose(m.lats, lats)  # ascendentes tras reconstruir
    rej = m.a_rejilla(Y.ravel())
    assert np.allclose(rej[:, 0], lats)
    incompleta = construir_malla(X.ravel()[:-1], Y.ravel()[:-1])
    assert not incompleta.rectangular


def test_interpolacion_desplazada_ignora_nan():
    lons_o = np.array([-92.08, -91.92, -91.76])
    lats_o = np.array([20.0, 20.16])
    campo = np.array([[1.0, 3.0, np.nan], [1.0, 3.0, 5.0]])
    (r,) = interpolar_bilineal(lons_o, lats_o, [campo], np.array([-92.0, -91.84]), np.array([20.0, 20.16]))
    assert r[0, 0] == pytest.approx(2.0)          # promedio de los dos vecinos en longitud
    assert r[0, 1] == pytest.approx(3.0)          # el vecino NaN se descarta y se renormaliza
    assert r[1, 1] == pytest.approx(4.0)


def test_direccion_por_seno_y_coseno():
    lons_o, lats_o = np.array([0.0, 0.16]), np.array([0.0, 0.16])
    d = interpolar_direccion(lons_o, lats_o, np.array([[350.0, 10.0], [350.0, 10.0]]), np.array([0.08]), np.array([0.0]))
    assert min(d[0, 0], 360 - d[0, 0]) == pytest.approx(0.0, abs=1e-9), "350° y 10° promedian a 0°, no a 180°"
