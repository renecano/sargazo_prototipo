# ⚠️ Datos SINTÉTICOS — no son datos de SEMAR

Esta carpeta contiene el conjunto de demostración del prototipo PMS. **Ningún valor
proviene de SEMAR, CMEMS, HYCOM ni de otra fuente operativa.** Todo se genera con
funciones analíticas en `scripts/generar_datos_demo.py`.

## Por qué existen

- El formato oficial de los archivos de SEMAR **aún no está confirmado**, y la fuente de
  corrientes (CMEMS o HYCOM) tampoco.
- Necesitamos mostrar la aplicación de punta a punta (validación → simulación →
  animación → historial) al equipo y a SEMAR sin esperar esos datos.
- Usar el mismo esquema de columnas que el archivo de SEMAR analizado
  (`salidadatos.txt`) obliga a que la ingesta y el validador ya funcionen con esa forma.

## Cómo se generan

```powershell
python scripts/generar_datos_demo.py
```

Crea (y no se versionan en git, por eso solo verás este README hasta que lo ejecutes):

| Ruta | Contenido |
|---|---|
| `salidadatos_AAAAMMDDHH.txt` × 120 | Una hora cada uno, del 2026-10-01 00 UTC al 2026-10-05 23 UTC |
| `corrientes/corrientes_esquematicas.txt` | Corriente superficial estacionaria, esquemática |
| `../demo_errores/` | Copia con 3 errores sembrados (archivo faltante, LAT = 95, columna ausente) |

## Esquema

Malla de **0.16°** alineada con la del archivo de SEMAR (124°W–76°W, 7°N–39°N),
recortada a lon −92.00…−84.00 y lat 16.92…23.00: 51 × 39 = 1 989 nodos, de los cuales
1 323 son mar según la costa aproximada del modelo.

| Columna | Unidad | Significado |
|---|---|---|
| `LON`, `LAT` | grados | Nodo de malla (oeste negativo) |
| `U`, `V` | m/s | Componentes del viento hacia el este y el norte |
| `WindsfcSp` | m/s | Velocidad del viento superficial |
| `WindsfcDir` | grados | Dirección **desde** la que sopla (0° = del norte) |
| `sfcPrimWaDir` | grados | Dirección primaria del oleaje (desde); `nan` en tierra |
| `sfcDirWindWa` | grados | Dirección del oleaje de viento (desde); `nan` en tierra |

Corrientes: `LON LAT UO VO` en m/s, convención oceanográfica (hacia donde fluye el agua).

## Qué representan (de forma esquemática)

- **Viento:** alisios del E/SE (~105°) de ~5.4 m/s de media, con ciclo diurno, un giro
  lento de ±15° y un evento de viento del NE más intenso entre las horas +78 y +108.
  Sobre tierra se debilita. Rango aproximado 1–11 m/s.
- **Corriente:** Corriente de Yucatán como un chorro hacia el norte (máx. ~1.5 m/s)
  entre Cancún/Cozumel y Cuba; flujo débil del Caribe hacia el O-NO al sur de 21°N;
  deriva débil hacia el oeste en el Banco de Campeche; se debilita cerca de la costa y
  es cero sobre tierra. **No varía en el tiempo.**

Estos campos sirven para probar el software, no para tomar decisiones.
