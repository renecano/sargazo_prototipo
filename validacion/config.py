"""Constantes de la validación: fuentes, umbrales, casos y experimentos.

Todo valor que influye en un número del reporte vive aquí, con su justificación, para que
se pueda revisar y volver a correr sin buscar constantes sueltas en el código.
"""
from __future__ import annotations

from datetime import date

from src.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, RAIZ

DIR_CACHE = RAIZ / "data" / "validacion"        # descargas completas (no se suben a git)
DIR_RESULTADOS = RAIZ / "docs" / "validacion"   # tablas, figuras y JSON que sí se suben

# ---------------------------------------------------------------------------
# Observaciones: AFAI de USF (Chuanmin Hu) servido por NOAA AOML ERDDAP
# ---------------------------------------------------------------------------
ERDDAP = "https://cwcgom.aoml.noaa.gov/erddap/griddap"
DATASET_AFAI_1D = "noaa_aoml_atlantic_oceanwatch_AFAI_1D"
DATASET_AFAI_7D = "noaa_aoml_atlantic_oceanwatch_AFAI_7D"   # documentado; no se usa (ver docs)
VARIABLE_AFAI = "AFAI"

# Solo se descarga el recuadro donde corre el modelo (dentro de la malla de dirmarea.txt):
# fuera de él no hay costa del modelo ni simulación con la que comparar.
RECUADRO = (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)

# Detección de sargazo (Wang & Hu, 2016, RSE 183:350-367, doi:10.1016/j.rse.2016.04.019):
#   ΔAFAI = AFAI − fondo, con el fondo = mediana en una ventana de 51 × 51 píxeles que
#   excluye los píxeles candidatos (ΔAFAI preliminar > Ts). Píxel con sargazo si ΔAFAI > T0.
UMBRAL_T0 = 1.79e-4             # captura ~95 % de los píxeles con sargazo (Wang & Hu, 2016, §4.1.2.3)
UMBRAL_TS = 2.55e-4             # candidatos que se excluyen del fondo (Wang & Hu, 2016, §4.1.2.1)
K_SIGMA = 3.0                   # además ΔAFAI > 3σ del ruido local (umbral local por distribución de la
                                # ventana, como Garcia et al., 2013, citado en Wang & Hu §2): el ruido del
                                # producto en el Caribe es del orden de T0. Fijado antes de correr experimentos.
VENTANA_FONDO = 51              # píxeles (Wang & Hu, 2016, §4.1.2.2)
PASO_FONDO = 10                 # la mediana se evalúa cada 10 píxeles y se interpola (ahorro de cómputo)
MIN_VALIDOS_FONDO = 0.10        # fracción mínima de píxeles válidos en la ventana para estimar el fondo
COSTURA_LAT, COSTURA_LON = 22.0, -90.0   # bordes de las dos regiones del producto de AOML (ver afai.py)
FRANJA_COSTURA_PX = 25          # del lado «Caribe», en los 25 px junto a la costura la frecuencia de detección
                                # sube de ~6 % a ~26 % hacia el borde (artefacto del producto): se excluye
BORDE_NUBE_PX = 2               # píxeles junto a una nube se descartan (efecto de adyacencia)
FRECUENCIA_PERSISTENTE = 0.20   # píxel "brillante" en ≥ 20 % de sus observaciones: fondo somero o
                                # turbidez fija, no sargazo (el sargazo se mueve); se excluye

# ---------------------------------------------------------------------------
# Selección automática de casos
# ---------------------------------------------------------------------------
BUSQUEDA_DESDE = date(2022, 1, 1)   # temporadas 2022–2026 (SMOC en Open-Meteo empieza en 2022)
BUSQUEDA_HASTA = date(2026, 10, 30)  # última imagen disponible al descargar
HORIZONTES_D = (3, 5, 7)
MIN_PIXELES_SARGAZO = 150       # píxeles con sargazo en t0 (~380 km² de píxeles con sargazo)
MIN_CLARO_T0 = 0.50             # fracción del mar útil sin nube en t0
MIN_CLARO_DESTINO = 0.40        # fracción del mar útil sin nube en +3, +5 y +7 días
MIN_CLARO_ZONA = 0.40           # fracción sin nube alrededor del sargazo de t0 (± 50 km) en cada destino
RADIO_ZONA_KM = 50.0
# Los casos no comparten imágenes: entre dos t0 elegidos hay más de 7 días, así cada imagen
# pertenece a un solo caso y el bootstrap por caso no repite información.
# Se pre-registró antes de correr: calibración = t0 antes de 2025, evaluación = 2025–2026.
CORTE_EVALUACION = date(2025, 1, 1)

# Hora nominal de la imagen: MODIS-Aqua y VIIRS pasan hacia las 13:30 hora solar
# (≈ 18:30 UTC a 87° O) y MODIS-Terra hacia las 10:30 (≈ 15:30 UTC). Se usa 18 UTC.
HORA_IMAGEN_UTC = 18
FECHA_DIRMAREA_SEMAR = date(2026, 10, 1)

# ---------------------------------------------------------------------------
# Experimentos
# ---------------------------------------------------------------------------
PARTICULAS = 20_000             # mismo número en todos los experimentos de un caso
SEMILLA = 2026
GAMMA_V03, KH_V03 = 1.0, 10.0   # PMS v0.3 tal cual
REJILLA_GAMMA = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)        # calibración de E3 (solo casos de calibración)
REJILLA_KH = (1.0, 10.0, 50.0, 100.0)
FACTORES_VIENTO = (0.01, 0.02, 0.03)                   # E5: 1 %, 2 % y 3 % del viento a 10 m

# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
ESCALAS_FSS_KM = (10, 25, 50)
ESCALA_CALIBRACION_KM = 25      # E3 maximiza el FSS medio a esta escala en los tres horizontes
BANDA_COSTA_KM = 10.0           # "pegado a la costa": a ≤ 10 km de la costa del modelo
REMUESTREOS_BOOTSTRAP = 2000
MIN_CASOS_VEREDICTO = 5         # con menos casos comparados no se declara "mejor" ni "peor"
NIVEL_CONFIANZA = 0.95

# MCC (correlación cruzada máxima) entre imágenes AFAI de días consecutivos
MCC_PLANTILLA_PX = 21           # ~33 km de lado
MCC_BUSQUEDA_PX = 40            # ± 40 px ≈ ± 64 km en un día (≤ 0.74 m/s)
MCC_MIN_SARGAZO = 15            # píxeles con sargazo dentro de la plantilla
MCC_MIN_VALIDOS = 0.70          # fracción válida en la plantilla y en la zona de búsqueda
MCC_MIN_CORRELACION = 0.50
