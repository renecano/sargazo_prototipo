"""Paleta del sargazo: que no se confunda con la tierra ni con el mar en ningún mapa base.

Los fondos del satélite y de las calles están medidos en teselas reales y guardados en
docs/contraste.json (scripts/medir_contraste.py); aquí se vuelve a calcular todo con la paleta
actual, sin red, y se exige un mínimo. Si alguien cambia un color de src/view/js/paleta.js y
no vuelve a medir, la última prueba falla.
"""
import json

import numpy as np
import pytest

from scripts import medir_contraste as mc

BASES = ("carta", "satelite", "calles")
VISIONES = ("visión normal", "protanopía", "deuteranopía", "tritanopía")


@pytest.fixture(scope="module")
def medido():
    guardado = json.loads(mc.SALIDA_JSON.read_text(encoding="utf-8"))
    paleta = mc.leer_paleta()
    return paleta, guardado, mc.medir(paleta, guardado["fondos"])


def fila(r, base, empieza):
    return next(e for e in r[base]["elementos"] if e["elemento"].startswith(empieza))


# --- Las cuentas ---------------------------------------------------------------------------

def test_razon_de_contraste_wcag_en_casos_conocidos():
    assert mc.contraste([0, 0, 0], [255, 255, 255]) == pytest.approx(21.0)
    assert mc.contraste([120, 40, 200], [120, 40, 200]) == pytest.approx(1.0)
    assert mc.contraste(mc.hexa("#767676"), [255, 255, 255]) == pytest.approx(4.54, abs=0.01)   # gris mínimo AA para texto
    assert mc.contraste([10, 20, 30], [200, 210, 220]) == mc.contraste([200, 210, 220], [10, 20, 30])


def test_mezcla_con_transparencia_y_hexadecimal():
    assert mc.a_hexa(mc.mezclar([255, 0, 0], 0.5, [0, 0, 255])) == "#800080"
    assert mc.a_hexa(mc.mezclar([10, 20, 30], 0.0, [200, 100, 50])) == "#c86432"
    assert mc.hexa("#7d1a8c").tolist() == [125, 26, 140]


def test_la_simulacion_de_daltonismo_no_altera_los_grises_y_si_los_tonos():
    for tipo in mc.DALTONISMO:
        assert np.allclose(mc.simular([128, 128, 128], tipo), [128, 128, 128], atol=0.6), tipo
        assert np.allclose(np.sum(mc.DALTONISMO[tipo], axis=1), 1.0, atol=1e-5), "cada fila suma 1: el blanco sigue blanco"
    rojo, verde = [220, 40, 40], [40, 160, 40]
    assert mc.delta_e(rojo, verde, "deuteranopía") < 0.5 * mc.delta_e(rojo, verde), "rojo y verde se acercan sin el cono M"
    assert mc.delta_e([0, 0, 0], [255, 255, 255]) == pytest.approx(100.0, abs=0.01)


def test_filtro_css_de_las_calles():
    blanco = np.array([[255.0, 255.0, 255.0]])
    neutro = mc.filtro_css(np.array([[10.0, 200.0, 90.0]]), sepia=0, saturate=1, brightness=1, contrast=1)
    assert np.allclose(neutro, [[10, 200, 90]], atol=1e-6)
    assert np.allclose(mc.filtro_css(blanco, sepia=0, saturate=1, brightness=1, contrast=1), blanco)
    sepia = mc.filtro_css(np.array([[100.0, 100.0, 100.0]]), sepia=1, saturate=1, brightness=1, contrast=1)[0]
    assert sepia[0] > sepia[1] > sepia[2], "el sepia entibia los grises"


# --- La paleta -----------------------------------------------------------------------------

def test_la_paleta_es_json_estricto_con_los_tres_mapas_base(medido):
    paleta, _, _ = medido
    assert set(paleta) == set(BASES)
    for base in BASES:
        p = paleta[base]
        assert len(p["sargazo"]) == 3 and all(c.startswith("#") and len(c) == 7 for c in p["sargazo"])
        for clave in ("bordeSargazo", "densidad", "zona", "varada", "haloVarada", "fondo"):
            assert p[clave].startswith("#") and len(p[clave]) == 7, (base, clave)
    assert paleta["carta"]["sargazo"] == paleta["calles"]["sargazo"], "sobre papel, la misma tinta"
    assert paleta["satelite"]["sargazo"] != paleta["carta"]["sargazo"], "sobre la imagen, trazo claro"


@pytest.mark.parametrize("base", BASES)
def test_las_particulas_contrastan_con_la_tierra_y_con_el_mar(medido, base):
    """Observación del usuario: el sargazo dorado se confundía con la tierra de la carta (la
    partícula lenta de la v0.5.0 inicial daba 1.6:1 contra la tierra y 2.0:1 contra el mar)."""
    _, _, r = medido
    for velocidad in ("lenta", "media", "rápida"):
        e = fila(r, base, f"Partícula a flote, {velocidad}")
        assert e["tierra"] >= 3.0 and e["mar"] >= 3.0, (base, velocidad, e)
    assert fila(r, base, "Partícula a flote, rápida")["mar"] >= 10
    assert fila(r, base, "Zona con el 90 %")["mar"] >= 4.5
    assert fila(r, base, "Densidad ≥ 20 %")["mar"] >= 3.0


def test_sobre_el_satelite_tambien_contrastan_con_los_bajos_turquesa(medido):
    _, _, r = medido
    for velocidad in ("lenta", "media", "rápida"):
        e = fila(r, "satelite", f"Partícula a flote, {velocidad}")
        assert e["mar_claro"] >= 3.0 and e["mar_oscuro"] >= 7.0 and e["tierra_oscuro"] >= 6.0, e


@pytest.mark.parametrize("base", BASES)
def test_lo_varado_se_distingue_del_mapa_y_del_sargazo(medido, base):
    _, _, r = medido
    varado = fila(r, base, "Varado")
    assert varado["tierra"] >= 3.0 and varado["mar"] >= 3.0, varado
    assert r[base]["halo_vs_varado"] >= 4.5, "el halo separa el anillo de lo que tenga debajo"
    assert min(r[base]["borde_vs_particula"]) >= 4.5, "el borde separa cada partícula de lo que tenga debajo"


@pytest.mark.parametrize("base", BASES)
@pytest.mark.parametrize("vision", VISIONES)
def test_no_depende_solo_del_tono_se_distingue_con_daltonismo(medido, base, vision):
    """ΔE de la partícula media contra la tierra, el mar y lo varado, con cada tipo de visión.
    Más de ~10 ya se distingue a simple vista; se pide 40."""
    _, _, r = medido
    d = r[base]["delta_e"][vision]
    assert d["tierra"] >= 40 and d["mar"] >= 40 and d["varado"] >= 40 and d["borde"] >= 40, (base, vision, d)


def test_el_documento_de_contraste_corresponde_a_la_paleta_actual(medido):
    _, guardado, r = medido
    assert guardado["contraste"] == r, "la paleta cambió: corre  python scripts/medir_contraste.py --sin-descarga"
    assert guardado["minimo_wcag"] == 3.0 and len(guardado["zonas"]) == 8
    for base in ("satelite", "calles"):
        f = guardado["fondos"][base]
        assert len(f["teselas"]) == 8 and f["tierra"]["pixeles"] > 100_000 and f["mar"]["pixeles"] > 100_000
    assert guardado["fondos"]["calles"]["filtro"] == mc.FILTRO_CALLES
    md = mc.SALIDA_MD.read_text(encoding="utf-8")
    assert "Partícula a flote, lenta" in md and "protanopía" in md and "Lo que no llega a 3:1" in md
