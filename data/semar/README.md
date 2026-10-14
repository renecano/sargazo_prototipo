# Datos de SEMAR

Los archivos de esta carpeta son datos de la Secretaría de Marina (SEMAR) entregados al
equipo como muestra. Se versionan en este repositorio **privado** para que la app y su
despliegue los encuentren; **no deben redistribuirse** fuera del equipo sin autorización de
SEMAR. Si el repositorio vuelve a ser público, hay que sacarlos antes (también del
historial). `.gitattributes` los guarda byte a byte para que su huella SHA-256 no cambie.

Archivos esperados:

| Archivo | Contenido | Obligatorio |
|---|---|---|
| `salidadatos.txt` | Viento (U, V, WindsfcSp, WindsfcDir) y direcciones de oleaje (sfcPrimWaDir, sfcDirWindWa) en una malla de 0.16°, 301 × 201 nodos (lon −124…−76, lat 39…7). Una sola hora: `19AUG2026 00` | Sí |
| `dirmarea.txt` | Oleaje de viento (dirección `dirolavto`, altura `alturaolavto`) en 41 bloques horarios (+0 … +120 h cada 3 h), malla 94 × 51 de 0.16° desplazada 0.08° en longitud | No (sin él no hay oleaje en el hover) |
| `corrientes/*.txt` | Corriente superficial `LON;LAT;UO;VO` (m/s, hacia donde fluye). **Aún no existe**: queda preparado para CMEMS/HYCOM | No (sin ella, u_c = 0) |

Formato común: separador `;`, primera línea con los nombres de columna, una línea de
fecha `DDMMMAAAA HH [h]` (mes en inglés) al inicio de cada bloque y `-9.99e+08` como valor
de relleno (sin dato, normalmente tierra).

Para usar otros archivos, reemplázalos aquí o apunta la app a otra carpeta con
`python main.py --datos <carpeta>`. Al levantar la app el validador revisa ambos archivos y reporta
cualquier problema con la causa, el archivo y la acción sugerida.
