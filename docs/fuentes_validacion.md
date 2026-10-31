# Fuentes de la validación (v0.4.0)

Todas se verificaron consultándolas directamente el **31/10/2026** (metadatos, ejes de tiempo y una
descarga de prueba). Solo Copernicus Marine pide cuenta (gratuita); sus credenciales nunca entran al repositorio. Las descargas completas viven en la caché local
`data/validacion/` (fuera de git y de Vercel); en el repositorio solo quedan los recortes pequeños de
`tests/fixtures/` y los resultados de `docs/validacion/`, cada uno con su fuente.

## a) Sargazo observado: AFAI diario de USF en NOAA AOML ERDDAP (la "verdad")

| | |
|---|---|
| Servidor | NOAA AOML ERDDAP, `https://cwcgom.aoml.noaa.gov/erddap/griddap/` |
| Dataset usado | `noaa_aoml_atlantic_oceanwatch_AFAI_1D` — «1-day USF AFAI Fields (USF AFAI 1D AOML)» |
| Dataset documentado, no usado | `noaa_aoml_atlantic_oceanwatch_AFAI_7D` — acumulado de 7 días |
| Variable | `AFAI` (Alternative Floating Algae Index, reflectancia); `_FillValue` NaN; `actual_range` −0.002…0.004 |
| Malla | 0.015° (lat 0.0150020°, lon 0.015°), lon −98…−38, lat 0…38 |
| Tiempo | diario, nominal 12:00 UTC; del 18/06/2016 al 30/10/2026 al descargar. 2022–2026: 1 765 días con imagen; falta casi todo julio de 2025 (22 días) |
| Recorte descargado | solo el recuadro donde corre el modelo: lon −92.08…−84.08, lat 16.92…23.00 (534 × 406 píxeles), dentro del dominio de `dirmarea.txt`. Un archivo NetCDF por mes (`.nc` de ERDDAP, leído con `scipy.io.netcdf_file`) |
| Origen | Optical Oceanography Laboratory, College of Marine Science, University of South Florida (Chuanmin Hu); distribuye NOAA/OAR/AOML/PHOD (Atlantic OceanWatch) |
| Licencia (metadatos) | «The data may be used and redistributed for free but is not intended for legal use, since it may contain inaccuracies.» Sin garantía |
| Atribución | USF AFAI (C. Hu) vía NOAA AOML Atlantic OceanWatch ERDDAP; Hu, C., Feng, L., Hardy, R. F. y Hochberg, E. J. (2015), *Remote Sens. Environ.* 167:229-246, doi:10.1016/j.rse.2015.05.022 |

**Umbral "aquí hay sargazo"** — Wang, M. y Hu, C. (2016). *Mapping and quantifying Sargassum
distribution and coverage in the Central West Atlantic using MODIS observations.* Remote Sensing of
Environment 183:350-367, doi:10.1016/j.rse.2016.04.019. Verificado en el texto completo (copia del autor
en sargcoop.org):

- §4.1.2.2: el fondo sin sargazo (*Ref AFAI*) es la mediana en una ventana de **51 × 51 píxeles**.
- §4.1.2.1: los píxeles con AFAI por encima del ajuste en **Ts = 2.55 × 10⁻⁴** se excluyen del fondo.
- §4.1.2.3: un píxel contiene sargazo si **AFAI − Ref AFAI > T0 = 1.79 × 10⁻⁴**; con ese valor «about 95% of the
  Sargassum-containing pixels were captured while only 10% of the adjacent Sargassum-free pixels were misclassified».
- §6 (sensibilidad): cambiar T0 de 1.53 a 1.79 × 10⁻⁴ cambia ~10 % el área estimada.

**Cómo se usa aquí** (`validacion/afai.py`, `validacion/inventario.py`):

- Nubes, brillo solar y tierra: ya vienen como NaN en el producto de AOML. Además se descartan 2 píxeles
  alrededor de cada nube (efecto de adyacencia; Wang & Hu eliminan los píxeles ambiguos junto a nubes).
- **Umbral adaptado al ruido**: además de ΔAFAI > T0 se exige ΔAFAI > 3σ, con σ = 1.4826 × MAD de ΔAFAI
  en la misma ventana. El ruido de ΔAFAI de este producto en el Caribe (~2 × 10⁻⁴, medido en el recuadro)
  es del orden de T0: con T0 solo, en enero (sin temporada) 11–18 % del Caribe abierto salía con
  "sargazo". Se fijó antes de correr cualquier experimento.
