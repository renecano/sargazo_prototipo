# Fuentes de la validación (v0.4.0)

Todas se verificaron consultándolas directamente el **31/10/2026** (metadatos, ejes de tiempo y una
descarga de prueba). Ninguna pide llave. Las descargas completas viven en la caché local
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

## c) Oleaje real: Open-Meteo Marine API

| | |
|---|---|
| URL | `https://marine-api.open-meteo.com/v1/marine` (sin llave, uso no comercial) |
| Modelo | `models=meteofrance_wave`: MeteoFrance **MFWAM**, global 0.08°, cada 3 h (Open-Meteo lo entrega horario), disponible desde oct 2021 |
| Variables | `wind_wave_height` (m), `wind_wave_direction` (°, **desde** donde viene, igual que `dirolavto`), `wind_wave_period` (s) |
| Uso | `scripts/generar_dirmarea.py` y `validacion/dirmarea.py` escriben `dirmarea.txt` con la ola de viento real; el período solo se usa para comparar con el supuesto T = 4·√H |
| Alternativa revisada | `models=era5_ocean` (ERA5, 0.5°, desde 1940): no ofrece la partición de ola de viento en Open-Meteo, por eso no se usa |

## d) Solo para experimentos: corriente superficial y viento a 10 m

| | Corriente | Viento |
|---|---|---|
| URL | `https://marine-api.open-meteo.com/v1/marine` | `https://archive-api.open-meteo.com/v1/archive` |
| Modelo | `models=meteofrance_currents`: MeteoFrance **SMOC**, 0.08°, horario, desde ene 2022 | `models=era5`: **ERA5** (ECMWF), 0.25°, horario; ~5 días de retraso |
| Variables | `ocean_current_velocity` (km/h → m/s), `ocean_current_direction` (°, **hacia** donde va) | `wind_speed_10m` (m/s con `wind_speed_unit=ms`), `wind_direction_10m` (°, **desde**) |
| Nota | Open-Meteo la define como «Velocity of ocean current considering Eulerian, Waves and Tides»: ya incluye deriva por oleaje y marea | Reanálisis |

**Licencia y atribución (c y d)**: datos de Open-Meteo bajo **CC BY 4.0** (uso no comercial gratuito);
Open-Meteo pide atribuir a los proveedores de cada modelo: Météo-France / Copernicus Marine (MFWAM, SMOC)
y ECMWF / Copernicus Climate Change Service (ERA5).

**Cuota y resolución**: el uso gratuito permite 600 llamadas por minuto, 5 000 por hora y 10 000 por día,
y **cada punto de una petición cuenta como una llamada** (verificado el 31/10/2026: una petición de 700
puntos pasó y la siguiente de 1 295 en el mismo minuto recibió HTTP 429 «Minutely API request limit
exceeded»). Por eso se descarga una submalla de la malla de 0.16° de `dirmarea.txt`: un nodo de cada dos
(0.32°, 366 puntos) para ola y corriente, y uno de cada tres (0.48°, 172 puntos) para viento, solo en los
nodos de mar del archivo de SEMAR dentro del recuadro del modelo (más una celda de margen); después se
interpola de forma bilineal a 0.16°. Cada caso pide t0…t0 + 10 días (una sola llamada por punto).

**Limitaciones**: MFWAM y SMOC en Open-Meteo son archivos de pronósticos de corto plazo, no reanálisis; la
corriente de SMOC es poco confiable cerca de la costa (lo advierte Open-Meteo); la submalla suaviza los
remolinos de menos de ~35 km.

## Archivo de referencia de SEMAR

`data/semar/dirmarea.txt` (01/10/2026, 41 bloques idénticos) se compara contra MFWAM en el caso de esa fecha.
