# Manual de pruebas de PMS v0.5.0

Cómo comprobar, a mano y con las pruebas automáticas, que cada observación de SEMAR quedó
resuelta. Sirve para revisar una instalación nueva o un despliegue.

## Antes de empezar

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium      # solo si no hay Microsoft Edge
python main.py                             # http://localhost:8000
```

Para probar un servidor ya desplegado, usa su dirección en lugar de `localhost:8000`.

## Pruebas automáticas

| Comando | Qué corre | Duración aproximada |
|---|---|---|
| `python -m pytest` | 209 pruebas rápidas: lector, validador, modelo, costa, interpolación, API y validación | 1 min |
| `python -m pytest -m e2e` | 35 pruebas de interfaz con un navegador real | 3 min |
| `python -m pytest -m e2e --url-base https://pms-sargazo.vercel.app` | Las de interfaz contra un servidor desplegado (omite las que necesitan datos propios) | 3 min |
| `python scripts/medir_rendimiento.py` | Tiempos del servidor y cuadros por segundo de la interfaz → `docs/rendimiento.md` | 3 min |
| `python scripts/capturar_pantalla.py` | Capturas de `docs/` en 1366×768 y 1920×1080 | 2 min |

Todas deben terminar sin fallas. Contra un servidor externo las simulaciones de prueba quedan
en su historial.

## Revisión manual, observación por observación

Usa una ventana de al menos 1366×768. Si se abre el recorrido guiado, ciérralo con «Saltar
recorrido» (se prueba aparte, al final).

### 1. Tierra y mar

| Paso | Qué debe verse |
|---|---|
| Acerca el mapa a Cancún e Isla Mujeres (zoom máximo) | La carta dibuja la zona hotelera, Isla Mujeres y la Bahía de Mujeres entre ambas, como mar |
| Clic en la Bahía de Mujeres (21.188° N, 86.768° O) | El punto se acepta: no aparece «El punto está en tierra» |
| Clic sobre Isla Mujeres | Aparece «El punto está en tierra. Elige un punto en el mar.» |
| Clic frente a Cancún, «Continuar a Ajustes», «Simular» | Los anillos rojos quedan sobre la línea de costa, ninguno en medio del mar |
| «Mapa y capas» → Satélite | Los anillos siguen sobre la playa de la imagen; ninguna partícula sobre tierra |
| Reproduce a 24 h/s y pausa varias veces | Ninguna partícula a flote aparece sobre tierra, tampoco entre horas |
| Clic al este de Cozumel (20.40° N, 86.60° O) y simula 72 h | La tabla de arribos dice «Cozumel»; nada llega al continente |

Automático: `tests/test_costa.py` y, en `tests/e2e`, `test_la_carta_propia…`,
`test_la_interfaz_y_el_modelo_usan_la_misma_mascara` y `test_ninguna_particula_se_dibuja_sobre_tierra…`.

### 2. Interpolación

| Paso | Qué debe verse |
|---|---|
| Pasa el cursor por el mar | La altura y la dirección de la ola cambian de forma continua, sin saltos entre nodos |
| Pasa el cursor a menos de 2 km de la costa de Playa del Carmen | Hay ola, con la nota «extendida a la costa» |
| Compara un punto con el modelo: abre `/api/ola?lon=-86.30&lat=21.00&hora=0` | La altura y la dirección coinciden con las del cursor en ese punto |
| Reproduce a 3 h/s | Las partículas avanzan sin saltos |

Automático: `tests/test_interpolacion.py` y, en `tests/e2e`,
`test_con_bloques_distintos_el_oleaje_cambia_con_la_hora_y_coincide_con_el_modelo`.

Para ver el oleaje cambiar con la hora hace falta un archivo con bloques distintos:

```powershell
python -c "from scripts.generar_fixtures import crear_fixture; crear_fixture('tmp/variable', completo=True, identicos=False)"
python main.py --datos tmp\variable --puerto 8001
```

Con ese archivo la leyenda dice «Oleaje del pronóstico: bloque +N h» y el oleaje cambia al
mover la línea de tiempo. Sus valores son sintéticos.

### 3. Oleaje en movimiento

| Paso | Qué debe verse |
|---|---|
| Al abrir | Trazos que fluyen hacia el ONO frente a Cancún; más largos y más rápidos mar adentro, donde la ola es más alta |
| Leyenda | «Oleaje constante: los 41 bloques del archivo son idénticos.» |
| «Mapa y capas» → desmarca «Animado» | Quedan flechas fijas, una por nodo con dato |
| Desmarca «Oleaje» | Desaparecen las flechas y la referencia «ola de 1 m» |
| Activa «reducir movimiento» en el sistema y recarga | El oleaje arranca fijo y el panel lo explica |

### 4. Movimiento no uniforme

