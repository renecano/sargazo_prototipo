"""Validador del archivo de oleaje de SEMAR (dirmarea.txt), el único archivo de entrada.

No se detiene en el primer error: cada verificación acumula hallazgos con la causa, el
archivo afectado y la acción sugerida. Si no hay errores, devuelve además el
ConjuntoDatos recortado al dominio del modelo en la malla nativa del archivo.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from src.config import (
    ARCHIVO_OLEAJE, COLUMNAS_OLEAJE, HORIZONTE_H, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, PASO_OLEAJE_H,
    RESOLUCION_GRADOS,
)
from src.ingestion.lector import ArchivoSemar, ConjuntoDatos, Malla, construir_malla, leer_archivo_semar
from src.model import costa
from src.model.conversiones import normalizar_longitud

EXTENSIONES_PERMITIDAS = {".txt", ".md"}
ALTURA_MAX_M = 20.0
TOLERANCIA_MALLA = 0.002
MAX_HALLAZGOS = 25
MESES_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

Progreso = Callable[[int, int, str], None]


@dataclass
class Hallazgo:
    nivel: str          # "error" | "advertencia"
    detalle: str
    archivo: str | None = None
    accion: str | None = None


@dataclass
class Verificacion:
    id: str
    nombre: str
    estado: str = "ok"  # "ok" | "advertencia" | "error"
    resumen: str = ""
    hallazgos: list[Hallazgo] = field(default_factory=list)
    omitidos: int = 0

    def agregar(self, nivel: str, detalle: str, archivo: str | None = None, accion: str | None = None):
        if nivel == "error":
            self.estado = "error"
        elif self.estado == "ok":
            self.estado = "advertencia"
        if len(self.hallazgos) < MAX_HALLAZGOS:
            self.hallazgos.append(Hallazgo(nivel, detalle, archivo, accion))
        else:
            self.omitidos += 1


@dataclass
class ReporteValidacion:
    directorio: str
    valido: bool
    verificaciones: list[Verificacion]
    duracion_s: float
    resumen_conjunto: dict | None = None

    def a_dict(self) -> dict:
        return asdict(self)

    @property
    def errores(self) -> list[Hallazgo]:
        return [h for v in self.verificaciones for h in v.hallazgos if h.nivel == "error"]

    @property
    def advertencias(self) -> list[Hallazgo]:
        return [h for v in self.verificaciones for h in v.hallazgos if h.nivel == "advertencia"]


def _sin_progreso(_k, _n, _m):
    return None


def _fmt_fecha(f) -> str:
    return f"{f.day:02d} {MESES_ES[f.month - 1]} {f.year} {f.hour:02d}:00 UTC" if f else "¿?"


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def validar_conjunto(directorio: Path, progreso: Progreso | None = None) -> tuple[ReporteValidacion, ConjuntoDatos | None]:
    t0 = time.perf_counter()
    progreso = progreso or _sin_progreso
    directorio = Path(directorio)
    v_arch = Verificacion("archivos", "Archivo de SEMAR")
    v_fmt = Verificacion("formato", "Encabezado, columnas y filas")
    v_fechas = Verificacion("fechas", "Fecha y horas de pronóstico (cada 3 h)")
    v_malla = Verificacion("malla", "Malla regular de 0.16° y cobertura del dominio")
    v_rell = Verificacion("relleno", "Valores de relleno (−9.99e+08)")
    v_rangos = Verificacion("rangos", "Rangos físicos")
    v_var = Verificacion("variacion", "Variación en el tiempo")
    v_masc = Verificacion("mascara", "Máscara de mar de los datos vs costa del modelo")
    verificaciones = [v_arch, v_fmt, v_fechas, v_malla, v_rell, v_rangos, v_var, v_masc]
    advertencias: list[str] = []

    def terminar(conjunto: ConjuntoDatos | None = None):
        reporte = ReporteValidacion(
            directorio=str(directorio), valido=all(v.estado != "error" for v in verificaciones),
            verificaciones=verificaciones, duracion_s=round(time.perf_counter() - t0, 3),
            resumen_conjunto=conjunto.resumen() if conjunto is not None else None,
        )
        return reporte, (conjunto if reporte.valido else None)

    def no_evaluadas(motivo: str, desde: int):
        for v in verificaciones[desde:]:
            if v.estado == "ok" and not v.resumen:
                v.estado, v.resumen = "error", f"No evaluado: {motivo}."

    # 1. Archivo -----------------------------------------------------------------
    ruta = directorio / ARCHIVO_OLEAJE
    if directorio.is_dir():
        for p in sorted(directorio.iterdir()):
            if not p.is_file() or p.name in (ARCHIVO_OLEAJE, "README.md"):
                continue
            if p.suffix.lower() not in EXTENSIONES_PERMITIDAS:
                v_arch.agregar("advertencia", f"Se ignoró un archivo con extensión inesperada ({p.suffix}).", p.name,
                               "Deja en la carpeta solo dirmarea.txt.")
            elif p.suffix.lower() == ".txt":
                v_arch.agregar("advertencia", "Archivo no usado por el modelo: se ignora.", p.name,
                               f"PMS solo lee {ARCHIVO_OLEAJE}; puedes retirar este archivo.")
    if not ruta.is_file():
        v_arch.agregar("error", f"No se encontró {ARCHIVO_OLEAJE} (oleaje de viento).", ARCHIVO_OLEAJE,
                       f"Copia el archivo de SEMAR en {directorio} (ver data/semar/README.md).")
        no_evaluadas("falta el archivo de oleaje", 1)
        return terminar()
    v_arch.resumen = f"{ARCHIVO_OLEAJE} encontrado ({ruta.stat().st_size / 2**20:.1f} MB)."

    # 2. Lectura y formato ------------------------------------------------------
    progreso(1, 3, f"Leyendo {ARCHIVO_OLEAJE}")
    a = leer_archivo_semar(ruta)
    _revisar_formato(v_fmt, a)
    if v_fmt.estado == "error" or not all(c in a.columnas for c in COLUMNAS_OLEAJE) or not a.bloques:
        no_evaluadas("el archivo no tiene el formato esperado", 2)
        return terminar()
    filas = sum(b.datos.shape[0] for b in a.bloques)
    v_fmt.resumen = (f"Columnas {';'.join(a.columnas)}; {len(a.bloques)} bloques, {_miles(filas)} filas "
                     f"({_miles(a.bloques[0].datos.shape[0])} por bloque).")

    # 3. Fechas y horas -----------------------------------------------------------
    progreso(2, 3, "Revisando fechas, malla y rangos")
    fechas = [b.fecha_base for b in a.bloques]
    horas = [b.hora_pronostico for b in a.bloques]
    if any(f is None for f in fechas):
        v_fechas.agregar("error", "Hay bloques con fecha ilegible.", ARCHIVO_OLEAJE,
                         "Cada bloque debe empezar con DDMMMAAAA HH h (mes en inglés), p. ej. 01OCT2026 00 3.")
    elif len(set(fechas)) > 1:
        v_fechas.agregar("advertencia", "Los bloques no comparten la misma fecha base; se usa la del primero.", ARCHIVO_OLEAJE)
    esperadas = list(range(0, HORIZONTE_H + 1, PASO_OLEAJE_H))
    faltan = sorted(set(esperadas) - set(horas))
    if faltan:
        v_fechas.agregar("error", f"Faltan horas de oleaje: {', '.join(f'+{h}' for h in faltan[:8])}"
                         + ("…" if len(faltan) > 8 else "") + ".", ARCHIVO_OLEAJE,
                         f"Se esperan {len(esperadas)} bloques: +0, +3, …, +{HORIZONTE_H} h.")
    if horas != sorted(set(horas)):
        v_fechas.agregar("error", "Horas de pronóstico repetidas o desordenadas.", ARCHIVO_OLEAJE,
                         "Entrega un bloque por hora, en orden.")
    extra = sorted(set(horas) - set(esperadas))
    if extra:
        v_fechas.agregar("advertencia", f"Horas fuera de la serie +0…+{HORIZONTE_H} cada {PASO_OLEAJE_H} h: "
                         f"{', '.join(f'+{h}' for h in extra[:5])}; se interpolan igual.", ARCHIVO_OLEAJE)
    if fechas[0] is not None:
        v_fechas.resumen = (f"Fecha base {_fmt_fecha(fechas[0])}; {len(horas)} bloques "
                            f"(+{min(horas)} … +{max(horas)} h).")

    # 4. Malla y cobertura --------------------------------------------------------
    b0 = a.bloques[0]
    lon = normalizar_longitud(b0.datos[:, a.indice("LON")])
    lat = b0.datos[:, a.indice("LAT")]
    malla = construir_malla(lon, lat)
    _revisar_malla(v_malla, malla)
    for b in a.bloques[1:]:
        if b.datos.shape != b0.datos.shape or not np.array_equal(b.datos[:, :2], b0.datos[:, :2], equal_nan=True):
            v_malla.agregar("error", f"El bloque «{b.texto_fecha}» tiene otra malla.", ARCHIVO_OLEAJE,
                            "Todos los bloques deben traer los mismos nodos en el mismo orden.")
            break
    sel_lon = (malla.lons >= LON_MIN - 1e-6) & (malla.lons <= LON_MAX + 1e-6)
    sel_lat = (malla.lats >= LAT_MIN - 1e-6) & (malla.lats <= LAT_MAX + 1e-6)
    esperados_lon = int(round((LON_MAX - LON_MIN) / RESOLUCION_GRADOS)) + 1
    esperados_lat = int(round((LAT_MAX - LAT_MIN) / RESOLUCION_GRADOS)) + 1
    n_lon, n_lat = int(sel_lon.sum()), int(sel_lat.sum())
    if n_lon < 2 or n_lat < 2:
        v_malla.agregar("error", "La malla no cubre el recuadro de Yucatán.", ARCHIVO_OLEAJE,
                        f"El archivo debe incluir lon {LON_MIN}…{LON_MAX} y lat {LAT_MIN}…{LAT_MAX}.")
    elif n_lon < esperados_lon or n_lat < esperados_lat:
        texto = (f"La malla cubre {n_lon} × {n_lat} de los {esperados_lon} × {esperados_lat} nodos del dominio: "
                 "se simula solo en la parte cubierta.")
        v_malla.agregar("advertencia", texto, ARCHIVO_OLEAJE)
        advertencias.append(texto)
    elif not _alineada(malla.lons[sel_lon], LON_MIN) or not _alineada(malla.lats[sel_lat], LAT_MIN):
        v_malla.agregar("advertencia", "La malla no está alineada con el dominio del modelo "
                        f"(se esperaba un nodo en lon {LON_MIN}, lat {LAT_MIN}).", ARCHIVO_OLEAJE)
    if malla.rectangular and v_malla.estado != "error":
        v_malla.resumen = (f"{malla.lons.size} × {malla.lats.size} nodos de {RESOLUCION_GRADOS}° "
                           f"(lon {malla.lons[0]:g}…{malla.lons[-1]:g}, lat {malla.lats[0]:g}…{malla.lats[-1]:g}); "
                           f"dominio del modelo: {n_lon} × {n_lat} = {n_lon * n_lat} nodos, sin interpolar.")
    if v_malla.estado == "error" or v_fechas.estado == "error":
        no_evaluadas("la malla o las horas no son válidas", 4)
        return terminar()

    # 5–6. Relleno y rangos ----------------------------------------------------------
    recorte = np.ix_(np.flatnonzero(sel_lat), np.flatnonzero(sel_lon))
    idir, ialt = a.indice("dirolavto"), a.indice("alturaolavto")
    direccion = np.stack([malla.a_rejilla(b.datos[:, idir])[recorte] for b in a.bloques])
    altura = np.stack([malla.a_rejilla(b.datos[:, ialt])[recorte] for b in a.bloques])
    rellenos = sum(b.rellenos for b in a.bloques)
    inconsistentes = int((np.isfinite(direccion) != np.isfinite(altura)).sum())
    if inconsistentes:
        v_rell.agregar("error", f"{inconsistentes} valores con dirección sin altura o altura sin dirección.",
                       ARCHIVO_OLEAJE, "dirolavto y alturaolavto deben tener dato o relleno a la vez.")
    mar = np.isfinite(altura[0])
    v_rell.resumen = (f"{_miles(rellenos)} valores de relleno convertidos a NaN; en el dominio hay "
                      f"{int(mar.sum())} nodos de mar con ola de {mar.size}.")
    malos = int(np.nansum((altura < 0) | (altura > ALTURA_MAX_M)))
    if malos:
        v_rangos.agregar("error", f"{malos} alturas de ola fuera de 0–{ALTURA_MAX_M:.0f} m.", ARCHIVO_OLEAJE,
                         "Revisa unidades (¿cm?) y valores de relleno.")
    malos = int(np.nansum((direccion < 0) | (direccion > 360)))
    if malos:
        v_rangos.agregar("error", f"{malos} direcciones fuera de 0–360°.", ARCHIVO_OLEAJE, "Revisa la columna dirolavto.")
    if v_rangos.estado == "ok":
        v_rangos.resumen = (f"Altura {np.nanmin(altura):.2f}–{np.nanmax(altura):.2f} m (media {np.nanmean(altura):.2f} m); "
                            "direcciones en 0–360° (desde donde viene la ola).")

    # 7. Variación temporal ---------------------------------------------------------
    identicos = len(a.bloques) > 1 and len({b.huella for b in a.bloques}) == 1
    if identicos:
        texto = (f"Los {len(a.bloques)} bloques son idénticos: el oleaje no varía en el tiempo "
                 f"(archivo de muestra, fecha {_fmt_fecha(fechas[0])}).")
        v_var.agregar("advertencia", texto, ARCHIVO_OLEAJE,
                      "Pedir a SEMAR el pronóstico real de 120 h; el modelo ya interpola entre bloques cada 3 h.")
        advertencias.append(texto)
        v_var.resumen = "Bloques idénticos; el modelo interpola linealmente cada 3 h (hoy sin efecto)."
    else:
        v_var.resumen = f"{len({b.huella for b in a.bloques})} bloques distintos; se interpola linealmente cada 3 h."

    # 8. Máscara de mar vs costa del modelo ----------------------------------------------
    lons_dom, lats_dom = malla.lons[sel_lon], malla.lats[sel_lat]
    X, Y = np.meshgrid(lons_dom, lats_dom)
    mar_costa = ~costa.en_tierra(X.ravel(), Y.ravel()).reshape(X.shape)
    solo_datos = int((mar & ~mar_costa).sum())
    solo_costa = int((~mar & mar_costa).sum())
    v_masc.resumen = (f"{int(mar.sum())} nodos de mar en los datos y {int(mar_costa.sum())} según la costa del modelo; "
                      f"no coinciden {solo_datos + solo_costa} ({solo_datos} con ola sobre «tierra» del modelo, "
                      f"{solo_costa} sin ola sobre «mar» del modelo).")
    if solo_datos + solo_costa:
        v_masc.agregar("advertencia", f"{solo_datos + solo_costa} nodos de la malla no coinciden con la costa del modelo.",
                       ARCHIVO_OLEAJE, "Esperable: la malla de oleaje es de 0.16° (~17 km) y la costa, de ~100 m. "
                       "Cerca de la costa el modelo usa los nodos vecinos con dato.")

    if any(v.estado == "error" for v in verificaciones):
        return terminar()
    progreso(3, 3, "Preparando la malla del modelo")
    conjunto = ConjuntoDatos(
        lons=lons_dom, lats=lats_dom, fecha_base=fechas[0], horas=np.array(horas, dtype=float),
        altura=altura.astype(np.float32), direccion=direccion.astype(np.float32), mar=mar,
        archivo=ARCHIVO_OLEAJE, huella_sha256=a.huella_sha256, bloques_identicos=identicos,
        advertencias=advertencias,
    )
    return terminar(conjunto)


def _alineada(valores: np.ndarray, origen: float) -> bool:
    return abs(float(valores[0]) - origen) <= TOLERANCIA_MALLA


def _revisar_formato(v: Verificacion, a: ArchivoSemar):
    nombre = a.ruta.name
    for linea, problema in a.problemas[:5]:
        v.agregar("error", f"Línea {linea}: {problema}.", nombre, "Corrige el archivo o pide a SEMAR una copia íntegra.")
    if a.columnas:
        faltan = [c for c in COLUMNAS_OLEAJE if c not in a.columnas]
        if faltan:
            v.agregar("error", f"Faltan columnas: {', '.join(faltan)}.", nombre,
                      f"El encabezado debe ser {';'.join(COLUMNAS_OLEAJE)}.")
        extra = [c for c in a.columnas if c not in COLUMNAS_OLEAJE]
        if extra:
            v.agregar("advertencia", f"Columnas adicionales ignoradas: {', '.join(extra)}.", nombre)
    for linea, motivo in a.filas_invalidas[:3]:
        v.agregar("error", f"Fila defectuosa en la línea {linea}: {motivo}.", nombre,
                  "Corrige o elimina la fila; todas deben tener el mismo número de columnas.")
    if len(a.filas_invalidas) > 3:
        v.agregar("error", f"… y {len(a.filas_invalidas) - 3} filas defectuosas más.", nombre)
    if a.columnas and not a.bloques:
        v.agregar("error", "El archivo no tiene datos.", nombre, "Verifica que la copia esté completa.")


def _revisar_malla(v: Verificacion, malla: Malla):
    dmin_lon, dmax_lon, dmin_lat, dmax_lat = malla.pasos
    pasos = np.array([dmin_lon, dmax_lon, dmin_lat, dmax_lat])
    if not np.all(np.abs(pasos - RESOLUCION_GRADOS) <= TOLERANCIA_MALLA):
        v.agregar("error", f"El espaciamiento no es de {RESOLUCION_GRADOS}° (observado lon {dmin_lon:.3f}–{dmax_lon:.3f}°, "
                  f"lat {dmin_lat:.3f}–{dmax_lat:.3f}°).", ARCHIVO_OLEAJE, "Confirma la resolución con SEMAR.")
    if not malla.rectangular:
        v.agregar("error", "La malla no es rectangular (faltan, sobran o se repiten nodos).", ARCHIVO_OLEAJE,
                  "El archivo debe traer todos los nodos, también los de tierra (con −9.99e+08).")
