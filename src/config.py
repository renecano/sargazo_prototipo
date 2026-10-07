"""Constantes compartidas del prototipo PMS.

Todo lo que define el dominio, la malla y la versión del modelo vive aquí para que
ingesta, modelo, API e interfaz usen exactamente los mismos valores.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"
DIR_SIMULACIONES = DIR_DATOS / "simulations"
DIR_VISTA = RAIZ / "src" / "view"

VERSION_APP = "0.1.0"
VERSION_MODELO = "pms-lagrangiano-0.1.0"

# Malla de 0.16° alineada con la malla del archivo de SEMAR analizado
# (124°W–76°W, 7°N–39°N). El recuadro de Yucatán usa los nodos que caen en él.
RESOLUCION_GRADOS = 0.16
LON_MIN, LON_MAX = -92.0, -84.0
LAT_MIN, LAT_MAX = 16.92, 23.0

HORAS_ESPERADAS = 120          # 5 días = 120 archivos horarios
PASO_SEGUNDOS = 3600.0          # Δt = 1 h
RADIO_TIERRA_M = 6_371_000.0

COLUMNAS_SEMAR = (
    "LON", "LAT", "U", "V", "WindsfcSp", "WindsfcDir", "sfcPrimWaDir", "sfcDirWindWa",
)
COLUMNAS_CORRIENTE = ("LON", "LAT", "UO", "VO")

# Hora local de Cancún: UTC−5 todo el año (Quintana Roo no aplica horario de verano).
DESFASE_CANCUN_H = -5
