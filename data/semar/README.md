# Datos de SEMAR

El único archivo de entrada de PMS es `dirmarea.txt`, oleaje de viento entregado por la
Secretaría de Marina (SEMAR) como muestra. Se versiona en este repositorio para que la app y
su despliegue lo encuentren. **El repositorio es público**, así que el archivo también lo es:
hay que confirmar con SEMAR que autoriza su difusión; si no, hay que retirarlo del
repositorio y también del historial. `.gitattributes` lo guarda byte a byte para que su huella SHA-256
no cambie.

| Archivo | Contenido |
|---|---|
| `dirmarea.txt` | `LON;LAT;dirolavto;alturaolavto`: dirección DESDE la que viene la ola de viento (grados, 0 = norte) y su altura (m). 41 bloques `01OCT2026 00 h` con h = 0, 3, …, 120; cada uno con 4 794 filas: malla 94 × 51 de 0.16°, lon −98.00…−83.12, lat 23…15 (de norte a sur). |

Formato: separador `;`, primera línea con los nombres de columna, una línea de fecha
`DDMMMAAAA HH h` (mes en inglés) al inicio de cada bloque y `-9.99e+08` como valor de
relleno (sin dato, tierra).

Los 41 bloques del archivo de muestra son idénticos byte por byte: el validador lo reporta
como advertencia. El modelo interpola entre bloques cada 3 h, así que funcionará igual
cuando lleguen datos que sí cambien en el tiempo.

Para usar otro archivo, reemplázalo aquí o apunta la app a otra carpeta con
`python main.py --datos <carpeta>`. Al levantar la app el validador revisa el archivo y
reporta cualquier problema con la causa, el archivo y la acción sugerida.
