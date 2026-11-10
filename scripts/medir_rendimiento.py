"""Mide tiempos y memoria del prototipo en esta máquina y escribe docs/rendimiento.md.

Dos partes:
  1. Servidor: validación, simulación, registro y carga de la costa (Python).
  2. Navegador: fluidez de la interfaz (cuadros por segundo) con el oleaje animado y la
     simulación reproduciéndose, a velocidad real del equipo y con el procesador frenado
     4× y 6× (Chromium, DevTools), para estimar un equipo más modesto que este.

Uso (PowerShell):
    python scripts/medir_rendimiento.py
"""
from __future__ import annotations

import gzip
import json
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

from src.api.almacen import armar_registro  # noqa: E402
from src.api.servicios import ServicioDatos  # noqa: E402
from src.config import ARCHIVO_OLEAJE, DIR_SEMAR  # noqa: E402
from src.ingestion.validador import validar_conjunto  # noqa: E402
from src.config import VERSION_MODELO  # noqa: E402
from src.model import costa  # noqa: E402
from src.model.campos import CamposOleaje  # noqa: E402
from src.model.metricas import resumir  # noqa: E402
from src.model.simulacion import Parametros, simular  # noqa: E402

REPETICIONES = 3


def medir(funcion, repeticiones=REPETICIONES):
    tiempos, resultado = [], None
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        resultado = funcion()
        tiempos.append(time.perf_counter() - t0)
    return statistics.median(tiempos), max(tiempos), resultado


def pico_memoria(funcion) -> float:
    """Pico de memoria asignada por Python (MB) en una corrida aparte: tracemalloc vuelve lento el código."""
    tracemalloc.start()
    funcion()
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return pico / 2**20


