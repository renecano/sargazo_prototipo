"""Validador de los datos de SEMAR: errores con causa, archivo y acción, y advertencias que no bloquean."""
from datetime import datetime, timezone

import numpy as np
import pytest

from scripts.generar_fixtures import CANCUN, escribir_dirmarea, escribir_salidadatos, ola_analitica
from src.config import ARCHIVO_OLEAJE, ARCHIVO_VIENTO, CARPETA_CORRIENTES, DIR_SEMAR
from src.ingestion.validador import validar_conjunto
from src.model import costa
from tests.conftest import editar_columna, editar_lineas, solo_con_datos_reales


def verif(reporte, vid):
    return next(v for v in reporte.verificaciones if v.id == vid)


def textos(reporte, vid):
    return " ".join(h.detalle for h in verif(reporte, vid).hallazgos)


def test_fixture_valido_con_advertencias_esperadas(semar):
    reporte, datos = validar_conjunto(semar)
    assert reporte.valido, [h.detalle for h in reporte.errores]
    assert datos is not None and datos.viento_u.shape == (1, 11, 10)
    for vid in ("archivos", "formato", "relleno", "rangos", "coherencia"):
        assert verif(reporte, vid).estado == "ok", (vid, verif(reporte, vid).hallazgos)
    assert "una sola hora" in textos(reporte, "fechas")
    assert "no coincide" in textos(reporte, "fechas")
    assert "idénticos" in textos(reporte, "oleaje")
    assert "u_c = 0" in textos(reporte, "corrientes")
    assert datos.corriente_u is None
    assert set(datos.archivos) == {ARCHIVO_VIENTO, ARCHIVO_OLEAJE}
    assert all(len(h) == 64 for h in datos.archivos.values())


def test_advertencia_bloques_identicos_solo_si_lo_son(semar):
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "oleaje").estado == "advertencia"
    escribir_dirmarea(semar / ARCHIVO_OLEAJE, identicos=False)
    reporte, datos = validar_conjunto(semar)
    assert verif(reporte, "oleaje").estado == "ok"
    assert not np.allclose(datos.ola_altura[0], datos.ola_altura[-1], equal_nan=True)


def test_advertencia_fechas_distintas_solo_si_lo_son(semar):
    escribir_dirmarea(semar / ARCHIVO_OLEAJE, fecha=datetime(2026, 8, 19, tzinfo=timezone.utc))
    reporte, _ = validar_conjunto(semar)
    assert "no coincide" not in textos(reporte, "fechas")
    assert reporte.valido


def test_malla_de_oleaje_desplazada_se_interpola(semar):
    """dirmarea está desplazada 0.08° en longitud; la altura (lineal en lon) debe quedar exacta
    en los nodos del modelo cuyos dos vecinos tienen dato."""
    reporte, datos = validar_conjunto(semar)
    assert "desplazada 0.08°" in verif(reporte, "oleaje").resumen
    X, Y = np.meshgrid(datos.lons, datos.lats)
    direccion, altura = ola_analitica(X, Y)
    con_dato = np.isfinite(datos.ola_altura[0])
    assert con_dato.sum() > 40
    # Altura lineal en lon y redondeada a 0.01 m en el archivo: el promedio de los vecinos es exacto ±0.01.
    ambos_vecinos = ~costa.en_tierra(X - 0.08, Y) & ~costa.en_tierra(X + 0.08, Y)
    interiores = con_dato & ambos_vecinos
    assert interiores.sum() >= 30
    assert np.allclose(datos.ola_altura[0][interiores], altura[interiores], atol=0.011)
    assert np.allclose(datos.ola_dir[0][interiores], direccion[interiores], atol=0.011)


def test_falta_salidadatos_es_error_con_accion(semar):
    (semar / ARCHIVO_VIENTO).unlink()
    reporte, datos = validar_conjunto(semar)
    assert not reporte.valido and datos is None
    h = verif(reporte, "archivos").hallazgos[0]
    assert h.archivo == ARCHIVO_VIENTO and "README" in h.accion


def test_falta_dirmarea_solo_advierte(semar):
    (semar / ARCHIVO_OLEAJE).unlink()
    reporte, datos = validar_conjunto(semar)
    assert reporte.valido and datos.ola_altura is None
    assert verif(reporte, "archivos").estado == "advertencia"


def test_fecha_ilegible(semar):
    editar_lineas(semar / ARCHIVO_VIENTO, lambda l: [l[0], "19AGO2026 00"] + l[2:])
    reporte, datos = validar_conjunto(semar)
    assert not reporte.valido
    assert verif(reporte, "fechas").estado == "error"
    assert "ilegible" in textos(reporte, "formato")


def test_columna_ausente(semar):
    def quitar(lineas):
        k = lineas[0].split(";").index("WindsfcDir")
        return [";".join(p for i, p in enumerate(l.split(";")) if i != k) if ";" in l else l for l in lineas]
    editar_lineas(semar / ARCHIVO_VIENTO, quitar)
    reporte, _ = validar_conjunto(semar)
    assert not reporte.valido
    assert "WindsfcDir" in textos(reporte, "formato")


def test_viento_fuera_de_rango(semar):
    editar_columna(semar / ARCHIVO_VIENTO, "WindsfcSp", lambda v: 99.0)
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "rangos").estado == "error"


