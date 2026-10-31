"""Validador de dirmarea.txt: errores con causa, archivo y acción; advertencias que no bloquean."""
from datetime import datetime, timezone

import numpy as np

from scripts.generar_fixtures import crear_fixture, escribir_dirmarea
from src.config import ARCHIVO_OLEAJE, DIR_SEMAR
from src.ingestion.validador import validar_conjunto
from tests.conftest import editar_columna, editar_lineas, solo_con_datos_reales


def verif(reporte, vid):
    return next(v for v in reporte.verificaciones if v.id == vid)


def textos(reporte, vid):
    return " ".join(h.detalle for h in verif(reporte, vid).hallazgos)


def test_fixture_valido_con_advertencias_esperadas(semar):
    reporte, datos = validar_conjunto(semar)
    assert reporte.valido, [h.detalle for h in reporte.errores]
    assert datos.altura.shape == (41, 11, 11) and datos.direccion.shape == (41, 11, 11)
    for vid in ("archivos", "formato", "fechas", "relleno", "rangos", "mascara"):
        assert verif(reporte, vid).estado == "ok", (vid, verif(reporte, vid).hallazgos)
    assert "idénticos" in textos(reporte, "variacion")
    assert "cubre 11 × 11" in textos(reporte, "malla"), "el recuadro de Cancún cubre parte del dominio"
    assert datos.bloques_identicos and list(datos.horas) == list(range(0, 121, 3))
    assert datos.fecha_base == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert len(datos.huella_sha256) == 64


def test_dominio_completo_sin_advertencia_de_cobertura(tmp_path):
    reporte, datos = validar_conjunto(crear_fixture(tmp_path / "semar", completo=True))
    assert reporte.valido and verif(reporte, "malla").estado == "ok"
    assert datos.lons.size * datos.lats.size == 1989
    assert datos.lons[0] == -92.08 and datos.lats[-1] == 23.0


def test_advertencia_de_bloques_identicos_solo_si_lo_son(semar):
    escribir_dirmarea(semar / ARCHIVO_OLEAJE, identicos=False)
    reporte, datos = validar_conjunto(semar)
    assert verif(reporte, "variacion").estado == "ok"
    assert not datos.bloques_identicos
    assert not np.allclose(datos.altura[0], datos.altura[-1], equal_nan=True)


def test_relleno_a_nan_y_mascara_de_mar(semar):
    _reporte, datos = validar_conjunto(semar)
    assert np.isnan(datos.altura[0][~datos.mar]).all()
    assert np.isfinite(datos.altura[0][datos.mar]).all()
    assert 0 < datos.mar.sum() < datos.mar.size


def test_falta_el_archivo_es_error_con_accion(semar):
    (semar / ARCHIVO_OLEAJE).unlink()
    reporte, datos = validar_conjunto(semar)
    assert not reporte.valido and datos is None
    h = verif(reporte, "archivos").hallazgos[0]
    assert h.archivo == ARCHIVO_OLEAJE and "README" in h.accion


def test_fecha_ilegible(semar):
    editar_lineas(semar / ARCHIVO_OLEAJE, lambda l: [l[0], "01OCTU2026 00 0"] + l[2:])
    reporte, _ = validar_conjunto(semar)
    assert not reporte.valido
    assert "ilegible" in textos(reporte, "formato")


def test_columna_ausente(semar):
    def quitar(lineas):
        return [";".join(p for i, p in enumerate(l.split(";")) if i != 3) if ";" in l else l for l in lineas]
    editar_lineas(semar / ARCHIVO_OLEAJE, quitar)
    reporte, _ = validar_conjunto(semar)
    assert not reporte.valido and "alturaolavto" in textos(reporte, "formato")


def test_hora_faltante(semar):
    escribir_dirmarea(semar / ARCHIVO_OLEAJE, horas=[h for h in range(0, 121, 3) if h != 57])
    reporte, _ = validar_conjunto(semar)
    assert not reporte.valido and "+57" in textos(reporte, "fechas")


def test_horas_desordenadas(semar):
    horas = list(range(0, 121, 3))
    horas[3], horas[4] = horas[4], horas[3]
    escribir_dirmarea(semar / ARCHIVO_OLEAJE, horas=horas)
    reporte, _ = validar_conjunto(semar)
    assert "desordenadas" in textos(reporte, "fechas")


def test_altura_fuera_de_rango(semar):
    editar_columna(semar / ARCHIVO_OLEAJE, "alturaolavto", lambda v: 45.0)
    reporte, _ = validar_conjunto(semar)
    assert not reporte.valido and "alturas de ola" in textos(reporte, "rangos")


def test_direccion_fuera_de_rango(semar):
    editar_columna(semar / ARCHIVO_OLEAJE, "dirolavto", lambda v: 400.0)
    reporte, _ = validar_conjunto(semar)
    assert "direcciones" in textos(reporte, "rangos")


def test_relleno_inconsistente(semar):
    def romper(lineas):
        k = next(i for i, l in enumerate(lineas[2:], start=2) if "-9.99e+08" not in l)
        p = lineas[k].split(";")
        lineas[k] = ";".join(p[:2] + ["-9.99e+08", p[3]])   # dirección sin dato, altura con dato
        return lineas
    editar_lineas(semar / ARCHIVO_OLEAJE, romper)
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "relleno").estado == "error"


def test_malla_no_rectangular(semar):
    editar_lineas(semar / ARCHIVO_OLEAJE, lambda l: l[:-1])   # el último bloque pierde un nodo
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "malla").estado == "error"


def test_malla_fuera_del_recuadro(tmp_path):
    escribir_dirmarea(tmp_path / ARCHIVO_OLEAJE, extension=(-97.84, -96.40, 21.08, 22.04))
    reporte, _ = validar_conjunto(tmp_path)
    assert not reporte.valido and "no cubre" in textos(reporte, "malla")


def test_mascara_de_mar_vs_costa(semar):
    def ola_en_tierra(lineas):
        for k, l in enumerate(lineas[2:], start=2):
            if l.endswith("-9.99e+08;-9.99e+08"):
                lineas[k] = ";".join(l.split(";")[:2] + ["90", "1"])
                break
        return lineas
    editar_lineas(semar / ARCHIVO_OLEAJE, ola_en_tierra)
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "mascara").estado == "advertencia"
    assert "no coinciden 1" in verif(reporte, "mascara").resumen


def test_otros_archivos_solo_advierten(semar):
    (semar / "salidadatos.txt").write_text("LON;LAT\n", encoding="utf-8")
    (semar / "malicioso.exe").write_bytes(b"MZ")
    reporte, datos = validar_conjunto(semar)
    assert reporte.valido and datos is not None
    archivos = [h.archivo for h in verif(reporte, "archivos").hallazgos]
    assert "salidadatos.txt" in archivos and "malicioso.exe" in archivos


@solo_con_datos_reales
def test_datos_reales_de_semar():
    """Hallazgos documentados del archivo de muestra (si está en data/semar/)."""
    reporte, datos = validar_conjunto(DIR_SEMAR)
    assert reporte.valido
    assert datos.lons.size * datos.lats.size == 1989
    assert int(datos.mar.sum()) == 1295
    assert datos.bloques_identicos and datos.horas.size == 41
    assert "Los 41 bloques son idénticos" in textos(reporte, "variacion")
    assert verif(reporte, "malla").estado == "ok"
    assert 0.1 <= np.nanmin(datos.altura) and np.nanmax(datos.altura) <= 2.0
