"""API FastAPI del prototipo PMS y servidor de la interfaz estática."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Path as RutaParam
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.api.almacen import Almacen
from src.api.servicios import (
    PATRON_CONJUNTO, ErrorConAccion, GestorTrabajos, ServicioDatos, ejecutar_simulacion,
)
from src.config import (
    DIR_DATOS, DIR_SIMULACIONES, DIR_VISTA, HORAS_ESPERADAS, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN,
    SERVERLESS, VERSION_APP, VERSION_MODELO,
)
from src.model import costa
from src.model.simulacion import Parametros, PuntoInvalido, validar_punto

# En Windows el registro puede declarar .js como text/plain y el navegador rechaza los módulos ES.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


class SolicitudSimulacion(BaseModel):
    conjunto: str = Field("demo", pattern=PATRON_CONJUNTO)
    lon: float = Field(..., ge=LON_MIN, le=LON_MAX, description="Longitud del punto de liberación (°, oeste negativo)")
    lat: float = Field(..., ge=LAT_MIN, le=LAT_MAX, description="Latitud del punto de liberación (°)")
    radio_km: float = Field(5.0, ge=0.5, le=50.0, description="Radio inicial del conglomerado (km)")
    particulas: int = Field(2000, ge=100, le=5000)
    alpha_pct: float = Field(1.0, ge=0.0, le=4.0, description="Arrastre del viento α (%)")
    kh_m2s: float = Field(10.0, ge=0.0, le=100.0, description="Difusión horizontal K_h (m²/s)")
    horizonte_h: int = Field(120, ge=24, le=HORAS_ESPERADAS)
    semilla: int = Field(2026, ge=0, le=2**31 - 1)

    def parametros(self) -> Parametros:
        return Parametros(lon=self.lon, lat=self.lat, radio_km=self.radio_km, particulas=self.particulas,
                          alpha_pct=self.alpha_pct, kh_m2s=self.kh_m2s, horizonte_h=self.horizonte_h,
                          semilla=self.semilla)


def crear_app(dir_datos: Path = DIR_DATOS, dir_simulaciones: Path = DIR_SIMULACIONES) -> FastAPI:
    app = FastAPI(title="PMS · Predicción de Movimiento del Sargazo (prototipo)", version=VERSION_APP)
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    datos = ServicioDatos(dir_datos)
    almacen = Almacen(dir_simulaciones)
    trabajos = GestorTrabajos()
    app.state.datos, app.state.almacen, app.state.trabajos = datos, almacen, trabajos

    @app.exception_handler(ErrorConAccion)
    async def _error_con_accion(_request, e: ErrorConAccion):
        return JSONResponse(status_code=e.codigo, content={"detail": e.a_dict()})

    @app.exception_handler(PuntoInvalido)
    async def _punto_invalido(_request, e: PuntoInvalido):
        return JSONResponse(status_code=422, content={"detail": {
            "causa": str(e), "accion": "Haz clic en un punto del mar dentro del recuadro de la malla.", "archivo": None}})

    @app.get("/api/salud")
    def salud():
        return {
            "estado": "ok", "version_app": VERSION_APP, "version_modelo": VERSION_MODELO,
            # En modo sin servidor la interfaz usa los endpoints síncronos y avisa que el
            # historial vive en almacenamiento temporal.
            "trabajos_en_segundo_plano": not SERVERLESS,
            "almacenamiento_efimero": SERVERLESS,
        }

    @app.get("/api/conjuntos")
    def conjuntos():
        return datos.listar()

    @app.get("/api/conjuntos/{conjunto_id}/validacion")
    def validacion(conjunto_id: str = RutaParam(..., pattern=PATRON_CONJUNTO)):
        reporte, _ = datos.validar(conjunto_id)
        return reporte.a_dict()

    @app.post("/api/conjuntos/{conjunto_id}/validar")
    def validar_async(conjunto_id: str = RutaParam(..., pattern=PATRON_CONJUNTO), forzar: bool = False):
        trabajo = trabajos.lanzar(
            "validacion", lambda progreso: datos.validar(conjunto_id, progreso, forzar=forzar)[0].a_dict())
        return {"trabajo_id": trabajo.id}

    @app.get("/api/conjuntos/{conjunto_id}/campos")
    def campos(conjunto_id: str = RutaParam(..., pattern=PATRON_CONJUNTO)):
        return datos.campos(conjunto_id)

    @app.get("/api/costa")
    def geojson_costa():
        return costa.geojson()

    @app.post("/api/simulaciones")
    def crear_simulacion(s: SolicitudSimulacion):
        """Ejecuta una simulación de forma síncrona, la guarda y devuelve el registro completo."""
        return ejecutar_simulacion(datos, almacen, s.conjunto, s.parametros())

    @app.post("/api/trabajos/simulacion")
    def simulacion_async(s: SolicitudSimulacion):
        """Igual que POST /api/simulaciones, pero en segundo plano para mostrar el progreso."""
        p = s.parametros()
        validar_punto(p.lon, p.lat)
        trabajo = trabajos.lanzar(
            "simulacion", lambda progreso: ejecutar_simulacion(datos, almacen, s.conjunto, p, progreso))
        return {"trabajo_id": trabajo.id}

    @app.get("/api/trabajos/{trabajo_id}")
    def estado_trabajo(trabajo_id: str, incluir_resultado: bool = True):
        try:
            return trabajos.obtener(trabajo_id).a_dict(incluir_resultado)
        except KeyError:
            raise HTTPException(404, "Trabajo no encontrado") from None

    @app.get("/api/simulaciones")
    def listar_simulaciones():
        return almacen.listar()

    @app.get("/api/simulaciones/{sim_id}")
    def obtener_simulacion(sim_id: str):
        try:
            return almacen.cargar(sim_id)
        except KeyError:
            raise HTTPException(404, "Simulación no encontrada") from None

    @app.get("/", include_in_schema=False)
    def inicio():
        return FileResponse(DIR_VISTA / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=DIR_VISTA), name="static")
    return app
