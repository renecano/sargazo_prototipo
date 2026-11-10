# Rendimiento medido

Medido con `python scripts/medir_rendimiento.py` el 2026-11-09 20:16 en Windows 11, Python 3.14.0, NumPy 2.5.3, procesador `Intel64 Family 6 Model 142 Stepping 12, GenuineIntel`, 7.8 GB de RAM, 2.3 GB libres al medir. Mediana y máximo de 3 repeticiones; memoria = pico asignado por Python medido con tracemalloc en una corrida aparte (no incluye el intérprete).

| Operación | Mediana | Máximo | Memoria / tamaño |
|---|---|---|---|
| Validar dirmarea.txt (lectura de 196 554 filas y 8 verificaciones) | 0.30 s | 0.30 s | 33 MB |
| Cargar la máscara de costa (8 240 × 6 320 celdas de 0.001°) | 0.01 s | — | 6.2 MB en memoria; 86 KB en disco |
| Simular 500 partículas × 120 h frente a Cancún | 0.14 s | 0.16 s | 1 MB |
| Simular 2 000 partículas × 120 h frente a Cancún | 0.21 s | 0.22 s | 4 MB |
| Simular 5 000 partículas × 120 h frente a Cancún | 0.37 s | 0.46 s | 11 MB |
| Simular 500 partículas × 120 h en mar abierto | 0.31 s | 0.31 s | 1 MB |
| Simular 2 000 partículas × 120 h en mar abierto | 0.53 s | 0.54 s | 4 MB |
| Simular 5 000 partículas × 120 h en mar abierto | 0.96 s | 0.98 s | 11 MB |
| Métricas + registro JSON (2 000 partículas) | 0.09 s | — | 1.3 MB en disco |
| Campos de oleaje para la interfaz (41 bloques) | — | — | 0.52 MB; 0.01 MB con gzip |
| Máscara de costa para la interfaz | — | — | 6.2 MB; 63 KB con gzip |

Notas:

- Datos: dirmarea.txt, 1989 nodos en el dominio (1295 con ola), 41 bloques idénticos; modelo pms-browniano-0.4.0.
- Frente a Cancún (21.12° N, 86.66° O) la ola empuja hacia la costa: el 100 % de las partículas vara entre la hora 8 y la 70 (mediana 35) y las varadas dejan de calcularse; por eso esa simulación es más barata que la de mar abierto.
- La costa de ~105 m se revisa cada media celda en cada paso (entre 4 y unas decenas de consultas por partícula y hora): por eso simular cuesta más que en la v0.4.0, que revisaba 4 puntos contra una costa de 440 m.
- La interfaz descarga los campos de oleaje una sola vez al abrir; la API los comprime con gzip (los 41 bloques idénticos se comprimen casi por completo).
- Los tiempos varían con la carga del equipo: con poca RAM libre todo se vuelve más lento.

## Interfaz en el navegador

Medido en chromium 157.0.4341.42 sin interfaz gráfica, ventana de 1366 × 768, con el mapa base «carta» (no usa internet), oleaje animado, estelas, densidad y localidades encendidos, reproduciendo a 6 h/s durante 6 s. El freno de procesador es el de las herramientas de desarrollo de Chromium (Emulation.setCPUThrottlingRate): 4× equivale aproximadamente a un equipo de gama baja y 6× a uno muy modesto.

| Operación | Resultado | Peor caso | Detalle |
|---|---|---|---|
| Abrir la página hasta «Listo» (carta, costa, localidades y oleaje) | 2.1 s | — | 31 respuestas, 0.25 MB transferidos |
| Reproducir 2 000 partículas con estelas y oleaje animado  a velocidad real | 31 cuadros/s | 117 ms el cuadro más lento | estela en 2 tramos al terminar; JavaScript: partículas 5.1 ms y oleaje 0.3 ms por cuadro (510 trazos); memoria de JS 22 MB |
| Reproducir 2 000 partículas con estelas y oleaje animado  con el procesador frenado 4× | 23 cuadros/s | 100 ms el cuadro más lento | estela en 1 tramos al terminar; JavaScript: partículas 27.9 ms y oleaje 2.0 ms por cuadro (510 trazos); memoria de JS 21 MB |
| Reproducir 2 000 partículas con estelas y oleaje animado  con el procesador frenado 6× | 15 cuadros/s | 117 ms el cuadro más lento | estela en 1 tramos al terminar; JavaScript: partículas 26.1 ms y oleaje 2.0 ms por cuadro (510 trazos); memoria de JS 19 MB |
| Reproducir 5 000 partículas con estelas y oleaje animado  a velocidad real | 17 cuadros/s | 100 ms el cuadro más lento | estela en 1 tramos al terminar; JavaScript: partículas 7.5 ms y oleaje 0.2 ms por cuadro (510 trazos); memoria de JS 30 MB |
| Reproducir 5 000 partículas con estelas y oleaje animado  con el procesador frenado 4× | 12 cuadros/s | 133 ms el cuadro más lento | estela en 1 tramos al terminar; JavaScript: partículas 39.1 ms y oleaje 2.4 ms por cuadro (510 trazos); memoria de JS 31 MB |
| Reproducir 5 000 partículas con estelas y oleaje animado  con el procesador frenado 6× | 8 cuadros/s | 300 ms el cuadro más lento | estela en 1 tramos al terminar; JavaScript: partículas 121.3 ms y oleaje 2.4 ms por cuadro (510 trazos); memoria de JS 37 MB |

Notas:

- Las estelas bajan de detalle solas cuando el equipo no alcanza: cada una se parte en 6, 3, 2 o 1 tramos de opacidad según el tiempo entre cuadros (más de 45 ms baja un nivel; menos de 20 ms sostenidos, sube). En pausa siempre se dibujan completas. Los anillos de las varadas se estampan desde una imagen ya pintada.
- El costo de JavaScript por cuadro es pequeño (columna de detalle); lo que limita los cuadros por segundo es el trazado del lienzo, que en este navegador sin interfaz gráfica se hace sin tarjeta de video.
- El oleaje animado se limita a 30 cuadros por segundo y a 900 trazos, y se detiene con la pestaña oculta, con su interruptor o con la preferencia del sistema de reducir el movimiento.
- La carta propia se pinta por teselas una sola vez por nivel de zoom; la máscara de costa ocupa 6.5 MB en la memoria del navegador.
- Con poca RAM libre el navegador sin interfaz gráfica entrega menos cuadros que uno normal: estos números son un piso.