- **Dos regiones del producto**: el AFAI de AOML une dos regiones con niveles de ruido distintos y bordes
  rectos en 22.0° N y 90.0° O (1 = lat < 22.0 y lon > −90.0; 0 = el resto). Se ven como un salto brusco en
  la frecuencia de detección y en el número de observaciones 2022–2026. El fondo y el ruido se estiman
  por región; si se mezclan, aparece una franja falsa de "sargazo" de ~15 km junto a la costura. Aun por
  región, del lado «Caribe» la frecuencia de detección sube de forma monótona en los 25 píxeles junto a la
  costura (de ~6 % a ~26 %; del otro lado, 2–3 %): es un artefacto de los valores del producto en el borde, así
  que esa franja de 25 píxeles se excluye del mar evaluado.
- No hay máscara de sombra de nube (Wang & Hu usan bandas de reflectancia que este producto no trae).
- El fondo sale de dos pasadas de mediana de 51 × 51 (evaluada cada 10 píxeles e interpolada), sin el
  ajuste polinómico de 4.º grado del artículo.
- Píxeles "brillantes persistentes" (sobre el umbral en ≥ 20 % de sus observaciones 2022–2026) y píxeles
  observados menos de 30 veces se excluyen: son fondo somero, turbidez fija o zonas sin cobertura (AOML no
  cubre la franja al sur de 21° N y al oeste de 90.5° O).

**Limitaciones**: el AFAI satura con nubes, brillo solar y aerosoles espesos; en aguas someras o turbias
puede dar falsos positivos; el umbral se derivó para MODIS en el Atlántico central; el producto diario
puede combinar sensores (sus palabras clave mencionan MODIS y VIIRS) con horas de paso distintas
(≈ 15:30 a 18:30 UTC sobre el Caribe mexicano); el sargazo varado en la playa no se ve. **El acumulado de 7 días
(AFAI_7D) no se usa**: combina 7 días de imágenes, así que mezcla posiciones y no sirve para medir desplazamientos.

## b) Segunda opinión: detección diaria con Sentinel-3 OLCI (no se pudo usar)

| | |
|---|---|
| Referencia | Debue, M., Guinaldo, T., Tarasenko, A. y Saux-Picart, S. (2026). *Daily Sargassum detection from OLCI images over the tropical Atlantic Ocean since 2018 through a multi-index approach.* ESSD, preprint essd-2026-589 (en revisión; discusión abierta hasta el 30/09/2026) |
| Datos | Météo-France (2026), *Daily composite of Sargassum detection derived from OLCI observations*, v1, Ifremer/CERSAT, doi:10.12770/1eb82d09-77ed-4f63-9f03-2c3516a9713d |
| Acceso declarado | `https://data-cersat.ifremer.fr/data/sargassum/` y `ftp.ifremer.fr/ifremer/cersat/data/sargassum`; política «Unrestricted» |
| Malla y tiempo | 0.0032°, lon −100…−10, lat 0…30; diario desde el 08/05/2018 |

**Estado**: el 31/10/2026 tanto el HTTPS como el FTP de Ifremer/CERSAT dieron *timeout* desde la red donde
se corrió la validación, así que no hay comparación con OLCI. Queda como siguiente paso; el código de
métricas no depende del sensor.

## c) Oleaje y corriente reales: Copernicus Marine Service

Origen de MFWAM y SMOC, sin cuota por punto y a resolución completa. Se accede con el toolbox
oficial **`copernicusmarine` 2.5.0** (Python API `open_dataset` sobre los servicios ARCO; está en
`requirements-validacion.txt`). Requiere una cuenta gratuita: la primera vez se corre
`copernicusmarine login` en la terminal y el toolbox guarda las credenciales en la carpeta del usuario
(`~/.copernicusmarine/`), **nunca en el repositorio ni en los logs**. IDs, cobertura y variables se
verificaron con `copernicusmarine describe` el **31/10/2026**; la cobertura se vuelve a consultar en cada
corrida (`validacion/copernicus.py`, caché en `data/validacion/copernicus/catalogo.json`).

