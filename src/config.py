"""Constantes compartidas de PMS.

Todo lo que define el dominio, la malla, el archivo de SEMAR, el modelo y su versión vive
aquí para que ingesta, modelo, API e interfaz usen exactamente los mismos valores.
"""
import math
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"
DIR_SEMAR = DIR_DATOS / "semar"          # datos reales de SEMAR (ver data/semar/README.md)
DIR_SIMULACIONES = DIR_DATOS / "simulations"
DIR_VISTA = RAIZ / "src" / "view"

# En Vercel (funciones sin servidor) el disco es de solo lectura salvo /tmp y cada
# petición puede caer en otra instancia: no hay trabajos en segundo plano compartidos.
SERVERLESS = os.environ.get("VERCEL") == "1"

VERSION_APP = "0.3.0"
VERSION_MODELO = "pms-browniano-0.3.0"

# Malla nativa de dirmarea.txt: 0.16°, lon −98.00…−83.12, lat 15…23. El modelo usa el
# recuadro de Yucatán alineado a esa malla: 51 × 39 = 1 989 nodos (sin interpolar mallas).
RESOLUCION_GRADOS = 0.16
LON_MIN, LON_MAX = -92.08, -84.08
LAT_MIN, LAT_MAX = 16.92, 23.0

HORIZONTE_H = 120               # 5 días
PASO_SEGUNDOS = 3600.0          # Δt = 1 h
PASO_OLEAJE_H = 3               # dirmarea.txt: +0, +3, …, +120 h
RADIO_TIERRA_M = 6_371_000.0

# Único archivo de entrada (separador ";", relleno −9.99e+08)
ARCHIVO_OLEAJE = "dirmarea.txt"
COLUMNAS_OLEAJE = ("LON", "LAT", "dirolavto", "alturaolavto")
VALOR_RELLENO = -9.99e8
UMBRAL_RELLENO = -1.0e8         # todo valor menor se trata como relleno (sin dato)

# ---------------------------------------------------------------------------
# Deriva de Stokes de la ola de viento (modelo pms-browniano-0.3.0)
#
#   |u_s| = γ · 2π³·H² / (g·T³)      en la dirección HACIA donde viaja la ola
#
# SUPUESTO: dirmarea.txt no trae período de ola, así que se estima T = 4.0·√H (s, H en m),
# una relación empírica aproximada para mar de viento en desarrollo. Con H = 1.25 m da
# T ≈ 4.5 s y |u_s| ≈ 0.11 m/s. γ (0–3, por defecto 1) escala la deriva para calibrarla.
# ---------------------------------------------------------------------------
GRAVEDAD = 9.81
COEF_PERIODO = 4.0              # T = COEF_PERIODO · √H
GAMMA_DEFECTO, GAMMA_MIN, GAMMA_MAX = 1.0, 0.0, 3.0
KH_DEFECTO = 10.0               # m²/s, intensidad del movimiento browniano
COEF_STOKES = 2 * math.pi ** 3 / (GRAVEDAD * COEF_PERIODO ** 3)   # |u_s| = γ · COEF_STOKES · √H

# Hora local de Cancún: UTC−5 todo el año (Quintana Roo no aplica horario de verano).
DESFASE_CANCUN_H = -5
