"""Validador de los datos de SEMAR (salidadatos.txt, dirmarea.txt y corrientes opcionales).

No se detiene en el primer error: cada verificación acumula hallazgos con la causa, el
archivo afectado y la acción sugerida. Si no hay errores, devuelve además el
ConjuntoDatos recortado e interpolado a la malla del modelo.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from src.config import (
    ARCHIVO_OLEAJE, ARCHIVO_VIENTO, CARPETA_CORRIENTES, COLUMNAS_CORRIENTE, COLUMNAS_OLEAJE,
    COLUMNAS_VIENTO, HORIZONTE_H, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, PASO_OLEAJE_H, RESOLUCION_GRADOS,
)
from src.ingestion.lector import (
    ArchivoSemar, ConjuntoDatos, Malla, construir_malla, interpolar_bilineal, interpolar_direccion,
    leer_archivo_semar,
)
from src.model import costa
from src.model.conversiones import diferencia_angular, normalizar_longitud, vector_a_desde

EXTENSIONES_PERMITIDAS = {".txt", ".md"}
VIENTO_MAX_MS = 75.0
ALTURA_MAX_M = 20.0
CORRIENTE_MAX_MS = 3.0
TOLERANCIA_MALLA = 0.002
TOLERANCIA_VELOCIDAD_MS = 0.05     # |WindsfcSp − √(U²+V²)|; en los datos reales el máximo es 0.011
MAX_HALLAZGOS = 25
COLUMNAS_DIRECCION = ("sfcPrimWaDir", "sfcDirWindWa", "WindsfcDir")
COLUMNAS_VIENTO_COMPLETAS = ("U", "V", "WindsfcSp", "WindsfcDir")

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


MESES_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _fmt_fecha(f) -> str:
    return f"{f.day:02d} {MESES_ES[f.month - 1]} {f.year} {f.hour:02d}:00 UTC" if f else "¿?"


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def validar_conjunto(directorio: Path, progreso: Progreso | None = None) -> tuple[ReporteValidacion, ConjuntoDatos | None]:
    t0 = time.perf_counter()
    progreso = progreso or _sin_progreso
    directorio = Path(directorio)
    v_arch = Verificacion("archivos", "Archivos de SEMAR")
    v_fmt = Verificacion("formato", "Encabezado, columnas y filas")
    v_fechas = Verificacion("fechas", "Fechas")
    v_malla = Verificacion("malla", "Malla regular de 0.16° y cobertura del dominio")
    v_rell = Verificacion("relleno", "Valores de relleno (−9.99e+08) y ausentes")
    v_rangos = Verificacion("rangos", "Rangos físicos")
    v_coh = Verificacion("coherencia", "Coherencia del viento y convención «desde»")
    v_ola = Verificacion("oleaje", "Oleaje: horas de pronóstico cada 3 h")
    v_masc = Verificacion("mascara", "Máscara de mar de los datos vs costa del modelo")
    v_corr = Verificacion("corrientes", "Corrientes superficiales")
    verificaciones = [v_arch, v_fmt, v_fechas, v_malla, v_rell, v_rangos, v_coh, v_ola, v_masc, v_corr]
    advertencias_conjunto: list[str] = []

    def terminar(conjunto: ConjuntoDatos | None = None):
        reporte = ReporteValidacion(
            directorio=str(directorio), valido=all(v.estado != "error" for v in verificaciones),
            verificaciones=verificaciones, duracion_s=round(time.perf_counter() - t0, 3),
            resumen_conjunto=conjunto.resumen() if conjunto is not None else None,
        )
        return reporte, (conjunto if reporte.valido else None)

    # 1. Archivos ---------------------------------------------------------------
    ruta_viento, ruta_ola = directorio / ARCHIVO_VIENTO, directorio / ARCHIVO_OLEAJE
    if directorio.is_dir():
        for p in sorted(directorio.iterdir()):
            if p.is_file() and p.suffix.lower() not in EXTENSIONES_PERMITIDAS:
                v_arch.agregar("advertencia", f"Se ignoró un archivo con extensión inesperada ({p.suffix}).", p.name,
                               "Deja en la carpeta solo los .txt de SEMAR.")
    if not ruta_viento.is_file():
        v_arch.agregar("error", f"No se encontró {ARCHIVO_VIENTO} (viento).", ARCHIVO_VIENTO,
                       f"Copia el archivo de SEMAR en {directorio} (ver data/semar/README.md).")
        for v in verificaciones[1:]:
            v.estado, v.resumen = "error", "No evaluado: falta el archivo de viento."
        return terminar()
    tiene_ola = ruta_ola.is_file()
    if not tiene_ola:
        v_arch.agregar("advertencia", f"No se encontró {ARCHIVO_OLEAJE}: no habrá oleaje en el hover.", ARCHIVO_OLEAJE,
                       f"Copia {ARCHIVO_OLEAJE} en {directorio} si se quiere consultar el oleaje.")
    v_arch.resumen = f"{ARCHIVO_VIENTO}" + (f" y {ARCHIVO_OLEAJE}" if tiene_ola else "") + " encontrados."

    # 2. Lectura y formato ----------------------------------------------------
    progreso(1, 4, f"Leyendo {ARCHIVO_VIENTO}")
    viento = leer_archivo_semar(ruta_viento)
    _revisar_formato(v_fmt, viento, COLUMNAS_VIENTO)
    ola = None
    if tiene_ola:
        progreso(2, 4, f"Leyendo {ARCHIVO_OLEAJE}")
        ola = leer_archivo_semar(ruta_ola)
        _revisar_formato(v_fmt, ola, COLUMNAS_OLEAJE)
    if v_fmt.estado == "ok":
        filas = sum(b.datos.shape[0] for b in viento.bloques)
        v_fmt.resumen = f"{ARCHIVO_VIENTO}: {len(viento.columnas)} columnas, {_miles(filas)} filas"
        if ola:
            v_fmt.resumen += f"; {ARCHIVO_OLEAJE}: {len(ola.columnas)} columnas, {len(ola.bloques)} bloques."
    viento_ok = all(c in viento.columnas for c in COLUMNAS_VIENTO) and viento.bloques
    ola_ok = ola is not None and all(c in ola.columnas for c in COLUMNAS_OLEAJE) and ola.bloques

    # 3. Fechas -------------------------------------------------------------------
    tiempos = [b.fecha_valida for b in viento.bloques]
    if any(t is None for t in tiempos) or not tiempos:
        v_fechas.agregar("error", "No se pudo leer la fecha del viento.", ARCHIVO_VIENTO,
                         "La segunda línea debe tener el formato DDMMMAAAA HH (mes en inglés), p. ej. 19AUG2026 00.")
    elif len(set(tiempos)) != len(tiempos) or tiempos != sorted(tiempos):
        v_fechas.agregar("error", "Las fechas de los bloques de viento están repetidas o desordenadas.", ARCHIVO_VIENTO,
                         "Entrega un bloque por hora, en orden cronológico.")
    elif len(tiempos) == 1:
        texto = f"Viento de una sola hora ({_fmt_fecha(tiempos[0])}): se usa fijo durante las {HORIZONTE_H} h."
        v_fechas.agregar("advertencia", texto, ARCHIVO_VIENTO,
                         "Pedir a SEMAR el pronóstico horario completo de 120 h; el lector ya acepta varios bloques.")
        advertencias_conjunto.append(texto)
    ola_base = None
    if ola_ok:
        fechas_ola = [b.fecha_base for b in ola.bloques]
        if any(f is None for f in fechas_ola):
            v_fechas.agregar("error", "Hay bloques de oleaje con fecha ilegible.", ARCHIVO_OLEAJE,
                             "Cada bloque debe empezar con DDMMMAAAA HH h, p. ej. 01OCT2026 00 3.")
        else:
            ola_base = fechas_ola[0]
            if len(set(fechas_ola)) > 1:
                v_fechas.agregar("advertencia", "Los bloques de oleaje no comparten la misma fecha base.", ARCHIVO_OLEAJE)
            if tiempos and tiempos[0] is not None and ola_base != tiempos[0]:
                texto = (f"La fecha del oleaje ({_fmt_fecha(ola_base)}) no coincide con la del viento "
                         f"({_fmt_fecha(tiempos[0])}).")
                v_fechas.agregar("advertencia", texto, ARCHIVO_OLEAJE,
                                 "Son archivos de muestra; pedir a SEMAR viento y oleaje del mismo pronóstico.")
                advertencias_conjunto.append(texto)
    if not v_fechas.resumen and tiempos and tiempos[0] is not None:
        v_fechas.resumen = f"Viento: {_fmt_fecha(tiempos[0])}" + (f" ({len(tiempos)} horas)" if len(tiempos) > 1 else "")
        if ola_base:
            v_fechas.resumen += f"; oleaje: base {_fmt_fecha(ola_base)}."

    if not viento_ok:
        for v in (v_malla, v_rell, v_rangos, v_coh, v_masc):
            v.estado, v.resumen = "error", "No evaluado: el archivo de viento no tiene el formato esperado."
        _revisar_oleaje(v_ola, ola, ola_ok, None)
        _revisar_corrientes(v_corr, directorio, None)
        return terminar()

    # 4. Malla y cobertura --------------------------------------------------------
    progreso(3, 4, "Revisando malla, rangos y coherencia")
    b0 = viento.bloques[0]
    lon = normalizar_longitud(b0.datos[:, viento.indice("LON")])
    lat = b0.datos[:, viento.indice("LAT")]
    malla = construir_malla(lon, lat)
    _revisar_malla(v_malla, malla, ARCHIVO_VIENTO)
    for b in viento.bloques[1:]:
        if b.datos.shape != b0.datos.shape or not np.allclose(b.datos[:, :2], b0.datos[:, :2], equal_nan=True):
            v_malla.agregar("error", f"El bloque «{b.texto_fecha}» tiene otra malla.", ARCHIVO_VIENTO,
                            "Todos los bloques deben compartir los mismos nodos.")
    sel_lon = (malla.lons >= LON_MIN - 1e-6) & (malla.lons <= LON_MAX + 1e-6)
    sel_lat = (malla.lats >= LAT_MIN - 1e-6) & (malla.lats <= LAT_MAX + 1e-6)
    lons_dom, lats_dom = malla.lons[sel_lon], malla.lats[sel_lat]
    esperados_lon = int(round((LON_MAX - LON_MIN) / RESOLUCION_GRADOS)) + 1
    esperados_lat = int(round((LAT_MAX - LAT_MIN) / RESOLUCION_GRADOS)) + 1
    if lons_dom.size < 2 or lats_dom.size < 2:
        v_malla.agregar("error", "La malla no cubre el recuadro de Yucatán.", ARCHIVO_VIENTO,
                        "Verifica que el archivo corresponda a la región (lon −92…−84, lat 16.92…23).")
    elif lons_dom.size < esperados_lon or lats_dom.size < esperados_lat:
        texto = (f"La malla cubre solo {lons_dom.size} × {lats_dom.size} de los {esperados_lon} × {esperados_lat} "
                 "nodos del dominio: se simula en la parte cubierta.")
        v_malla.agregar("advertencia", texto, ARCHIVO_VIENTO)
        advertencias_conjunto.append(texto)
    if malla.rectangular and v_malla.estado != "error":
        v_malla.resumen = (f"{malla.lons.size} × {malla.lats.size} nodos de {RESOLUCION_GRADOS}° "
                           f"(lon {malla.lons[0]:g}…{malla.lons[-1]:g}, lat {malla.lats[0]:g}…{malla.lats[-1]:g}); "
                           f"dominio del modelo: {lons_dom.size} × {lats_dom.size} = {lons_dom.size * lats_dom.size} nodos.")

    # 5–7. Relleno, rangos y coherencia del viento ------------------------------------
    rejillas = {}
    for c in COLUMNAS_VIENTO[2:]:
        rejillas[c] = np.stack([malla.a_rejilla(b.datos[:, viento.indice(c)]) for b in viento.bloques]) if malla.rectangular else None
    if malla.rectangular and lons_dom.size >= 2 and lats_dom.size >= 2:
        recorte = np.ix_(np.flatnonzero(sel_lat), np.flatnonzero(sel_lon))
        dom = {c: r[(slice(None),) + recorte] for c, r in rejillas.items()}
        _revisar_relleno(v_rell, viento, dom)
        _revisar_rangos_viento(v_rangos, dom)
        _revisar_coherencia(v_coh, dom)
    else:
        for v in (v_rell, v_rangos, v_coh, v_masc):
            v.estado, v.resumen = "error", "No evaluado: la malla no es regular."
        dom = None

    # 8. Oleaje ------------------------------------------------------------------
    ola_dom = _revisar_oleaje(v_ola, ola, ola_ok, (lons_dom, lats_dom) if dom else None, advertencias_conjunto)
    if ola_ok and ola_dom is not None and v_ola.estado != "error":
        _revisar_rangos_oleaje(v_rangos, ola_dom)

    # 9. Máscara de mar vs costa del modelo -------------------------------------------
    if dom is not None:
        mar_datos = np.isfinite(dom["WindsfcSp"][0])
        X, Y = np.meshgrid(lons_dom, lats_dom)
        mar_costa = ~costa.en_tierra(X.ravel(), Y.ravel()).reshape(X.shape)
        solo_datos = int((mar_datos & ~mar_costa).sum())
        solo_costa = int((~mar_datos & mar_costa).sum())
        v_masc.resumen = (f"{int(mar_datos.sum())} nodos de mar en los datos y {int(mar_costa.sum())} según la costa del modelo; "
                          f"no coinciden {solo_datos + solo_costa} ({solo_datos} con viento sobre «tierra» del modelo, "
                          f"{solo_costa} sin viento sobre «mar» del modelo).")
        if solo_datos + solo_costa:
            v_masc.agregar("advertencia", f"{solo_datos + solo_costa} nodos de la malla no coinciden con la costa poligonal.", None,
                           "Esperable con una costa aproximada; las partículas en esos nodos usan los vecinos con dato.")

    # 10. Corrientes ---------------------------------------------------------------
    corriente = _revisar_corrientes(v_corr, directorio, (lons_dom, lats_dom) if dom else None)
    if corriente is None and v_corr.estado != "error":
        advertencias_conjunto.append("Sin corrientes: u_c = 0 (solo viento y difusión).")

    if any(v.estado == "error" for v in verificaciones) or dom is None:
        return terminar()

    progreso(4, 4, "Preparando la malla del modelo")
    archivos = {ARCHIVO_VIENTO: viento.huella_sha256}
    if ola is not None:
        archivos[ARCHIVO_OLEAJE] = ola.huella_sha256
    if corriente is not None:
        archivos.update(corriente["huellas"])
    conjunto = ConjuntoDatos(
        lons=lons_dom, lats=lats_dom, tiempos_viento=tiempos,
        viento_u=dom["U"].astype(np.float32), viento_v=dom["V"].astype(np.float32),
        viento_vel=dom["WindsfcSp"].astype(np.float32), viento_dir=dom["WindsfcDir"].astype(np.float32),
        mar=np.isfinite(dom["WindsfcSp"][0]),
        ola_horas=np.array(ola_dom["horas"]) if ola_dom else np.array([]),
        ola_dir=ola_dom["dir"].astype(np.float32) if ola_dom else None,
        ola_altura=ola_dom["altura"].astype(np.float32) if ola_dom else None,
        ola_fecha_base=ola_base,
        corriente_u=corriente["u"] if corriente else None, corriente_v=corriente["v"] if corriente else None,
        archivos=archivos, advertencias=advertencias_conjunto,
    )
    return terminar(conjunto)


# ---------------------------------------------------------------------------
def _revisar_formato(v: Verificacion, a: ArchivoSemar, requeridas):
    nombre = a.ruta.name
    for linea, problema in a.problemas[:5]:
        v.agregar("error", f"Línea {linea}: {problema}.", nombre, "Corrige el archivo o pide a SEMAR una copia íntegra.")
    if a.columnas:
        faltan = [c for c in requeridas if c not in a.columnas]
        if faltan:
            v.agregar("error", f"Faltan columnas: {', '.join(faltan)}.", nombre,
                      f"El encabezado debe ser {';'.join(requeridas)}.")
        extra = [c for c in a.columnas if c not in requeridas]
        if extra:
            v.agregar("advertencia", f"Columnas adicionales ignoradas: {', '.join(extra)}.", nombre)
    for linea, motivo in a.filas_invalidas[:3]:
        v.agregar("error", f"Fila defectuosa en la línea {linea}: {motivo}.", nombre,
                  "Corrige o elimina la fila; todas deben tener el mismo número de columnas.")
    if len(a.filas_invalidas) > 3:
        v.agregar("error", f"… y {len(a.filas_invalidas) - 3} filas defectuosas más.", nombre)
    if a.columnas and not a.bloques:
        v.agregar("error", "El archivo no tiene datos.", nombre, "Verifica que la copia esté completa.")


def _revisar_malla(v: Verificacion, malla: Malla, nombre: str):
    dmin_lon, dmax_lon, dmin_lat, dmax_lat = malla.pasos
    pasos = np.array([dmin_lon, dmax_lon, dmin_lat, dmax_lat])
    if not np.all(np.abs(pasos - RESOLUCION_GRADOS) <= TOLERANCIA_MALLA):
        v.agregar("error", f"El espaciamiento no es de {RESOLUCION_GRADOS}° (observado lon {dmin_lon:.3f}–{dmax_lon:.3f}°, "
                  f"lat {dmin_lat:.3f}–{dmax_lat:.3f}°).", nombre, "Confirma la resolución con SEMAR.")
    if not malla.rectangular:
        v.agregar("error", "La malla no es rectangular (faltan, sobran o se repiten nodos).", nombre,
                  "El archivo debe traer todos los nodos, también los de tierra (con −9.99e+08).")


def _revisar_relleno(v: Verificacion, a: ArchivoSemar, dom: dict):
    rellenos = sum(b.rellenos for b in a.bloques)
    completas = np.stack([np.isfinite(dom[c]) for c in COLUMNAS_VIENTO_COMPLETAS])
    inconsistentes = int((completas.any(axis=0) & ~completas.all(axis=0)).sum())
    if inconsistentes:
        v.agregar("error", f"{inconsistentes} nodos tienen U, V, WindsfcSp o WindsfcDir incompletos.", a.ruta.name,
                  "Las cuatro columnas de viento deben tener dato o relleno a la vez.")
    mar = np.isfinite(dom["WindsfcSp"][0])
    con_ola_viento = int((mar & np.isfinite(dom["sfcDirWindWa"][0])).sum())
    con_ola_prim = int((mar & np.isfinite(dom["sfcPrimWaDir"][0])).sum())
    v.resumen = (f"{_miles(rellenos)} valores de relleno convertidos a NaN. En el dominio: {int(mar.sum())} nodos de mar "
                 f"con viento, {con_ola_prim} con sfcPrimWaDir y {con_ola_viento} con sfcDirWindWa "
                 "(no hay mar de viento en todos los nodos: es normal).")


def _revisar_rangos_viento(v: Verificacion, dom: dict):
    vel = dom["WindsfcSp"]
    malos = int(np.nansum((vel < 0) | (vel > VIENTO_MAX_MS)))
    if malos:
        v.agregar("error", f"{malos} velocidades de viento fuera de 0–{VIENTO_MAX_MS:.0f} m/s.", ARCHIVO_VIENTO,
                  "Revisa unidades y valores de relleno.")
    for c in ("U", "V"):
        malos = int(np.nansum(np.abs(dom[c]) > VIENTO_MAX_MS))
        if malos:
            v.agregar("error", f"{malos} valores de {c} fuera de ±{VIENTO_MAX_MS:.0f} m/s.", ARCHIVO_VIENTO, "Revisa la columna.")
    for c in COLUMNAS_DIRECCION:
        malos = int(np.nansum((dom[c] < 0) | (dom[c] > 360)))
        if malos:
            v.agregar("error", f"{malos} direcciones de {c} fuera de 0–360°.", ARCHIVO_VIENTO, "Revisa la columna.")
    if v.estado != "error":
        v.resumen = (f"Viento {np.nanmin(vel):.2f}–{np.nanmax(vel):.2f} m/s (media {np.nanmean(vel):.1f}); "
                     "direcciones en 0–360°.")


def _revisar_rangos_oleaje(v: Verificacion, ola: dict):
    altura, direccion = ola["altura_cruda"], ola["dir_cruda"]
    malos = int(np.nansum((altura < 0) | (altura > ALTURA_MAX_M)))
    if malos:
        v.agregar("error", f"{malos} alturas de ola fuera de 0–{ALTURA_MAX_M:.0f} m.", ARCHIVO_OLEAJE, "Revisa unidades (¿cm?).")
    malos = int(np.nansum((direccion < 0) | (direccion > 360)))
    if malos:
        v.agregar("error", f"{malos} direcciones de ola fuera de 0–360°.", ARCHIVO_OLEAJE, "Revisa la columna dirolavto.")
    if v.estado != "error":
        v.resumen += f" Ola {np.nanmin(altura):.2f}–{np.nanmax(altura):.2f} m."


def _revisar_coherencia(v: Verificacion, dom: dict):
    u, w, vel, direccion = dom["U"], dom["V"], dom["WindsfcSp"], dom["WindsfcDir"]
    vel_uv, dir_uv = vector_a_desde(u, w)
    dif = np.abs(vel_uv - vel)
    malos = int(np.nansum(dif > TOLERANCIA_VELOCIDAD_MS))
    if malos:
        v.agregar("error", f"WindsfcSp difiere de √(U²+V²) en {malos} nodos (máx. {np.nanmax(dif):.3f} m/s).",
                  ARCHIVO_VIENTO, "Confirma con SEMAR que U, V y WindsfcSp estén en m/s.")
    fuerte = np.isfinite(vel) & (vel_uv > 0.5)
    if not fuerte.any():
        v.agregar("error", "No hay viento suficiente para verificar la convención.", ARCHIVO_VIENTO)
        return
    mediana = float(np.median(diferencia_angular(dir_uv[fuerte], direccion[fuerte])))
    if mediana > 170:
        v.agregar("error", f"WindsfcDir difiere ~180° de atan2(−U, −V) (mediana {mediana:.1f}°): parece convención «hacia».",
                  ARCHIVO_VIENTO, "Confirma con SEMAR; PMS asume dirección DESDE la que sopla.")
    elif mediana > 2:
        v.agregar("error", f"WindsfcDir no es consistente con U, V (error mediano {mediana:.1f}°).", ARCHIVO_VIENTO,
                  "Revisa el signo de U y V y la convención de WindsfcDir.")
    ola_v = np.isfinite(dom["sfcDirWindWa"]) & fuerte
    texto_ola = ""
    if ola_v.any():
        dif_ola = float(np.median(diferencia_angular(dom["sfcDirWindWa"][ola_v], direccion[ola_v])))
        texto_ola = f" sfcDirWindWa difiere {dif_ola:.0f}° (mediana) de WindsfcDir: misma convención «desde»."
        if dif_ola > 90:
            v.agregar("advertencia", f"sfcDirWindWa difiere {dif_ola:.0f}° de WindsfcDir: ¿convención opuesta?", ARCHIVO_VIENTO)
    if v.estado != "error":
        v.resumen = (f"|WindsfcSp − √(U²+V²)| ≤ {np.nanmax(dif):.3f} m/s; WindsfcDir vs atan2(−U, −V): "
                     f"mediana {mediana:.2f}° → convención «desde».{texto_ola}")


def _revisar_oleaje(v: Verificacion, ola: ArchivoSemar | None, ola_ok, destino, advertencias=None):
    """Valida dirmarea.txt y lo interpola (bilineal, ignorando NaN) a la malla del modelo."""
    if ola is None:
        v.estado, v.resumen = "advertencia", "Sin archivo de oleaje."
        return None
    if not ola_ok:
        v.estado, v.resumen = "error", "No evaluado: el archivo de oleaje no tiene el formato esperado."
        return None
    nombre = ola.ruta.name
    horas = [b.hora_pronostico for b in ola.bloques]
    esperadas = list(range(0, HORIZONTE_H + 1, PASO_OLEAJE_H))
    faltan = sorted(set(esperadas) - set(horas))
    if faltan:
        v.agregar("error", f"Faltan horas de oleaje: {', '.join(f'+{h}' for h in faltan[:8])}"
                  + ("…" if len(faltan) > 8 else "") + ".", nombre,
                  f"Se esperan {len(esperadas)} bloques: +0, +3, …, +{HORIZONTE_H} h.")
    if horas != sorted(set(horas)):
        v.agregar("error", "Horas de oleaje repetidas o desordenadas.", nombre, "Un bloque por hora, en orden.")
    b0 = ola.bloques[0]
    lon = normalizar_longitud(b0.datos[:, ola.indice("LON")])
    lat = b0.datos[:, ola.indice("LAT")]
    malla = construir_malla(lon, lat)
    _revisar_malla(v, malla, nombre)
    for b in ola.bloques[1:]:
        if b.datos.shape != b0.datos.shape or not np.array_equal(b.datos[:, :2], b0.datos[:, :2], equal_nan=True):
            v.agregar("error", f"El bloque «{b.texto_fecha}» tiene otra malla.", nombre,
                      "Todos los bloques deben compartir los mismos nodos.")
            break
    if len(ola.bloques) > 1 and len({b.huella for b in ola.bloques}) == 1:
        texto = f"Los {len(ola.bloques)} bloques de oleaje son idénticos: el oleaje no varía en el tiempo."
        v.agregar("advertencia", texto, nombre, "Confirmar con SEMAR si es un archivo de muestra.")
        if advertencias is not None:
            advertencias.append(texto)
    if v.estado == "error" or destino is None:
        return None
    lons_d, lats_d = destino
    desfase = float(np.min(np.abs(((lons_d[0] - malla.lons) + 0.08) % RESOLUCION_GRADOS - 0.08)))
    dirs, alturas = [], []
    idir, ialt = ola.indice("dirolavto"), ola.indice("alturaolavto")
    cache = {}
    for b in ola.bloques:
        if b.huella not in cache:
            d = malla.a_rejilla(b.datos[:, idir])
            a = malla.a_rejilla(b.datos[:, ialt])
            cache[b.huella] = (d, a, interpolar_direccion(malla.lons, malla.lats, d, lons_d, lats_d),
                               interpolar_bilineal(malla.lons, malla.lats, [a], lons_d, lats_d)[0])
        dirs.append(cache[b.huella][2])
        alturas.append(cache[b.huella][3])
    crudas = list(cache.values())
    cubiertos = int(np.isfinite(alturas[0]).sum())
    v.resumen = (f"{len(ola.bloques)} bloques (+{horas[0]} … +{horas[-1]} h), malla {malla.lons.size} × {malla.lats.size} "
                 f"de {RESOLUCION_GRADOS}°"
                 + (f" desplazada {desfase:.2f}° en longitud: se interpola bilinealmente (dirección por seno y coseno)"
                    if desfase > 1e-6 else "")
                 + f"; {cubiertos} nodos del dominio con ola.")
    return {
        "horas": horas, "dir": np.stack(dirs), "altura": np.stack(alturas),
        "dir_cruda": np.stack([c[0] for c in crudas]), "altura_cruda": np.stack([c[1] for c in crudas]),
    }


def _revisar_corrientes(v: Verificacion, directorio: Path, destino):
    carpeta = directorio / CARPETA_CORRIENTES
    archivos = sorted(carpeta.glob("*.txt")) if carpeta.is_dir() else []
    if not archivos:
        v.agregar("advertencia", "No hay corrientes: el modelo usa u_c = 0 (solo viento y difusión).", None,
                  f"Agregar corrientes CMEMS/HYCOM en {CARPETA_CORRIENTES}/ (LON;LAT;UO;VO) cuando se confirme la fuente.")
        v.resumen = "Sin corrientes (u_c = 0)."
        return None
    a = leer_archivo_semar(archivos[0])
    _revisar_formato(v, a, COLUMNAS_CORRIENTE)
    if v.estado == "error" or destino is None:
        return None
    b = a.bloques[0]
    malla = construir_malla(normalizar_longitud(b.datos[:, a.indice("LON")]), b.datos[:, a.indice("LAT")])
    _revisar_malla(v, malla, a.ruta.name)
    if v.estado == "error":
        return None
    uo = malla.a_rejilla(b.datos[:, a.indice("UO")])
    vo = malla.a_rejilla(b.datos[:, a.indice("VO")])
    vel = np.hypot(uo, vo)
    if np.nanmax(vel) > CORRIENTE_MAX_MS:
        v.agregar("error", f"Corriente máxima de {np.nanmax(vel):.2f} m/s (> {CORRIENTE_MAX_MS} m/s).", a.ruta.name,
                  "Revisa unidades (¿cm/s?).")
        return None
    u, w = interpolar_bilineal(malla.lons, malla.lats, [uo, vo], *destino)
    v.resumen = f"{a.ruta.name}: estacionaria, máx. {np.nanmax(vel):.2f} m/s, interpolada a la malla del modelo."
    return {"u": np.nan_to_num(u).astype(np.float32), "v": np.nan_to_num(w).astype(np.float32),
            "huellas": {f"{CARPETA_CORRIENTES}/{a.ruta.name}": a.huella_sha256}}
