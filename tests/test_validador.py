"""Validador: detecta archivos faltantes, coordenadas fuera de rango, columnas ausentes y más."""
from pathlib import Path

import numpy as np

from src.ingestion.lector import leer_tabla
from src.ingestion.validador import validar_conjunto
from tests.conftest import LATS_PEQ, LONS_PEQ, archivos_horarios, editar_filas


def verificacion(reporte, vid):
    return next(v for v in reporte.verificaciones if v.id == vid)


def test_conjunto_sintetico_valido(conjunto):
    reporte, datos = validar_conjunto(conjunto)
    assert reporte.valido, [h.detalle for h in reporte.errores]
    assert reporte.archivos_encontrados == 120
    assert datos is not None
    assert datos.viento_u.shape == (120, LATS_PEQ.size, LONS_PEQ.size)
    assert datos.sintetico and datos.corrientes_esquematicas
    # Las corrientes esquemáticas se reportan como advertencia, nunca se ocultan.
    assert verificacion(reporte, "corrientes").estado == "advertencia"
    for vid in ("archivos", "continuidad", "columnas", "coordenadas", "ausentes", "rangos", "unidades", "convencion"):
        assert verificacion(reporte, vid).estado == "ok", vid


def test_detecta_archivo_horario_faltante(conjunto):
    faltante = archivos_horarios(conjunto)[30]
    faltante.unlink()
    reporte, datos = validar_conjunto(conjunto)
    assert not reporte.valido and datos is None
    assert verificacion(reporte, "archivos").estado == "error"
    continuidad = verificacion(reporte, "continuidad")
    assert continuidad.estado == "error"
    hallazgo = continuidad.hallazgos[0]
    assert hallazgo.archivo == faltante.name
    assert "+30" in hallazgo.detalle
    assert hallazgo.accion


def test_detecta_latitud_fuera_de_rango(conjunto):
    archivo = archivos_horarios(conjunto)[10]

    def lat_mala(columnas, filas):
        filas[3][columnas.index("LAT")] = "95.00"
        return columnas, filas

    editar_filas(archivo, lat_mala)
    reporte, datos = validar_conjunto(conjunto)
    assert not reporte.valido and datos is None
    coord = verificacion(reporte, "coordenadas")
    assert coord.estado == "error"
    assert coord.hallazgos[0].archivo == archivo.name
    assert "Latitud fuera de rango (95)" in coord.hallazgos[0].detalle


def test_detecta_columna_ausente(conjunto):
    archivo = archivos_horarios(conjunto)[80]

    def quitar(columnas, filas):
        k = columnas.index("WindsfcDir")
        return columnas[:k] + columnas[k + 1:], [f[:k] + f[k + 1:] for f in filas]

    editar_filas(archivo, quitar)
    reporte, datos = validar_conjunto(conjunto)
    assert not reporte.valido and datos is None
    col = verificacion(reporte, "columnas")
    assert col.estado == "error"
    assert col.hallazgos[0].archivo == archivo.name
    assert "WindsfcDir" in col.hallazgos[0].detalle


def test_reporta_todos_los_errores_a_la_vez(conjunto):
    archivos = archivos_horarios(conjunto)
    archivos[5].unlink()
    editar_filas(archivos[6], lambda c, f: (c, [r if i else r[:1] + ["-99.0"] + r[2:] for i, r in enumerate(f)]))
    reporte, _ = validar_conjunto(conjunto)
    estados = {v.id: v.estado for v in reporte.verificaciones}
    assert estados["continuidad"] == "error"
    assert estados["coordenadas"] == "error"


def test_detecta_convencion_hacia_invertida(conjunto):
    for archivo in archivos_horarios(conjunto):
        def invertir(columnas, filas):
            k = columnas.index("WindsfcDir")
            for f in filas:
                f[k] = f"{(float(f[k]) + 180) % 360:.2f}"
            return columnas, filas
        editar_filas(archivo, invertir)
    reporte, _ = validar_conjunto(conjunto)
    conv = verificacion(reporte, "convencion")
    assert conv.estado == "error"
    assert "hacia" in conv.hallazgos[0].detalle


def test_detecta_viento_fuera_de_rango(conjunto):
    archivo = archivos_horarios(conjunto)[0]

    def relleno(columnas, filas):
        filas[0][columnas.index("WindsfcSp")] = "9999"
        return columnas, filas

    editar_filas(archivo, relleno)
    reporte, _ = validar_conjunto(conjunto)
    assert verificacion(reporte, "rangos").estado == "error"


def test_detecta_viento_ausente(conjunto):
    archivo = archivos_horarios(conjunto)[3]
    editar_filas(archivo, lambda c, f: (c, [r[:2] + ["nan"] + r[3:] for r in f]))
    reporte, _ = validar_conjunto(conjunto)
    assert verificacion(reporte, "ausentes").estado == "error"


def test_ignora_extension_inesperada_con_advertencia(conjunto):
    (conjunto / "malicioso.exe").write_bytes(b"MZ")
    reporte, datos = validar_conjunto(conjunto)
    assert reporte.valido and datos is not None
    arch = verificacion(reporte, "archivos")
    assert arch.estado == "advertencia"
    assert "malicioso.exe" == arch.hallazgos[0].archivo


def test_detecta_malla_inconsistente_entre_archivos(conjunto):
    editar_filas(archivos_horarios(conjunto)[50], lambda c, f: (c, f[:-1]))  # un nodo menos
    reporte, _ = validar_conjunto(conjunto)
    assert verificacion(reporte, "coordenadas").estado == "error"


def test_sin_corrientes_es_error(conjunto):
    for p in (conjunto / "corrientes").glob("*.txt"):
        p.unlink()
    reporte, datos = validar_conjunto(conjunto)
    assert not reporte.valido and datos is None
    assert verificacion(reporte, "corrientes").estado == "error"


def test_carpeta_inexistente(tmp_path):
    reporte, datos = validar_conjunto(tmp_path / "no_existe")
    assert not reporte.valido and datos is None
    assert "generar_datos_demo.py" in reporte.verificaciones[0].hallazgos[0].accion


def test_lector_tolera_filas_defectuosas(tmp_path):
    ruta = tmp_path / "x_2026100100.txt"
    ruta.write_text("# fecha_validez: 2026-10-01T00:00Z\nLON LAT U\n-86.0 21.0 1.0\n-86.16 21.0\n-86.32 21.0 abc\n", encoding="utf-8")
    t = leer_tabla(ruta)
    assert t.columnas == ["LON", "LAT", "U"]
    assert t.datos.shape == (1, 3)
    assert np.allclose(t.datos[0], [-86.0, 21.0, 1.0])
    assert len(t.filas_invalidas) == 2
    assert t.metadatos["fecha_validez"] == "2026-10-01T00:00Z"


def test_conjunto_completo_de_demo_si_existe():
    """Si ya se generó data/demo/, el validador debe aceptarlo tal cual (como lo verá la app)."""
    demo = Path(__file__).resolve().parent.parent / "data" / "demo"
    if not any(demo.glob("*.txt")):
        import pytest
        pytest.skip("data/demo/ no generado")
    reporte, datos = validar_conjunto(demo)
    assert reporte.valido
    assert datos.mar.sum() == 1323
