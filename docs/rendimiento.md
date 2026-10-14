# Rendimiento medido

Medido con `python scripts/medir_rendimiento.py` el 2026-10-14 09:59 en Windows 11, Python 3.14.0, NumPy 2.5.3, procesador `Intel64 Family 6 Model 142 Stepping 12, GenuineIntel`, 7.8 GB de RAM, 1.3 GB libres al medir. Mediana y máximo de 3 repeticiones; memoria = pico asignado por Python medido con tracemalloc en una corrida aparte (no incluye el intérprete).

| Operación | Mediana | Máximo | Memoria / tamaño |
|---|---|---|---|
| Validar salidadatos.txt + dirmarea.txt (lectura, 10 verificaciones, interpolación del oleaje) | 0.38 s | 0.47 s | 43 MB |
| Simular 500 partículas × 120 h frente a Cancún | 0.14 s | 0.15 s | 1 MB |
| Simular 2 000 partículas × 120 h frente a Cancún | 0.21 s | 0.21 s | 4 MB |
| Métricas + registro JSON (2 000 partículas) | 0.09 s | — | 1.3 MB en disco |
| Simular 5 000 partículas × 120 h frente a Cancún | 0.30 s | 0.31 s | 11 MB |
| Métricas + registro JSON (5 000 partículas) | 0.18 s | — | 3.1 MB en disco |
| Campos para la interfaz (viento + 41 horas de oleaje) | — | — | 0.43 MB; 0.01 MB con gzip |

Notas:

- Datos de SEMAR: 1989 nodos en el dominio (1314 con viento), viento de una sola hora y 41 bloques de oleaje.
- La simulación incluye la prueba de tierra por segmento y la búsqueda binaria del punto de varamiento.
- Las partículas varadas dejan de calcularse; frente a Cancún varan de forma gradual (mediana +64 h), así que el costo baja a lo largo de la simulación.
- La interfaz descarga los campos una sola vez al abrir; la API los comprime con gzip (los 41 bloques de oleaje idénticos se comprimen casi por completo).
- Los tiempos varían con la carga del equipo: con poca RAM libre todo se vuelve más lento.
