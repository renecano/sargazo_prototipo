# Recortes para las pruebas sin red

| Archivo | Fuente | Contenido |
|---|---|---|
| `afai_recorte_2025-06-01.nc` | NOAA AOML ERDDAP, dataset `noaa_aoml_atlantic_oceanwatch_AFAI_1D` (AFAI de USF, C. Hu). Descargado el 31/10/2026 con `validacion.afai.url_afai(date(2025, 6, 1), date(2025, 6, 2), recuadro=(-86.90, -86.60, 20.90, 21.20))` | AFAI de 21 × 21 píxeles (0.015°) frente a Cancún, 1 y 2 de junio de 2025, NetCDF-3 tal como lo entrega ERDDAP (9 KB). Licencia del dataset: uso y redistribución libres, sin garantía |

Los demás datos de las pruebas de validación (oleaje, corriente, viento, inventario) son
sintéticos y se construyen en `tests/test_validacion.py`.