def test_velocidad_incoherente_con_u_v(semar):
    editar_columna(semar / ARCHIVO_VIENTO, "WindsfcSp", lambda v: v + 1.0)
    reporte, _ = validar_conjunto(semar)
    assert "WindsfcSp difiere" in textos(reporte, "coherencia")


def test_convencion_hacia_invertida(semar):
    editar_columna(semar / ARCHIVO_VIENTO, "WindsfcDir", lambda v: (v + 180) % 360)
    reporte, _ = validar_conjunto(semar)
    assert "hacia" in textos(reporte, "coherencia")


def test_relleno_inconsistente_entre_columnas(semar):
    def romper(lineas):
        partes = lineas[3].split(";")
        partes[4] = "-9.99e+08"  # U sin dato pero V, WindsfcSp y WindsfcDir con dato
        return lineas[:3] + [";".join(partes)] + lineas[4:]
    editar_lineas(semar / ARCHIVO_VIENTO, romper)
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "relleno").estado == "error"


def test_malla_no_rectangular(semar):
    editar_lineas(semar / ARCHIVO_VIENTO, lambda l: l[:-1])
    reporte, _ = validar_conjunto(semar)
    assert "rectangular" in textos(reporte, "malla")


def test_hora_de_oleaje_faltante(semar):
    escribir_dirmarea(semar / ARCHIVO_OLEAJE, horas=[h for h in range(0, 121, 3) if h != 57])
    reporte, _ = validar_conjunto(semar)
    assert not reporte.valido
    assert "+57" in textos(reporte, "oleaje")


def test_altura_de_ola_fuera_de_rango(semar):
    editar_columna(semar / ARCHIVO_OLEAJE, "alturaolavto", lambda v: 45.0)
    reporte, _ = validar_conjunto(semar)
    assert "alturas de ola" in textos(reporte, "rangos")


def test_mascara_de_mar_vs_costa(semar):
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "mascara").estado == "ok", "el fixture usa la misma costa poligonal"
    # Un nodo de tierra con viento: debe contarse como discrepancia.
    def viento_en_tierra(lineas):
        for k, l in enumerate(lineas[2:], start=2):
            if l.endswith("-9.99e+08;-9.99e+08;-9.99e+08;-9.99e+08"):
                p = l.split(";")
                lineas[k] = ";".join(p[:2] + ["90", "90", "-5", "0", "5", "90"])
                break
        return lineas
    editar_lineas(semar / ARCHIVO_VIENTO, viento_en_tierra)
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "mascara").estado == "advertencia"
    assert "no coinciden 1" in verif(reporte, "mascara").resumen


def test_corrientes_opcionales(semar):
    carpeta = semar / CARPETA_CORRIENTES
    carpeta.mkdir()
    lineas = ["LON;LAT;UO;VO", "19AUG2026 00"]
    lon0, lon1, lat0, lat1 = CANCUN
    for lat in np.arange(lat1, lat0 - 0.01, -0.16):
        for lon in np.arange(lon0, lon1 + 0.01, 0.16):
            lineas.append(f"{lon:.2f};{lat:.2f};0.10;0.30")
    (carpeta / "corrientes.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    reporte, datos = validar_conjunto(semar)
    assert verif(reporte, "corrientes").estado == "ok"
    assert np.allclose(datos.corriente_v, 0.30)
    assert "corrientes/corrientes.txt" in datos.archivos
    (carpeta / "corrientes.txt").write_text("\n".join(lineas).replace("0.30", "30.0") + "\n", encoding="utf-8")
    reporte, _ = validar_conjunto(semar)
    assert verif(reporte, "corrientes").estado == "error"


def test_extension_inesperada_advierte(semar):
    (semar / "malicioso.exe").write_bytes(b"MZ")
    reporte, datos = validar_conjunto(semar)
    assert reporte.valido and "malicioso.exe" in [h.archivo for h in verif(reporte, "archivos").hallazgos]


def test_viento_con_varias_horas(semar):
    escribir_salidadatos(semar / ARCHIVO_VIENTO, horas=(0, 60, 120))
    reporte, datos = validar_conjunto(semar)
    assert reporte.valido
    assert not datos.viento_estacionario
    assert list(datos.horas_viento) == [0, 60, 120]
    assert "una sola hora" not in textos(reporte, "fechas")


@solo_con_datos_reales
def test_datos_reales_de_semar():
    """Hallazgos documentados de los archivos de muestra (solo si están en data/semar/)."""
    reporte, datos = validar_conjunto(DIR_SEMAR)
    assert reporte.valido
    assert datos.lons.size * datos.lats.size == 1989
    assert int(datos.mar.sum()) == 1314
    assert "1045 con sfcDirWindWa" in verif(reporte, "relleno").resumen
    assert datos.viento_estacionario and datos.inicio == datetime(2026, 8, 19, tzinfo=timezone.utc)
    assert "Los 41 bloques de oleaje son idénticos" in textos(reporte, "oleaje")
    assert "no coincide" in textos(reporte, "fechas")
    assert "desplazada 0.08°" in verif(reporte, "oleaje").resumen
    assert verif(reporte, "coherencia").estado == "ok"
