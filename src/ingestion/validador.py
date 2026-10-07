"""Validador de un conjunto de 120 archivos horarios + campo de corrientes.

Revisa, en este orden: archivos y extensiones, continuidad temporal, columnas,
coordenadas y malla, valores ausentes, rangos físicos, unidades, convención de
dirección del viento y campo de corrientes. No se detiene en el primer error: el
reporte lista todos los hallazgos con el archivo afectado y la acción sugerida.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable

import numpy as np

from src.config import (
    COLUMNAS_CORRIENTE, COLUMNAS_SEMAR, HORAS_ESPERADAS, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN,
    RESOLUCION_GRADOS,
)
from src.ingestion.lector import (
    PATRON_HORARIO, ArchivoTabla, ConjuntoDatos, fecha_de_nombre, huella_archivos, leer_tabla,
)
from src.model.conversiones import diferencia_angular, normalizar_longitud, vector_a_desde

EXTENSIONES_PERMITIDAS = {".txt", ".md"}
VIENTO_MAX_MS = 75.0           # por encima es físicamente implausible a 10 m
VIENTO_ADVERTENCIA_MS = 40.0
CORRIENTE_MAX_MS = 3.0
TOLERANCIA_MALLA = 0.002
COLUMNAS_SIN_AUSENTES = ("LON", "LAT", "U", "V", "WindsfcSp", "WindsfcDir")
COLUMNAS_OLEAJE = ("sfcPrimWaDir", "sfcDirWindWa")
MAX_HALLAZGOS_POR_VERIFICACION = 25

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
        if len(self.hallazgos) < MAX_HALLAZGOS_POR_VERIFICACION:
            self.hallazgos.append(Hallazgo(nivel, detalle, archivo, accion))
        else:
            self.omitidos += 1


@dataclass
class ReporteValidacion:
    conjunto: str
    valido: bool
    verificaciones: list[Verificacion]
    archivos_encontrados: int
    archivos_esperados: int
    duracion_s: float
    resumen_conjunto: dict | None = None

    def a_dict(self) -> dict:
        return asdict(self)

    @property
    def errores(self) -> list[Hallazgo]:
        return [h for v in self.verificaciones for h in v.hallazgos if h.nivel == "error"]


def _sin_progreso(_k, _n, _m):
    return None


def validar_conjunto(directorio: Path, progreso: Progreso | None = None,
                     horas_esperadas: int = HORAS_ESPERADAS) -> tuple[ReporteValidacion, ConjuntoDatos | None]:
    """Valida el conjunto en `directorio`. Devuelve el reporte y, si es válido, los campos cargados."""
    t0 = time.perf_counter()
    progreso = progreso or _sin_progreso
    directorio = Path(directorio)
    v_arch = Verificacion("archivos", f"Archivos horarios ({horas_esperadas} esperados)")
    v_tiempo = Verificacion("continuidad", "Continuidad temporal (paso de 1 h)")
    v_col = Verificacion("columnas", "Columnas requeridas")
    v_coord = Verificacion("coordenadas", "Coordenadas y malla de 0.16°")
    v_aus = Verificacion("ausentes", "Valores ausentes")
    v_rangos = Verificacion("rangos", "Rangos físicos")
    v_unid = Verificacion("unidades", "Unidades")
    v_conv = Verificacion("convencion", "Convención de dirección del viento")
    v_corr = Verificacion("corrientes", "Campo de corrientes")
    verificaciones = [v_arch, v_tiempo, v_col, v_coord, v_aus, v_rangos, v_unid, v_conv, v_corr]

    def terminar(conjunto=None, encontrados=0):
        reporte = ReporteValidacion(
            conjunto=directorio.name,
            valido=all(v.estado != "error" for v in verificaciones),
            verificaciones=verificaciones,
            archivos_encontrados=encontrados,
            archivos_esperados=horas_esperadas,
            duracion_s=round(time.perf_counter() - t0, 3),
            resumen_conjunto=conjunto.resumen() if conjunto is not None else None,
        )
        return reporte, (conjunto if reporte.valido else None)

    # 1. Archivos -------------------------------------------------------------
    if not directorio.is_dir():
        v_arch.agregar("error", f"No existe la carpeta {directorio}.", None,
                       "Genera los datos de demostración: python scripts/generar_datos_demo.py")
        for v in verificaciones[1:]:
            v.estado, v.resumen = "error", "No evaluado: no hay archivos."
        return terminar()

    horarios: list[tuple] = []
    for ruta in sorted(p for p in directorio.iterdir() if p.is_file()):
        if ruta.suffix.lower() not in EXTENSIONES_PERMITIDAS:
            v_arch.agregar("advertencia", f"Se ignoró un archivo con extensión inesperada ({ruta.suffix}).",
                           ruta.name, "Deja en la carpeta solo los archivos .txt horarios.")
            continue
        if ruta.suffix.lower() != ".txt":
            continue
        fecha = fecha_de_nombre(ruta.name)
        if fecha is None:
            v_arch.agregar("advertencia", "Nombre sin fecha AAAAMMDDHH; no se usará.", ruta.name,
                           "Renombra el archivo como <prefijo>_AAAAMMDDHH.txt.")
            continue
        horarios.append((fecha, ruta))
    horarios.sort()
    n = len(horarios)
    if n == 0:
        v_arch.agregar("error", "No se encontraron archivos horarios .txt.", None,
                       "Genera los datos de demostración: python scripts/generar_datos_demo.py")
    elif n != horas_esperadas:
        v_arch.agregar("error", f"Se encontraron {n} archivos horarios; se esperan {horas_esperadas}.", None,
                       "Completa el conjunto: debe haber un archivo por cada hora del horizonte de 5 días.")
    v_arch.resumen = f"{n} de {horas_esperadas} archivos horarios encontrados."

    # 2. Continuidad ------------------------------------------------------------
    if horarios:
        fechas = [f for f, _ in horarios]
        inicio = fechas[0]
        esperadas = [inicio + timedelta(hours=h) for h in range(horas_esperadas)]
        presentes = set(fechas)
        prefijo = PATRON_HORARIO.match(horarios[0][1].name).group("prefijo")
        for h, f in enumerate(esperadas):
            if f not in presentes:
                v_tiempo.agregar("error", f"Falta la hora +{h} ({f:%Y-%m-%d %H:00} UTC).",
                                 f"{prefijo}_{f:%Y%m%d%H}.txt",
                                 "Solicita o vuelve a copiar el archivo faltante; el modelo necesita las 120 horas consecutivas.")
        for f in sorted(presentes - set(esperadas)):
            v_tiempo.agregar("error", f"Archivo fuera del horizonte de {horas_esperadas} h ({f:%Y-%m-%d %H:00} UTC).",
                             f"{prefijo}_{f:%Y%m%d%H}.txt", "Retira archivos que no pertenecen a este pronóstico.")
        duplicadas = len(fechas) - len(presentes)
        if duplicadas:
            v_tiempo.agregar("error", f"{duplicadas} fechas de validez duplicadas.", None,
                             "Deja un solo archivo por hora.")
        v_tiempo.resumen = (f"{inicio:%Y-%m-%d %H:00} → {esperadas[-1]:%Y-%m-%d %H:00} UTC; "
                            f"{len(presentes & set(esperadas))} de {horas_esperadas} horas consecutivas.")
    else:
        v_tiempo.estado, v_tiempo.resumen = "error", "No evaluado: no hay archivos."

    # 3–8. Contenido por archivo ---------------------------------------------
    tablas: list[tuple] = []
    malla_ref = None
    nombre_ref = None
    errores_angulo = []
    velocidades = []
    for k, (fecha, ruta) in enumerate(horarios, start=1):
        progreso(k, n + 1, f"Leyendo {ruta.name}")
        tabla = leer_tabla(ruta)
        for linea, motivo in tabla.filas_invalidas[:3]:
            v_col.agregar("error", f"Fila defectuosa en la línea {linea}: {motivo}.", ruta.name,
                          "Corrige o elimina la fila; todas deben tener el mismo número de columnas.")
        faltan = [c for c in COLUMNAS_SEMAR if c not in tabla.columnas]
        if faltan:
            v_col.agregar("error", f"Faltan columnas: {', '.join(faltan)}.", ruta.name,
                          "Verifica que el archivo provenga de la misma salida de SEMAR que el resto.")
            continue
        extra = [c for c in tabla.columnas if c not in COLUMNAS_SEMAR]
        if extra and k == 1:
            v_col.agregar("advertencia", f"Columnas adicionales ignoradas: {', '.join(extra)}.", ruta.name)
        meta_fecha = tabla.metadatos.get("fecha_validez")
        if meta_fecha and not meta_fecha.startswith(fecha.strftime("%Y-%m-%dT%H")):
            v_tiempo.agregar("advertencia", f"La fecha del encabezado ({meta_fecha}) no coincide con el nombre.",
                             ruta.name, "Confirma cuál de las dos fechas es la correcta.")

        lon = normalizar_longitud(tabla.columna("LON"))
        lat = tabla.columna("LAT")
        ok_archivo = _verificar_coordenadas(v_coord, ruta.name, tabla, lon, lat)
        _verificar_ausentes(v_aus, ruta.name, tabla)
        _verificar_rangos(v_rangos, ruta.name, tabla)
        if not ok_archivo:
            continue
        malla = np.column_stack([np.round(lon, 3), np.round(lat, 3)])
        orden = np.lexsort((malla[:, 0], malla[:, 1]))
        malla = malla[orden]
        if malla_ref is None:
            malla_ref, nombre_ref = malla, ruta.name
        elif malla.shape != malla_ref.shape or not np.allclose(malla, malla_ref, atol=TOLERANCIA_MALLA):
            v_coord.agregar("error", f"La malla no coincide con la de {nombre_ref}.", ruta.name,
                            "Todos los archivos deben compartir exactamente los mismos puntos de malla.")
            continue

        u, v = tabla.columna("U")[orden], tabla.columna("V")[orden]
        vel, dirr = tabla.columna("WindsfcSp")[orden], tabla.columna("WindsfcDir")[orden]
        vel_uv, dir_uv = vector_a_desde(u, v)
        fuerte = vel_uv > 0.5
        if fuerte.any():
            errores_angulo.append(diferencia_angular(dir_uv[fuerte], dirr[fuerte]))
        velocidades.append(vel)
        if np.nanmax(np.abs(vel_uv - vel)) > 0.05 * max(1.0, float(np.nanmax(vel))):
            v_unid.agregar("advertencia", "WindsfcSp no coincide con √(U²+V²).", ruta.name,
                           "Confirma con SEMAR si U, V y WindsfcSp están en las mismas unidades.")
        tablas.append((fecha, ruta, tabla, orden))

    # Malla y cobertura
    if malla_ref is not None:
        lons = np.unique(malla_ref[:, 0])
        lats = np.unique(malla_ref[:, 1])
        pasos = np.concatenate([np.diff(lons), np.diff(lats)])
        if pasos.size and np.max(np.abs(pasos - RESOLUCION_GRADOS)) > TOLERANCIA_MALLA:
            v_coord.agregar("error", f"El espaciamiento de malla no es {RESOLUCION_GRADOS}° "
                            f"(observado {pasos.min():.3f}–{pasos.max():.3f}°).", nombre_ref,
                            "Confirma la resolución de los datos con SEMAR.")
        if lons.size * lats.size != malla_ref.shape[0]:
            v_coord.agregar("error", "La malla no es rectangular (faltan o sobran puntos).", nombre_ref,
                            "Incluye todos los nodos de la malla aunque estén en tierra (con NaN).")
        v_coord.resumen = (f"{lons.size} × {lats.size} = {lons.size * lats.size} puntos; "
                           f"lon {lons.min():.2f}…{lons.max():.2f}, lat {lats.min():.2f}…{lats.max():.2f}; "
                           f"misma malla en {len(tablas)} archivos.")
    elif not v_coord.resumen:
        v_coord.estado = "error" if v_coord.estado == "ok" else v_coord.estado
        v_coord.resumen = "No se pudo construir la malla."

    if v_col.estado == "ok":
        v_col.resumen = f"{len(COLUMNAS_SEMAR)} columnas presentes en {len(tablas)} archivos: {', '.join(COLUMNAS_SEMAR)}."
    else:
        v_col.resumen = "Hay archivos con columnas faltantes o filas defectuosas."
    if v_aus.estado == "ok":
        v_aus.resumen = "Sin ausentes en viento y coordenadas; oleaje sin dato solo en tierra."
    if v_rangos.estado == "ok":
        v_rangos.resumen = (f"Viento, U y V dentro de 0–{VIENTO_MAX_MS:.0f} m/s y direcciones (viento y oleaje) "
                            "dentro de 0–360° en todos los archivos.")

    if velocidades:
        todas = np.concatenate(velocidades)
        media = float(np.nanmean(todas))
        v_unid.resumen = (f"Viento {np.nanmin(todas):.2f}–{np.nanmax(todas):.1f} m/s, media {media:.1f} m/s: "
                          "consistente con m/s (1 nudo = 0.514444 m/s).")
        if media > 20:
            v_unid.agregar("advertencia", f"Velocidad media de {media:.1f}: ¿podría estar en nudos o km/h?", None,
                           "Confirma las unidades con SEMAR antes de simular.")
    else:
        v_unid.estado, v_unid.resumen = ("error", "No evaluado.") if not tablas else (v_unid.estado, "")

    if errores_angulo:
        mediana = float(np.median(np.concatenate(errores_angulo)))
        if mediana > 170:
            v_conv.agregar("error", f"WindsfcDir difiere ~180° de la dirección de (U, V) (mediana {mediana:.1f}°): "
                           "parece estar en convención \"hacia\".", None,
                           "Confirma con SEMAR la convención; PMS asume dirección DESDE la que sopla.")
        elif mediana > 2:
            v_conv.agregar("error", f"WindsfcDir no es consistente con (U, V): error mediano {mediana:.1f}°.", None,
                           "Revisa el signo de U y V y la convención de WindsfcDir.")
        v_conv.resumen = (f"WindsfcDir comparada con atan2(−U, −V): error mediano {mediana:.2f}° → "
                          "convención meteorológica \"desde\" verificada. Oleaje: se asume la misma (pendiente de confirmar).")
    elif not v_conv.hallazgos:
        v_conv.estado, v_conv.resumen = "error", "No evaluado."

    # 9. Corrientes -------------------------------------------------------------
    progreso(n + 1, n + 1, "Leyendo corrientes")
    corriente = _leer_corrientes(directorio, v_corr, malla_ref)

    if not tablas or v_arch.estado == "error" or any(v.estado == "error" for v in verificaciones):
        return terminar(encontrados=n)

    conjunto = _armar_conjunto(directorio, tablas, malla_ref, corriente)
    return terminar(conjunto, encontrados=n)


def _verificar_coordenadas(v: Verificacion, nombre: str, tabla: ArchivoTabla, lon, lat) -> bool:
    ok = True
    fuera_lat = np.flatnonzero((lat < -90) | (lat > 90) | ~np.isfinite(lat))
    if fuera_lat.size:
        ok = False
        fila = tabla.linea_primer_dato + int(fuera_lat[0])
        v.agregar("error", f"Latitud fuera de rango ({lat[fuera_lat[0]]:g}) en {fuera_lat.size} fila(s), "
                  f"la primera en la línea {fila}.", nombre,
                  "Corrige la fila; LAT debe estar entre −90 y 90 (y en el recuadro de Yucatán).")
    fuera_lon = np.flatnonzero(~np.isfinite(lon))
    if fuera_lon.size:
        ok = False
        v.agregar("error", f"Longitud inválida en {fuera_lon.size} fila(s).", nombre, "Corrige la columna LON.")
    if ok:
        margen = RESOLUCION_GRADOS / 2
        fuera = (lon < LON_MIN - margen) | (lon > LON_MAX + margen) | (lat < LAT_MIN - margen) | (lat > LAT_MAX + margen)
        if fuera.any():
            v.agregar("advertencia", f"{int(fuera.sum())} puntos fuera del recuadro de Yucatán; se recortarán.",
                      nombre)
    return ok


def _verificar_ausentes(v: Verificacion, nombre: str, tabla: ArchivoTabla):
    for c in COLUMNAS_SIN_AUSENTES:
        faltan = int(np.isnan(tabla.columna(c)).sum())
        if faltan:
            v.agregar("error", f"{faltan} valores ausentes en {c}.", nombre,
                      "El viento debe estar completo en toda la malla; solicita el archivo corregido.")
    ola = tabla.columna("sfcPrimWaDir")
    if np.isnan(ola).all():
        v.agregar("advertencia", "sfcPrimWaDir sin datos en todo el archivo.", nombre)


def _verificar_rangos(v: Verificacion, nombre: str, tabla: ArchivoTabla):
    vel = tabla.columna("WindsfcSp")
    malos = int(((vel < 0) | (vel > VIENTO_MAX_MS)).sum())
    if malos:
        v.agregar("error", f"{malos} velocidades de viento fuera de 0–{VIENTO_MAX_MS:.0f} m/s.", nombre,
                  "Revisa unidades y valores de relleno (p. ej. 9999).")
    elif np.nanmax(vel) > VIENTO_ADVERTENCIA_MS:
        v.agregar("advertencia", f"Viento máximo de {np.nanmax(vel):.1f} m/s (inusual).", nombre)
    for c in ("WindsfcDir",) + COLUMNAS_OLEAJE:
        x = tabla.columna(c)
        malos = int(((x < 0) | (x > 360)).sum())
        if malos:
            v.agregar("error", f"{malos} direcciones de {c} fuera de 0–360°.", nombre, "Revisa la columna.")
    for c in ("U", "V"):
        malos = int((np.abs(tabla.columna(c)) > VIENTO_MAX_MS).sum())
        if malos:
            v.agregar("error", f"{malos} valores de {c} fuera de ±{VIENTO_MAX_MS:.0f} m/s.", nombre, "Revisa la columna.")


def _leer_corrientes(directorio: Path, v: Verificacion, malla_ref):
    carpeta = directorio / "corrientes"
    archivos = sorted(carpeta.glob("*.txt")) if carpeta.is_dir() else []
    if not archivos:
        v.agregar("error", "No se encontró el campo de corrientes (carpeta corrientes/).", None,
                  "Agrega corrientes superficiales (CMEMS/HYCOM) o regenera el demo.")
        v.resumen = "Sin corrientes."
        return None
    tabla = leer_tabla(archivos[0])
    faltan = [c for c in COLUMNAS_CORRIENTE if c not in tabla.columnas]
    if faltan:
        v.agregar("error", f"Faltan columnas: {', '.join(faltan)}.", archivos[0].name, "Corrige el archivo de corrientes.")
        return None
    lon = normalizar_longitud(tabla.columna("LON"))
    lat = tabla.columna("LAT")
    uo, vo = tabla.columna("UO"), tabla.columna("VO")
    vel = np.hypot(uo, vo)
    if np.isnan(vel).any():
        v.agregar("error", f"{int(np.isnan(vel).sum())} valores ausentes de corriente.", archivos[0].name,
                  "Usa 0 en tierra y valores numéricos en mar.")
    if np.nanmax(vel) > CORRIENTE_MAX_MS:
        v.agregar("error", f"Corriente máxima de {np.nanmax(vel):.2f} m/s (> {CORRIENTE_MAX_MS} m/s).",
                  archivos[0].name, "Revisa unidades (¿cm/s?).")
    malla = np.column_stack([np.round(lon, 3), np.round(lat, 3)])
    orden = np.lexsort((malla[:, 0], malla[:, 1]))
    if malla_ref is not None and (malla.shape != malla_ref.shape
                                  or not np.allclose(malla[orden], malla_ref, atol=TOLERANCIA_MALLA)):
        v.agregar("error", "La malla de corrientes no coincide con la del viento.", archivos[0].name,
                  "Interpola las corrientes a la malla de 0.16° antes de cargarlas.")
        return None
    esquematica = tabla.sintetico or any("ESQUEMATICA" in c.upper() for c in tabla.metadatos["_comentarios"])
    if esquematica:
        v.agregar("advertencia", "Corrientes ESQUEMÁTICAS (sintéticas), no de CMEMS/HYCOM.", archivos[0].name,
                  "Sustituir por corrientes operativas cuando se confirme la fuente.")
    v.resumen = (f"{archivos[0].name}: estacionario, máx. {np.nanmax(vel):.2f} m/s"
                 + (" — esquemático." if esquematica else "."))
    return {"u": uo[orden], "v": vo[orden], "esquematica": esquematica}


def _armar_conjunto(directorio: Path, tablas, malla_ref, corriente) -> ConjuntoDatos:
    lons = np.unique(malla_ref[:, 0])
    lats = np.unique(malla_ref[:, 1])
    forma = (len(tablas), lats.size, lons.size)
    campos = {c: np.empty(forma, dtype=np.float32) for c in ("U", "V", "WindsfcSp", "WindsfcDir", "sfcPrimWaDir")}
    for k, (_f, _r, tabla, orden) in enumerate(tablas):
        for c, destino in campos.items():
            destino[k] = tabla.columna(c)[orden].reshape(lats.size, lons.size)
    mar = np.isfinite(campos["sfcPrimWaDir"][0])
    rutas = [r for _f, r, _t, _o in tablas]
    return ConjuntoDatos(
        id=directorio.name,
        lons=lons, lats=lats,
        tiempos=[f for f, _r, _t, _o in tablas],
        viento_u=campos["U"], viento_v=campos["V"],
        viento_vel=campos["WindsfcSp"], viento_dir=campos["WindsfcDir"],
        ola_dir=campos["sfcPrimWaDir"],
        corriente_u=corriente["u"].reshape(lats.size, lons.size).astype(np.float32),
        corriente_v=corriente["v"].reshape(lats.size, lons.size).astype(np.float32),
        mar=mar,
        archivos=[r.name for r in rutas],
        huella=huella_archivos(rutas + sorted((directorio / "corrientes").glob("*.txt"))),
        sintetico=any(t.sintetico for _f, _r, t, _o in tablas[:1]),
        corrientes_esquematicas=bool(corriente["esquematica"]),
    )
