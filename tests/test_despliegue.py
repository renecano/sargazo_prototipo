"""Qué sube cada despliegue de Vercel: solo lo que la app usa en producción.

`.vercelignore` es una lista blanca con la sintaxis de `.gitignore`; aquí se evalúa con el
propio git sobre los archivos versionados, que son los que recibe un despliegue desde GitHub.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PRESUPUESTO_MB = 12.0   # archivos del proyecto por despliegue (sin las dependencias de Python)


def _git(*args: str) -> list[str]:
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        pytest.skip("git no está disponible")
    if r.returncode != 0:
        pytest.skip(f"git no pudo listar los archivos: {r.stderr.strip()[:120]}")
    return [linea for linea in r.stdout.splitlines() if linea]


@pytest.fixture(scope="module")
def subidos() -> set[str]:
    versionados = set(_git("ls-files"))
    ignorados = set(_git("ls-files", "-ci", "--exclude-from=.vercelignore"))
    return versionados - ignorados


def test_sube_todo_lo_que_la_app_usa(subidos):
    necesarios = {"api/index.py", "requirements.txt", ".python-version", "vercel.json", "public/.gitkeep",
                  "data/semar/dirmarea.txt", "src/config.py", "src/api/app.py", "src/view/index.html",
                  "src/model/datos/costa.npz", "src/model/datos/costa.json", "src/model/datos/localidades.json"}
    assert necesarios <= subidos, f"faltan en el despliegue: {sorted(necesarios - subidos)}"
    fuente = {f for f in _git("ls-files", "src", "api")}
    assert fuente <= subidos, f"código de la app fuera del despliegue: {sorted(fuente - subidos)[:5]}"


def test_la_pagina_de_validacion_sube_completa(subidos):
    pagina = RAIZ / "docs" / "validacion" / "index.html"
    if not pagina.is_file():
        pytest.skip("Aún no hay resultados de validación en docs/validacion/")
    assert "docs/validacion/index.html" in subidos
    figuras = set(re.findall(r'src="(figuras/[^"]+)"', pagina.read_text(encoding="utf-8")))
    assert figuras, "la página de validación no enlaza ninguna figura"
    faltan = {f for f in figuras if f"docs/validacion/{f}" not in subidos}
    assert not faltan, f"figuras de /validacion fuera del despliegue: {sorted(faltan)}"
    assert "docs/validacion/fss_resumen.csv" in subidos   # las tablas se descargan desde /validacion/


def test_no_sube_nada_de_desarrollo(subidos):
    raices = {f.split("/")[0] for f in subidos}
    assert raices == {"api", "src", "public", "data", "docs", "requirements.txt", ".python-version", "vercel.json"}, sorted(raices)
    assert {f for f in subidos if f.startswith("data/")} == {"data/semar/dirmarea.txt"}
    fuera = {f for f in subidos if f.startswith("docs/") and not f.startswith("docs/validacion/")}
    assert not fuera, f"documentación o capturas en el despliegue: {sorted(fuera)[:5]}"


def test_el_despliegue_no_vuelve_a_crecer(subidos):
    total = sum((RAIZ / f).stat().st_size for f in subidos if (RAIZ / f).is_file()) / 2**20
    assert total <= PRESUPUESTO_MB, (
        f"el despliegue sube {total:.1f} MB de archivos del proyecto (presupuesto {PRESUPUESTO_MB} MB): "
        "revisa .vercelignore o corre scripts/tamano_despliegue.py")


def test_solo_main_despliega_y_no_se_publican_copias_estaticas():
    config = json.loads((RAIZ / "vercel.json").read_text(encoding="utf-8"))
    ramas = config["git"]["deploymentEnabled"]
    assert ramas["main"] is True
    assert ramas["*"] is False and ramas["**"] is False   # sin despliegues de vista previa por rama
    # Con public/ presente, Vercel solo publica esa carpeta como estáticos; la app la sirve la función.
    assert (RAIZ / "public").is_dir()
    assert [p.name for p in (RAIZ / "public").iterdir()] == [".gitkeep"]
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]
