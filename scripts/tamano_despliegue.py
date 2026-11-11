"""Mide qué entra en un despliegue de Vercel a partir de una construcción local.

    vercel pull --yes --environment=production
    vercel build --prod --yes                     # no crea ningún despliegue
    python scripts/tamano_despliegue.py           # lee .vercel/output

Suma el tamaño de los archivos de cada función (`.vc-config.json` → `filePathMap`, más lo que
el constructor haya copiado dentro de la carpeta `.func`) y de la carpeta `static`, y los
agrupa: dependencias de Python por paquete y archivos del proyecto por carpeta. El tamaño que
reporta Vercel (`vercel inspect <url>`) es el del paquete ya comprimido para Linux; aquí se
mide sin comprimir y con las dependencias del sistema donde se construye, así que sirve para
comparar antes y después de un cambio, no como cifra exacta de facturación.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def medir(salida: Path) -> dict:
    raiz = salida.parent.parent
    resultado = {"funciones": {}, "estaticos": 0, "archivos_estaticos": 0}
    for config in sorted(salida.glob("functions/**/.vc-config.json")):
        func = config.parent
        mapa = json.loads(config.read_text(encoding="utf-8")).get("filePathMap", {})
        grupos, proyecto, total, n = Counter(), Counter(), 0, 0
        archivos = {destino: (raiz / origen) for destino, origen in mapa.items()}
        for f in func.rglob("*"):
            if f.is_file() and f.name != ".vc-config.json":
                archivos.setdefault(f.relative_to(func).as_posix(), f)
        for destino, origen in archivos.items():
            if not origen.is_file():
                continue
            tam = origen.stat().st_size
            total += tam
            n += 1
            partes = destino.replace("\\", "/").split("/")
            if "site-packages" in partes or partes[0].startswith(("_vendor", ".vercel")):
                k = partes.index("site-packages") + 1 if "site-packages" in partes else 1
                grupos["dependencia: " + partes[min(k, len(partes) - 1)].split("-")[0].split(".")[0]] += tam
            else:
                grupos["proyecto"] += tam
                proyecto["/".join(partes[:2]) if len(partes) > 2 else partes[0]] += tam
        resultado["funciones"][func.relative_to(salida).as_posix()] = {
            "bytes": total, "archivos": n, "grupos": dict(grupos.most_common()), "proyecto": dict(proyecto.most_common())}
    estaticos = salida / "static"
    if estaticos.is_dir():
        for f in estaticos.rglob("*"):
            if f.is_file():
                resultado["estaticos"] += f.stat().st_size
                resultado["archivos_estaticos"] += 1
    return resultado


def principal(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=Path(".vercel/output"), help="carpeta de salida de `vercel build`")
    ap.add_argument("--json", action="store_true", help="imprime el resultado en JSON")
    a = ap.parse_args(argv)
    if not a.salida.is_dir():
        print(f"No existe {a.salida}: corre primero  vercel build --prod --yes")
        return 1
    r = medir(a.salida.resolve())
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    mb = lambda b: f"{b / 2**20:8.2f} MB"   # noqa: E731
    for nombre, f in r["funciones"].items():
        print(f"Función {nombre}: {mb(f['bytes'])} sin comprimir en {f['archivos']} archivos")
        for grupo, b in list(f["grupos"].items())[:12]:
            print(f"  {mb(b)}  {grupo}")
        print("  Archivos del proyecto:")
        for carpeta, b in list(f["proyecto"].items())[:14]:
            print(f"    {mb(b)}  {carpeta}")
    print(f"Estáticos: {mb(r['estaticos'])} en {r['archivos_estaticos']} archivos")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
