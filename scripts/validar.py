"""Valida PMS contra el sargazo observado por satélite. Corre todo desde cero con un comando.

    python -m pip install -r requirements-validacion.txt
    python scripts/validar.py

Pasos (cada uno guarda su resultado en data/validacion/ y se reanuda si se corta):
  1. Inventario AFAI 2022–2026 (NOAA AOML ERDDAP) y detección de sargazo.
  2. Selección automática de casos (calibración < 2025 ≤ evaluación) y caso de la fecha
     del dirmarea.txt de SEMAR.
  3. Oleaje real (Open-Meteo/MFWAM) → dirmarea.txt en el formato de SEMAR por caso.
  4. Calibración de γ y K_h (E3) solo con los casos de calibración.
  5. Experimentos E0–E5 por caso y métricas (FSS, centroide, MCC, costa).
  6. Tablas, figuras, docs/validacion.md, página /validacion y bloque del README.

Open-Meteo gratuito permite 10 000 llamadas por día y cada punto cuenta como una llamada
(~900 por caso). Si se agota la cuota, el script se detiene, dice qué falta y al volver a
correrlo continúa donde se quedó.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.config import DIR_SEMAR  # noqa: E402
from src.ingestion.validador import validar_conjunto  # noqa: E402
from src.model.campos import CamposOleaje  # noqa: E402
from validacion import casos as mod_casos  # noqa: E402
from validacion import config as cfg  # noqa: E402
from validacion import documento, ejecutar, experimentos, inventario, reporte  # noqa: E402
from validacion.experimentos import Contexto, Experimento, Forzamientos  # noqa: E402
from validacion.openmeteo import CuotaAgotada  # noqa: E402


def registrar(msg: str):
    print(msg, flush=True)


def principal(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solo-reporte", action="store_true", help="solo rehace tablas, figuras y documentos")
    a = p.parse_args(argv)
    t_inicio = time.perf_counter()
    cache, salida = cfg.DIR_CACHE, cfg.DIR_RESULTADOS
    salida.mkdir(parents=True, exist_ok=True)

    registrar("1. Inventario AFAI")
    m, det, dias = inventario.construir(cache, registrar)
    registrar(f"   {len(dias)} imágenes; mar evaluado {int(m.mar_util.sum())} píxeles; "
              f"{int(m.persistente.sum())} brillantes persistentes excluidos")

    registrar("2. Selección de casos")
    sel = mod_casos.seleccionar(dias, det, m)
    cal = [c for c in sel.casos if c.conjunto == "calibracion"]
    eva = [c for c in sel.casos if c.conjunto == "evaluacion"]
    registrar(f"   {sel.candidatos} días candidatos → {len(sel.casos)} casos ({len(cal)} calibración, "
              f"{len(eva)} evaluación); caso SEMAR: {sel.caso_semar.id if sel.caso_semar else 'sin imagen'}")
    ctx = Contexto(m)
    estado = {"pendiente": []}

    def forzamientos(caso, con_extra):
        return experimentos.preparar_forzamientos(caso, cache, registrar, con_extra)

    if not a.solo_reporte:
        try:
            registrar("3–4. Oleaje real y calibración de E3 (solo casos de calibración)")
            filas_cal = []
            for c in cal:
                f = forzamientos(c, False)
                filas_cal += ejecutar.calibrar_caso(c, ctx, det, f, cache, registrar)
                registrar(f"   calibrado {c.id}")
            gamma, kh, tabla_cal = ejecutar.elegir_calibracion(filas_cal)
            registrar(f"   E3: γ = {gamma:g}, K_h = {kh:g}")
            lista = experimentos.experimentos(gamma, kh)

            # Primero lo que ya no necesita descargas (oleaje de calibración y caso SEMAR en caché),
            # luego los casos de evaluación, que piden corriente y viento.
            registrar("5. Experimentos: casos de calibración (E0–E3; para las tablas con todos los casos)")
            # En calibración solo se descarga el oleaje (lo único que necesita E3): E4 y E5 se
            # evalúan en los casos de evaluación, que son los de la tabla principal.
            for c in cal:
                ejecutar.procesar_caso(c, ctx, det, det.archivo, forzamientos(c, False), lista, cache, registrar)
            if sel.caso_semar:
                registrar("   caso de la fecha del dirmarea.txt de SEMAR")
                _, conj = validar_conjunto(DIR_SEMAR)
                f_semar = Forzamientos(CamposOleaje(conj), None, None, {"oleaje": "dirmarea.txt de SEMAR"})
                extra = (Experimento("E2-SEMAR", "E2 con el dirmarea.txt de SEMAR", gamma=1.0, kh=cfg.KH_V03), f_semar)
                ejecutar.procesar_caso(sel.caso_semar, ctx, det, det.archivo, forzamientos(sel.caso_semar, True),
                                       lista, cache, registrar, extra_semar=extra)
            registrar("   casos de evaluación (E0–E5)")
            for c in eva:
                ejecutar.procesar_caso(c, ctx, det, det.archivo, forzamientos(c, True), lista, cache, registrar)
        except CuotaAgotada as e:
            registrar(f"\nOpen-Meteo agotó la cuota gratuita: {e}\nVuelve a correr el script más tarde; "
                      "continuará donde se quedó (todo lo descargado está en la caché).")
            return 2
    else:
        # Solo lo que ya está en la caché (no descarga ni calcula).
        filas_cal = []
        for c in cal:
            ruta = cache / "casos" / c.id / "calibracion.json"
            if ruta.is_file():
                filas_cal += json.loads(ruta.read_text(encoding="utf-8"))
        gamma, kh, tabla_cal = ejecutar.elegir_calibracion(filas_cal)

    registrar("6. Tablas, figuras y documentos")
    datos = documento.Insumos(
        seleccion=sel, mascaras=m, dias=dias, contexto=ctx, gamma=gamma, kh=kh, tabla_calibracion=tabla_cal,
        filas_calibracion=filas_cal,
        resultados=[ejecutar.cargar_resultado(c, cache) for c in sel.casos],
        resultado_semar=ejecutar.cargar_resultado(sel.caso_semar, cache) if sel.caso_semar else None,
        comparacion_semar=ejecutar.comparar_semar(cache, registrar),
        generado=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        duracion_s=time.perf_counter() - t_inicio)
    documento.escribir_todo(datos, salida, registrar)
    registrar(f"Listo en {time.perf_counter() - t_inicio:.0f} s. Resultados en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
