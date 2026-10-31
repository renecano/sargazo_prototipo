"""Lectura de dirmarea.txt: fechas, bloques, relleno −9.99e+08 → NaN, filas defectuosas y malla."""
from datetime import datetime, timezone

import numpy as np
import pytest

from scripts.generar_fixtures import CANCUN, escribir_dirmarea, nodos
from src.config import ARCHIVO_OLEAJE, COLUMNAS_OLEAJE
from src.ingestion.lector import construir_malla, formatear_fecha, leer_archivo_semar, parsear_fecha

UTC = timezone.utc


@pytest.mark.parametrize("texto, fecha, hora", [
    ("01OCT2026 00 0", datetime(2026, 10, 1, 0, tzinfo=UTC), 0),
    ("01OCT2026 00 3", datetime(2026, 10, 1, 0, tzinfo=UTC), 3),
    ("01OCT2026 00 120 h", datetime(2026, 10, 1, 0, tzinfo=UTC), 120),
    ("19AUG2026 00", datetime(2026, 8, 19, 0, tzinfo=UTC), 0),
    ("05jan2027 18", datetime(2027, 1, 5, 18, tzinfo=UTC), 0),
    ("31DEC2026 23 117", datetime(2026, 12, 31, 23, tzinfo=UTC), 117),
])
def test_parsear_fecha_semar(texto, fecha, hora):
    assert parsear_fecha(texto) == (fecha, hora)


@pytest.mark.parametrize("texto", ["01OCTU2026 00", "32OCT2026 00", "01OCT2026", "2026-10-01 00", "01OCT2026 25"])
def test_fecha_ilegible_devuelve_none(texto):
    assert parsear_fecha(texto) is None


def test_formatear_fecha_es_inverso():
    f = datetime(2026, 10, 1, 0, tzinfo=UTC)
    assert formatear_fecha(f) == "01OCT2026 00"
    assert parsear_fecha(formatear_fecha(f, 9)) == (f, 9)


def test_lee_dirmarea_41_bloques_con_relleno(tmp_path):
    a = leer_archivo_semar(escribir_dirmarea(tmp_path / ARCHIVO_OLEAJE))
    lons, lats = nodos(*CANCUN)
    assert a.columnas == list(COLUMNAS_OLEAJE)
    assert [b.hora_pronostico for b in a.bloques] == list(range(0, 121, 3))
    assert all(b.datos.shape == (lons.size * lats.size, 4) for b in a.bloques)
    assert a.bloques[5].fecha_valida == datetime(2026, 10, 1, 15, tzinfo=UTC)
    b = a.bloques[0]
    assert b.rellenos > 0 and np.nanmin(b.datos) > -1e8, "el relleno −9.99e+08 debe quedar como NaN"
    assert np.isnan(b.datos[:, a.indice("alturaolavto")]).sum() == b.rellenos // 2
    assert len({x.huella for x in a.bloques}) == 1, "por defecto los bloques son idénticos, como en la muestra"
    assert len(a.huella_sha256) == 64


def test_bloques_distintos(tmp_path):
    a = leer_archivo_semar(escribir_dirmarea(tmp_path / ARCHIVO_OLEAJE, identicos=False))
    assert len({b.huella for b in a.bloques}) == 41


def test_relleno_exacto_a_nan(tmp_path):
    ruta = tmp_path / "x.txt"
    ruta.write_text("LON;LAT;dirolavto;alturaolavto\n01OCT2026 00 0\n-86;21.;-9.99e+08;-9.99e+08\n"
                    "-85.84;21;100.5;1.2\n-85.68;21.;-999000000;0.4\n", encoding="utf-8")
    d = leer_archivo_semar(ruta).bloques[0]
    assert np.isnan(d.datos[0, 2]) and np.isnan(d.datos[0, 3])
    assert d.datos[1, 2] == 100.5 and d.datos[1, 3] == 1.2
    assert np.isnan(d.datos[2, 2]) and d.datos[2, 3] == 0.4
    assert d.rellenos == 3


def test_lector_tolerante_reporta_filas_defectuosas(tmp_path):
    ruta = tmp_path / "x.txt"
    ruta.write_text("LON;LAT;dirolavto;alturaolavto\n01OCT2026 00 0\n-86;21;90;1\n-85.84;21\n"
                    "-85.68;21;abc;1\n-85.52;21;90;2\n", encoding="utf-8")
    a = leer_archivo_semar(ruta)
    assert a.bloques[0].datos.shape == (2, 4)
    assert [linea for linea, _ in a.filas_invalidas] == [4, 5]


def test_lector_reporta_fecha_ilegible_y_datos_sin_fecha(tmp_path):
    ruta = tmp_path / "x.txt"
    ruta.write_text("LON;LAT;dirolavto;alturaolavto\n-86;21;90;1\nOCTUBRE 1 DE 2026\n-85.84;21;90;1\n", encoding="utf-8")
    descripciones = " ".join(p for _, p in leer_archivo_semar(ruta).problemas)
    assert "antes de la línea de fecha" in descripciones and "fecha ilegible" in descripciones


def test_malla_norte_a_sur_se_reconstruye_ascendente():
    lons, lats = nodos(-87.6, -87.12, 20.12, 20.6)
    X, Y = np.meshgrid(lons, lats[::-1])  # filas de norte a sur, como SEMAR
    m = construir_malla(X.ravel(), Y.ravel())
    assert m.rectangular and m.forma == (lats.size, lons.size)
    assert np.allclose(m.lats, lats)
    assert np.allclose(m.a_rejilla(Y.ravel())[:, 0], lats)
    assert not construir_malla(X.ravel()[:-1], Y.ravel()[:-1]).rectangular
