# Datos de SEMAR (no versionados)

Los archivos de esta carpeta son datos de la Secretaría de Marina (SEMAR) entregados al
equipo como muestra. **No tenemos permiso para publicarlos**, por eso están en
`.gitignore` y no se suben a GitHub. Para correr PMS, copia aquí:

| Archivo | Contenido | Obligatorio |
|---|---|---|
| `salidadatos.txt` | Viento (U, V, WindsfcSp, WindsfcDir) y direcciones de oleaje (sfcPrimWaDir, sfcDirWindWa) en una malla de 0.16°, 301 × 201 nodos (lon −124…−76, lat 39…7). Una sola hora: `19AUG2026 00` | Sí |
| `dirmarea.txt` | Oleaje de viento (dirección `dirolavto`, altura `alturaolavto`) en 41 bloques horarios (+0 … +120 h cada 3 h), malla 94 × 51 de 0.16° desplazada 0.08° en longitud | No (sin él no hay oleaje en el hover) |
| `corrientes/*.txt` | Corriente superficial `LON;LAT;UO;VO` (m/s, hacia donde fluye). **Aún no existe**: queda preparado para CMEMS/HYCOM | No (sin ella, u_c = 0) |

Formato común: separador `;`, primera línea con los nombres de columna, una línea de
fecha `DDMMMAAAA HH [h]` (mes en inglés) al inicio de cada bloque y `-9.99e+08` como valor
de relleno (sin dato, normalmente tierra).

Al levantar la app (`python main.py`) el validador revisa ambos archivos y reporta
cualquier problema con la causa, el archivo y la acción sugerida.
