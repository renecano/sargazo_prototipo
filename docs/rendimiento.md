# Rendimiento medido

Medido con `python scripts/medir_rendimiento.py` el 2026-10-07 18:23 en Windows 11, Python 3.14.0, NumPy 2.5.3, procesador `Intel64 Family 6 Model 142 Stepping 12, GenuineIntel`, 7.8 GB de RAM, 0.8 GB libres al medir. Mediana y máximo de 3 repeticiones; memoria = pico asignado por Python medido con tracemalloc en una corrida aparte (no incluye el intérprete).

| Operación | Mediana | Máximo | Memoria / tamaño |
|---|---|---|---|
| Validar 120 archivos + corrientes | 3.38 s | 3.53 s | 27 MB |
| Simular 500 partículas × 120 h | 1.30 s | 1.45 s | 1 MB |
| Simular 2 000 partículas × 120 h | 0.97 s | 1.00 s | 4 MB |
| Métricas + registro JSON (2 000 partículas) | 0.19 s | — | 1.3 MB en disco |
| Simular 5 000 partículas × 120 h | 2.84 s | 2.89 s | 11 MB |
| Métricas + registro JSON (5 000 partículas) | 0.24 s | — | 3.1 MB en disco |
| Campos para la interfaz (JSON) | — | — | 1.8 MB; 0.7 MB con gzip |

Notas:

- Conjunto: 1989 nodos × 120 horas (sintético).
- La simulación incluye la prueba de tierra por segmento y la búsqueda binaria del punto de varamiento.
- La interfaz descarga los campos una sola vez por conjunto; la API los comprime con gzip.
- Los tiempos varían con la carga del equipo: con poca RAM libre todo se vuelve más lento.
