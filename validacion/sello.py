"""Sello de la caché de la validación: con qué modelo y qué costa se calculó cada carpeta.

La detección (mar del modelo), la calibración y los experimentos dependen de la versión del
modelo y de la máscara de costa. Cada carpeta de resultados derivados guarda un `sello.json`;
si no coincide con el modelo y la costa actuales, lo que haya ahí no se reutiliza. Las
descargas (AFAI, Copernicus Marine, Open-Meteo) no dependen del modelo y no llevan sello.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.config import VERSION_MODELO
from src.model import costa

NOMBRE = "sello.json"


def actual() -> dict:
    return {"version_modelo": VERSION_MODELO, "costa_sha256": costa.procedencia()["costa"]["sha256_bits"]}


def vigente(directorio: Path) -> bool:
    ruta = Path(directorio) / NOMBRE
    if not ruta.is_file():
        return False
    try:
        return json.loads(ruta.read_text(encoding="utf-8")) == actual()
    except (OSError, json.JSONDecodeError):
        return False


def renovar(directorio: Path, patrones: tuple[str, ...]) -> list[str]:
    """Si la carpeta no tiene el sello vigente, retira los archivos derivados que casen con
    `patrones` (calculados con otro modelo u otra costa) y la sella. Devuelve lo retirado."""
    directorio = Path(directorio)
    if vigente(directorio):
        return []
    retirados = []
    if directorio.is_dir():
        for patron in patrones:
            for ruta in directorio.glob(patron):
                ruta.unlink()
                retirados.append(ruta.name)
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / NOMBRE).write_text(json.dumps(actual(), indent=1), encoding="utf-8")
    return retirados