| Paso | Qué debe verse |
|---|---|
| Con una simulación, acerca el mapa a las partículas | Cada una deja una estela púrpura; hay estelas cortas y claras, y largas y oscuras (sobre el satélite, rosas: las largas son las más claras) |
| Mueve la línea de tiempo | «Conglomerado» cambia: nudos, km/h y rumbo |
| Pausa y pasa el cursor sobre una partícula | «Partícula N · 0.29 kn · 0.53 km/h · rumbo 327° (NNO)» |
| Reproduce | El dato de la partícula desaparece mientras se mueve |

### 5. Escalas

| Paso | Qué debe verse |
|---|---|
| Acerca y aleja el mapa | La barra doble cambia de valor y de largo: km arriba, MN abajo, siempre en números redondos |
| Mide con la barra el círculo punteado (radio 5 km) | El diámetro es de 10 km en cualquier zoom |
| Compara una flecha de oleaje con «ola de 1 m» | Donde la ola es de ~1 m (pasa el cursor), el trazo mide lo mismo que la referencia, en cualquier zoom |
| Leyenda con una simulación | Cuatro clases de densidad: 0.2–1, 1–5, 5–20 y ≥ 20 % del sargazo liberado por celda de 0.04° |
| Mira la densidad y la zona con el 90 % en los tres mapas base | Manchas púrpura translúcidas de bordes suaves, con trama diagonal y sin bloques rectangulares ni borde grueso; no se pintan sobre tierra. La zona es una línea fina. Nada se confunde con la tierra ni con el mar |
| Suelta el conglomerado en 21.40° N, 86.65° O, simula y acerca el mapa al norte de Cancún (zooms 9 a 11) | La barra de Isla Blanca e Isla Contoy se ven como tierra; cada anillo rojo queda sobre tierra dibujada |
| Línea de tiempo | «Hora N de 120», fecha en UTC y en hora de Quintana Roo (5 horas menos), una marca por día |
| Botones −6 h y +6 h; cambia «Salto» a 3 y a 12 | Saltan lo que dicen; no pasan de 0 ni de 120 |
| Cambia «Velocidad» a 24 h/s | La reproducción va cuatro veces más rápido que a 6 h/s |
| Paso 1 | Bajo latitud y longitud aparece el punto en grados y minutos |
| Paso 3 y «Ver detalle» | Distancias en km y MN, rapidez en nudos y km/h |

### 6. Información geográfica

| Paso | Qué debe verse |
|---|---|
| Vista completa | Mérida, Cancún, Chetumal, Campeche y otras ciudades, sin encimarse |
| Acerca a Quintana Roo | Aparecen Isla Mujeres, Puerto Morelos, Playa del Carmen, San Miguel de Cozumel, Tulum |
| Acerca más | Poblados menores, islas y canales en cursiva |
| Sur de Quintana Roo | Mahahual, Chetumal, Banco Chinchorro |
| «Mapa y capas» → Satélite y Calles | Cambia el fondo; abajo a la derecha cambia la atribución |
| Desmarca «Localidades y puertos» | Los rótulos desaparecen |

### 7. Interfaz limpia

| Paso | Qué debe verse |
|---|---|
| Al abrir | Solo la cabecera, la hoja del paso 1, la línea de tiempo y la leyenda con las escalas |
| Paso 3 | El titular, la tabla de arribos, «Ver detalle» y dos botones para exportar |
| «Ver detalle» del resultado y de la leyenda | Ahí están las cifras secundarias, los símbolos explicados y las fuentes |
| Pie de la leyenda | El aviso de límites y el enlace «Validación contra satélite», en letra pequeña |

### Tabla de arribos y exportación

| Paso | Qué debe verse |
|---|---|
| Paso 3 | Una fila por tramo, de la que llega primero a la última: fecha y hora, porcentaje y distancia |
| Toca una fila | El mapa va a ese tramo y la línea de tiempo a la hora del primer arribo; la fila queda marcada |
| «Guardar imagen del mapa» | Se descarga un PNG con el mapa, la fecha, las escalas y las fuentes |
| «Resumen de una página» | Se abre el diálogo de impresión con una hoja: parámetros, mapa, tabla de arribos, escalas y límites |

### Recorrido guiado

Borra `pms.recorrido.visto.v4` del almacenamiento local (o usa una ventana privada) y recarga.
Debe abrirse solo, tener 14 pasos, esperar el clic en el mar (paso 4) y la simulación (paso 7),
iluminar el elemento del que habla en cada paso y cerrarse con «Terminar» o con Esc.

## Después de desplegar

```powershell
curl -s https://pms-sargazo.vercel.app/api/salud
python -m pytest -m e2e --url-base https://pms-sargazo.vercel.app
```

`/api/salud` debe responder `"estado":"ok"`, `"version_app":"0.5.0"`,
`"version_modelo":"pms-browniano-0.4.0"` y `"datos_disponibles":true`.