| | Ola de viento (análisis y pronóstico) | Ola de viento (reanálisis) | Corriente SMOC |
|---|---|---|---|
| Producto | GLOBAL_ANALYSISFORECAST_WAV_001_027, «Global Ocean Waves Analysis and Forecast» | GLOBAL_MULTIYEAR_WAV_001_032, «Global Ocean Waves Reanalysis» | GLOBAL_ANALYSISFORECAST_PHY_001_024, «Global Ocean Physics Analysis and Forecast» |
| DOI | [10.48670/moi-00017](https://doi.org/10.48670/moi-00017) | [10.48670/moi-00022](https://doi.org/10.48670/moi-00022) | [10.48670/moi-00016](https://doi.org/10.48670/moi-00016) |
| Dataset | `cmems_mod_glo_wav_anfc_0.083deg_PT3H-i` (versión 202411) | `cmems_mod_glo_wav_my_0.2deg_PT3H-i` (versión 202411) | `cmems_mod_glo_phy_anfc_merged-uv_PT1H-i` (versión 202211) |
| Cobertura (31/10/2026) | 01/11/2022 03:00 → 10/11/2026 00:00 UTC | 01/01/1980 → 31/08/2026 21:00 UTC | 01/11/2020 → 09/11/2026 23:00 UTC |
| Resolución | 0.083° (1/12°), cada 3 h | 0.2°, cada 3 h | 0.083° (1/12°), cada hora, superficie (0.49 m) |
| Variables usadas | `VHM0_WW` (altura de la ola de viento, m), `VMDR_WW` (dirección media DESDE la que viene, °), `VTM01_WW` (período medio, s), `VSDX`/`VSDY` (deriva de Stokes del espectro completo, m/s) | las mismas | `uo`/`vo` (euleriana), `utide`/`vtide` (marea), `utotal`/`vtotal` (= uo + utide + vsdx; verificado, diferencia máxima 0.001 m/s) |
| Uso | `dirmarea.txt` real de cada caso (E1–E3, E5) y verificación del período y de la fórmula de Stokes del modelo | lo mismo para casos con fechas antes de nov 2022 | E4 = corriente total; E5 = corriente sin Stokes (uo + utide), porque la ola del modelo ya pone la deriva por oleaje |
| Productor | Mercator Ocean International | Mercator Ocean International | Mercator Ocean International |

**Qué fuente usó cada caso**: se elige por cobertura (`copernicus.elegir_oleaje`): el análisis y pronóstico de
0.083° si cubre toda la ventana del caso (t0 … t0 + 10 d) y, si no, el reanálisis de 0.2°. Cada caso guarda su
dataset y su resolución en las columnas `fuente_oleaje`, `oleaje_resolucion_grados` y `fuente_corriente` de
`docs/validacion/casos.csv`. Se descarga solo el recorte del recuadro del modelo (más 0.35° de margen para
interpolar en los bordes), a la resolución nativa y sin submuestrear. La ola se interpola de forma bilineal a los
nodos de 0.16° del `dirmarea.txt` (formato del producto); la corriente se usa a 0.083°.

**Licencia y atribución**: «Licence to use the Copernicus Marine Service products»: gratuita, mundial, no
exclusiva y perpetua; permite modificar y distribuir productos derivados «for any purpose». Obliga a dar
crédito visible donde se muestran los datos: **«Generated using E.U. Copernicus Marine Service Information;
https://doi.org/10.48670/moi-00017, https://doi.org/10.48670/moi-00022, https://doi.org/10.48670/moi-00016»**
(está en `docs/validacion.md`, en la página `/validacion` y en el README).

**Limitaciones**: MFWAM y SMOC de análisis y pronóstico son la mejor estimación operativa de cada día, no un
reanálisis; antes de nov 2022 la ola sale del reanálisis, más grueso (0.2°). La deriva de Stokes del producto
(VSDX/VSDY) incluye el mar de fondo; la del modelo solo la ola de viento. Bajar un caso cuesta ~4 min (una
variable a la vez para no pasar de ~100 MB de memoria).

## d) Solo para E5: viento a 10 m (Open-Meteo)

| | |
|---|---|
| URL | `https://archive-api.open-meteo.com/v1/archive` (sin llave, uso no comercial) |
| Modelo | `models=era5`: **ERA5** (ECMWF), 0.25°, horario; ~5 días de retraso |
| Variables | `wind_speed_10m` (m/s con `wind_speed_unit=ms`), `wind_direction_10m` (°, **desde**) |
| Puntos | submalla de 0.48° (un nodo de cada tres de la malla de 0.16°): ~170 puntos por caso, interpolados después |
| Licencia y atribución | Open-Meteo bajo **CC BY 4.0**; atribuir a ECMWF / Copernicus Climate Change Service (ERA5) y a Open-Meteo |

## Fuente previa (documentada, ya no se usa): oleaje y corriente de Open-Meteo

Hasta la primera corrida de la v0.4.0, la ola de viento (`models=meteofrance_wave`, MFWAM) y la corriente
(`models=meteofrance_currents`, SMOC) se pedían a la Marine API de Open-Meteo. Open-Meteo cuenta **cada punto de
una petición como una llamada** (verificado el 31/10/2026: una petición de 700 puntos pasó y la siguiente de 1 295
en el mismo minuto recibió HTTP 429 «Minutely API request limit exceeded») y el uso gratuito permite 600 llamadas
por minuto, 5 000 por hora y 10 000 por día. Aun pidiendo una submalla de 0.32° (366 puntos por variable y caso),
la cuota diaria se agotó con 0 casos de evaluación completos. **Todos los casos se rehicieron con Copernicus
Marine**: ningún resultado mezcla datos de 0.32° interpolados de Open-Meteo con datos de 0.083°.

## Archivo de referencia de SEMAR

`data/semar/dirmarea.txt` (01/10/2026, 41 bloques idénticos) se compara contra MFWAM en el caso de esa fecha.