def memoria_sistema() -> str:
    """RAM total y libre al medir (solo Windows); el resultado depende mucho de lo que haya abierto."""
    if platform.system() != "Windows":
        return "n/d"
    import ctypes

    class Estado(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    e = Estado()
    e.dwLength = ctypes.sizeof(Estado)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
    return f"{e.ullTotalPhys / 2**30:.1f} GB de RAM, {e.ullAvailPhys / 2**30:.1f} GB libres al medir"


JS_MEDIR = """async ([segundos, velocidad]) => {
    const pms = window.pms, d = window.pmsDepurar;
    d.ponerHora(0);
    document.getElementById('lt-velocidad').value = String(velocidad);
    document.getElementById('lt-velocidad').dispatchEvent(new Event('change'));
    if (!pms.reproduciendo) document.getElementById('btn-play').click();
    const tiempos = [];
    let ultimo = performance.now();
    const fin = ultimo + segundos * 1000;
    await new Promise((listo) => { const tic = (t) => { tiempos.push(t - ultimo); ultimo = t; if (t < fin) requestAnimationFrame(tic); else listo(); }; requestAnimationFrame(tic); });
    const tramos = pms.dibujo.tramosEstela;
    if (pms.reproduciendo) document.getElementById('btn-play').click();
    tiempos.shift();
    tiempos.sort((a, b) => a - b);
    const suma = tiempos.reduce((a, b) => a + b, 0);
    const t0 = performance.now();
    for (let k = 0; k < 20; k++) d.capas.particulas.redibujar();
    const particulas = (performance.now() - t0) / 20;
    const t1 = performance.now();
    for (let k = 0; k < 20; k++) d.oleaje.avanzar(0.033);
    const oleaje = (performance.now() - t1) / 20;
    return { fps: 1000 * tiempos.length / suma, p95: tiempos[Math.floor(tiempos.length * 0.95)], maximo: tiempos[tiempos.length - 1],
             particulas, oleaje, trazos: d.oleaje.trazos.length, tramos,
             heap: performance.memory ? performance.memory.usedJSHeapSize / 2 ** 20 : null };
}"""


def medir_navegador() -> tuple[list[tuple], str]:
    """Fluidez de la interfaz en Chromium a 1366 × 768, con y sin freno de procesador."""
    try:
        import socket
        import tempfile
        import threading

        import uvicorn
        from playwright.sync_api import sync_playwright

        from src.api.app import crear_app
    except ImportError as e:
        return [], f"no se midió ({e})"
    with socket.socket() as zocalo:
        zocalo.bind(("127.0.0.1", 0))
        puerto = zocalo.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(crear_app(DIR_SEMAR, Path(tempfile.mkdtemp())), host="127.0.0.1", port=puerto, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    filas, navegador = [], ""
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001
            nav = p.chromium.launch()
        navegador = f"{nav.browser_type.name} {nav.version}"
        pg = nav.new_page(viewport={"width": 1366, "height": 768})
        pg.add_init_script("localStorage.setItem('pms.recorrido.visto.v4', '1')")
        transferido = {"bytes": 0, "n": 0}
        pg.on("response", lambda r: transferido.update(bytes=transferido["bytes"] + int(r.headers.get("content-length", 0) or 0), n=transferido["n"] + 1))
        t0 = time.perf_counter()
        pg.goto(f"http://127.0.0.1:{puerto}")
        pg.wait_for_function("window.pms && window.pms.estado === 'listo' && window.pms.costa && window.pms.localidades", timeout=60_000)
        carga = time.perf_counter() - t0
        filas.append(("Abrir la página hasta «Listo» (carta, costa, localidades y oleaje)", f"{carga:.1f} s", "—",
                      f"{transferido['n']} respuestas, {transferido['bytes'] / 2**20:.2f} MB transferidos"))
        cdp = pg.context.new_cdp_session(pg)
        for n in (2000, 5000):
            pg.click('#pasos [data-paso="2"]')
            pg.evaluate("(n) => { document.getElementById('avanzado').open = true; document.getElementById('p-n').value = n; }", n)
            anterior = pg.evaluate("window.pms.sim && window.pms.sim.id")
            pg.click("#btn-simular")
            pg.wait_for_function("(a) => window.pms.sim && window.pms.sim.id !== a && window.pms.estado === 'resultado'", arg=anterior, timeout=120_000)
            if pg.evaluate("window.pms.reproduciendo"):
                pg.click("#btn-play")
            for freno in (1, 4, 6):
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": freno})
                m = pg.evaluate(JS_MEDIR, [6, 6])
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
                etiqueta = "a velocidad real" if freno == 1 else f"con el procesador frenado {freno}×"
                memoria = f"; memoria de JS {m['heap']:.0f} MB" if m["heap"] else ""
                filas.append((f"Reproducir {n:,} partículas con estelas y oleaje animado, {etiqueta}".replace(",", " "),
                              f"{m['fps']:.0f} cuadros/s", f"{m['maximo']:.0f} ms el cuadro más lento",
                              f"estela en {m['tramos']} tramos al terminar; JavaScript: partículas {m['particulas']:.1f} ms y oleaje {m['oleaje']:.1f} ms por cuadro "
                              f"({m['trazos']} trazos){memoria}"))
        nav.close()
    srv.should_exit = True
    return filas, navegador


def principal() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not (DIR_SEMAR / ARCHIVO_OLEAJE).is_file():
        print(f"Falta {ARCHIVO_OLEAJE} en {DIR_SEMAR} (ver data/semar/README.md).")
        return 1
    filas = []
    med, mx, (reporte, conjunto) = medir(lambda: validar_conjunto(DIR_SEMAR))
    filas.append(("Validar dirmarea.txt (lectura de 196 554 filas y 8 verificaciones)",
                  f"{med:.2f} s", f"{mx:.2f} s", f"{pico_memoria(lambda: validar_conjunto(DIR_SEMAR)):.0f} MB"))

    costa.mascara.cache_clear()
    costa._archivo.cache_clear()
    t0 = time.perf_counter()
    mascara = costa.mascara()
    filas.append(("Cargar la máscara de costa (8 240 × 6 320 celdas de 0.001°)", f"{time.perf_counter() - t0:.2f} s", "—",
                  f"{mascara.bits.nbytes / 2**20:.1f} MB en memoria; {costa.ARCHIVO_COSTA.stat().st_size / 1024:.0f} KB en disco"))

    campos = CamposOleaje(conjunto)
    dominio = (float(conjunto.lons[0]), float(conjunto.lons[-1]), float(conjunto.lats[0]), float(conjunto.lats[-1]))
    varamiento = ""
    for etiqueta, lon, lat in (("frente a Cancún", -86.66, 21.12), ("en mar abierto", -86.30, 21.00)):
        for n in (500, 2000, 5000):
            p = Parametros(lon=lon, lat=lat, particulas=n, horizonte_h=120)
            med, mx, r = medir(lambda: simular(campos, p, dominio=dominio))
            if n == 2000 and not varamiento:
                hv = r.hora_varada[r.hora_varada >= 0]
                varamiento = (f"el {100 * hv.size / n:.0f} % de las partículas vara entre la hora {hv.min()} y la {hv.max()} "
                              f"(mediana {int(np.median(hv))})")
            filas.append((f"Simular {n:,} partículas × 120 h {etiqueta}".replace(",", " "), f"{med:.2f} s", f"{mx:.2f} s",
                          f"{pico_memoria(lambda: simular(campos, p, dominio=dominio)):.0f} MB"))
    p = Parametros(lon=-86.30, lat=21.00, particulas=2000, horizonte_h=120)
    r = simular(campos, p, dominio=dominio)
    t0 = time.perf_counter()
    reg = armar_registro(r, resumir(r), conjunto.resumen())
    texto = json.dumps(reg, ensure_ascii=False, separators=(",", ":"))
    filas.append(("Métricas + registro JSON (2 000 partículas)", f"{time.perf_counter() - t0:.2f} s", "—",
                  f"{len(texto) / 2**20:.1f} MB en disco"))
    servicio = ServicioDatos(DIR_SEMAR)
    campos_json = json.dumps(servicio.campos(), separators=(",", ":")).encode()
    filas.append(("Campos de oleaje para la interfaz (41 bloques)", "—", "—",
                  f"{len(campos_json) / 2**20:.2f} MB; {len(gzip.compress(campos_json)) / 2**20:.2f} MB con gzip"))

    mascara_bytes = mascara.bits.tobytes()
    filas.append(("Máscara de costa para la interfaz", "—", "—",
                  f"{len(mascara_bytes) / 2**20:.1f} MB; {len(gzip.compress(mascara_bytes, 6)) / 1024:.0f} KB con gzip"))
    filas_nav, navegador = medir_navegador()

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = [
        "# Rendimiento medido",
        "",
        f"Medido con `python scripts/medir_rendimiento.py` el {ahora} en "
        f"{platform.system()} {platform.release()}, Python {platform.python_version()}, NumPy {np.__version__}, "
        f"procesador `{platform.processor() or platform.machine()}`, {memoria_sistema()}. Mediana y máximo de {REPETICIONES} repeticiones; "
        "memoria = pico asignado por Python medido con tracemalloc en una corrida aparte (no incluye el intérprete).",
        "",
        "| Operación | Mediana | Máximo | Memoria / tamaño |",
        "|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} |" for a, b, c, d in filas],
        "",
        "Notas:",
        "",
        f"- Datos: {ARCHIVO_OLEAJE}, {conjunto.resumen()['puntos_malla']} nodos en el dominio "
        f"({conjunto.resumen()['puntos_mar']} con ola), 41 bloques idénticos; modelo {VERSION_MODELO}.",
        f"- Frente a Cancún (21.12° N, 86.66° O) la ola empuja hacia la costa: {varamiento} y las varadas dejan de "
        "calcularse; por eso esa simulación es más barata que la de mar abierto.",
        "- La costa de ~105 m se revisa cada media celda en cada paso (entre 4 y unas decenas de consultas por "
        "partícula y hora): por eso simular cuesta más que en la v0.4.0, que revisaba 4 puntos contra una costa de 440 m.",
        "- La interfaz descarga los campos de oleaje una sola vez al abrir; la API los comprime con gzip (los 41 "
        "bloques idénticos se comprimen casi por completo).",
        "- Los tiempos varían con la carga del equipo: con poca RAM libre todo se vuelve más lento.",
        "",
        "## Interfaz en el navegador",
        "",
        f"Medido en {navegador or 'n/d'} sin interfaz gráfica, ventana de 1366 × 768, con el mapa base «carta» (no usa internet), "
        "oleaje animado, estelas, densidad y localidades encendidos, reproduciendo a 6 h/s durante 6 s. El freno de "
        "procesador es el de las herramientas de desarrollo de Chromium (Emulation.setCPUThrottlingRate): 4× equivale "
        "aproximadamente a un equipo de gama baja y 6× a uno muy modesto.",
        "",
        "| Operación | Resultado | Peor caso | Detalle |",
        "|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} |" for a, b, c, d in filas_nav],
        "",
        "Notas:",
        "",
        "- Las estelas bajan de detalle solas cuando el equipo no alcanza: cada una se parte en 6, 3, 2 o 1 tramos de "
        "opacidad según el tiempo entre cuadros (más de 45 ms baja un nivel; menos de 20 ms sostenidos, sube). En pausa "
        "siempre se dibujan completas. Los anillos de las varadas se estampan desde una imagen ya pintada.",
        "- El costo de JavaScript por cuadro es pequeño (columna de detalle); lo que limita los cuadros por segundo es el "
        "trazado del lienzo, que en este navegador sin interfaz gráfica se hace sin tarjeta de video.",
        "- El oleaje animado se limita a 30 cuadros por segundo y a 900 trazos, y se detiene con la pestaña oculta, con "
        "su interruptor o con la preferencia del sistema de reducir el movimiento.",
        "- La carta propia se pinta por teselas una sola vez por nivel de zoom; la máscara de costa ocupa 6.5 MB en la "
        "memoria del navegador.",
        "- Con poca RAM libre el navegador sin interfaz gráfica entrega menos cuadros que uno normal: estos números son un piso.",
        "",
    ]
    destino = RAIZ / "docs" / "rendimiento.md"
    destino.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
