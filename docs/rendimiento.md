# Rendimiento medido

Medido con `python scripts/medir_rendimiento.py` el 2026-10-30 20:23 en Windows 11, Python 3.14.0, NumPy 2.5.3, procesador `Intel64 Family 6 Model 142 Stepping 12, GenuineIntel`, 7.8 GB de RAM, 1.7 GB libres al medir. Mediana y máximo de 3 repeticiones; memoria = pico asignado por Python medido con tracemalloc en una corrida aparte (no incluye el intérprete).

| Operación | Mediana | Máximo | Memoria / tamaño |
|---|---|---|---|
| Validar dirmarea.txt (lectura de 196 554 filas y 8 verificaciones) | 0.26 s | 0.35 s | 33 MB |
| Simular 500 partículas × 120 h frente a Cancún | 0.09 s | 0.11 s | 1 MB |
| Simular 2 000 partículas × 120 h frente a Cancún | 0.13 s | 0.13 s | 4 MB |
| Simular 5 000 partículas × 120 h frente a Cancún | 0.20 s | 0.20 s | 11 MB |
| Simular 500 partículas × 120 h en mar abierto | 0.17 s | 0.17 s | 1 MB |
| Simular 2 000 partículas × 120 h en mar abierto | 0.33 s | 0.34 s | 4 MB |
| Simular 5 000 partículas × 120 h en mar abierto | 0.62 s | 0.62 s | 11 MB |
| Métricas + registro JSON (2 000 partículas) | 0.06 s | — | 1.3 MB en disco |
| Campos de oleaje para la interfaz (41 bloques) | — | — | 0.42 MB; 0.01 MB con gzip |

Notas:

- Datos: dirmarea.txt, 1989 nodos en el dominio (1295 con ola), 41 bloques idénticos; modelo pms-browniano-0.3.0.
- Frente a Cancún (21.12° N, 86.66° O) la ola empuja hacia la costa: todas las partículas varan entre +8 h y +61 h (mediana +27 h) y las varadas dejan de calcularse; por eso esa simulación es más barata que la de mar abierto.
- La interfaz descarga los campos de oleaje una sola vez al abrir; la API los comprime con gzip (los 41 bloques idénticos se comprimen casi por completo).
- Los tiempos varían con la carga del equipo: con poca RAM libre todo se vuelve más lento.
