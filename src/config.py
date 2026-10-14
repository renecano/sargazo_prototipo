"""Constantes compartidas de PMS.

Todo lo que define el dominio, la malla, los archivos de SEMAR y la versión del modelo
vive aquí para que ingesta, modelo, API e interfaz usen exactamente los mismos valores.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"
DIR_SEMAR = DIR_DATOS / "semar"          # datos reales, fuera de git (ver data/semar/README.md)
DIR_SIMULACIONES = DIR_DATOS / "simulations"
DIR_VISTA = RAIZ / "src" / "view"

# En Vercel (funciones sin servidor) el disco es de solo lectura salvo /tmp y cada
# petición puede caer en otra instancia: no hay trabajos en segundo plano compartidos.
SERVERLESS = os.environ.get("VERCEL") == "1"

VERSION_APP = "0.2.0"
VERSION_MODELO = "pms-lagrangiano-0.2.0"

# Malla de 0.16° de SEMAR (124°W–76°W, 7°N–39°N). El modelo usa los nodos del recuadro
# de Yucatán: 51 × 39 = 1 989 nodos.
RESOLUCION_GRADOS = 0.16
LON_MIN, LON_MAX = -92.0, -84.0
LAT_MIN, LAT_MAX = 16.92, 23.0

HORIZONTE_H = 120               # 5 días
PASO_SEGUNDOS = 3600.0          # Δt = 1 h
PASO_OLEAJE_H = 3               # dirmarea.txt: +0, +3, …, +120 h
RADIO_TIERRA_M = 6_371_000.0

# Archivos y columnas de SEMAR (separador ";", relleno -9.99e+08)
ARCHIVO_VIENTO = "salidadatos.txt"
ARCHIVO_OLEAJE = "dirmarea.txt"
CARPETA_CORRIENTES = "corrientes"
COLUMNAS_VIENTO = ("LON", "LAT", "sfcPrimWaDir", "sfcDirWindWa", "U", "V", "WindsfcSp", "WindsfcDir")
COLUMNAS_OLEAJE = ("LON", "LAT", "dirolavto", "alturaolavto")
COLUMNAS_CORRIENTE = ("LON", "LAT", "UO", "VO")
VALOR_RELLENO = -9.99e8
UMBRAL_RELLENO = -1.0e8         # todo valor menor se trata como relleno (sin dato)

# Hora local de Cancún: UTC−5 todo el año (Quintana Roo no aplica horario de verano).
DESFASE_CANCUN_H = -5
