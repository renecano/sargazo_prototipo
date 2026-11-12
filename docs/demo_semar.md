# Demo para SEMAR: PMS v0.5.0 en 3 minutos

Guion para mostrar, en orden, cada observación de SEMAR ya resuelta. Los tiempos son una
guía; lo que se dice va entre comillas.

## Antes de entrar

- Abre <https://pms-sargazo.vercel.app> en una ventana de 1366×768 o más y cierra el
  recorrido con «Saltar recorrido». Deja la página en el paso 1, con la vista completa.
- En «Velocidad» deja 6 h/s y en «Salto», 6 h.
- Ten a la mano el punto de prueba: latitud **21.120**, longitud **−86.660** (es el que trae
  por defecto).
- Si no hay internet, la carta, el oleaje y la simulación funcionan igual; solo fallan el
  satélite, las calles y las tipografías.

## Guion

| Tiempo | Observación | Qué hacer | Qué decir |
|---|---|---|---|
| 0:00 | Apertura | Nada: deja ver la carta con el oleaje fluyendo | «Tomamos sus siete observaciones. Esta es la versión 0.5. Lo primero que cambió es lo que ven: el mar se mueve.» |
| 0:15 | 3. Oleaje en movimiento | Señala los trazos y la leyenda | «Cada trazo viaja hacia donde va la ola; es más largo y corre más donde la ola es más alta.» |
| 0:30 | 6. Geografía | Acerca el mapa a Cancún con la rueda | «Ya hay ciudades y puertos; aparecen al acercar y no se enciman. El rombo marca los que tienen puerto.» |
| 0:45 | 1. Tierra y mar | Con el zoom cerca, señala la Bahía de Mujeres | «El error de contacto con tierra venía de una costa dibujada a mano, de 92 puntos. Aquí, entre Cancún e Isla Mujeres, el modelo creía que había tierra. Ahora la costa es la de OpenStreetMap, a 100 metros, y la que dibuja la carta es la misma que usa el modelo.» |
| 1:00 | Simular | «Continuar a Ajustes» y «Simular» | «Soltamos 2 000 partículas frente a Cancún, a 120 horas.» |
| 1:10 | 4. Movimiento no uniforme | Deja correr unos segundos y pausa con la barra espaciadora; pasa el cursor sobre una partícula | «Cada partícula deja una estela: más larga y de tono más intenso, más rápida. Abajo, la rapidez del conglomerado en nudos y kilómetros por hora cambia con la hora. Y en pausa cada partícula dice su rapidez y su rumbo.» |
| 1:30 | 1. Tierra y mar | «Mapa y capas» → Satélite; vuelve a Carta | «Sobre la imagen de satélite los anillos rojos quedan en la playa, no en el mar. Y ninguna partícula cruza tierra.» |
| 1:45 | 5. Escalas | Señala la leyenda; acerca y aleja una vez | «La escala está en kilómetros y en millas náuticas y sigue al zoom. La flecha de ola de un metro mide lo mismo en cualquier zoom. La densidad tiene unidad: porcentaje del sargazo por celda de unos 4 kilómetros.» |
| 2:00 | 5. Línea de tiempo | Pulsa +6 h dos veces; señala las fechas | «La línea de tiempo dice la hora del pronóstico, la fecha en UTC y la hora de Quintana Roo, con una marca por día, saltos de 3, 6 y 12 horas y velocidad.» |
| 2:15 | Tabla de arribos | Señala la tabla del paso 3 y toca la última fila | «Este es el resultado principal: para cada tramo de costa, cuándo llega lo primero, cuánto llega y cuánto recorre, en kilómetros y millas náuticas. Toco un tramo y el mapa va a ese lugar y a esa hora.» |
| 2:30 | 7. Interfaz limpia | Abre y cierra «Ver detalle» | «A la vista solo queda lo esencial. Lo demás está en Ver detalle: parámetros y horas en UTC.» |
| 2:40 | Exportar | «Resumen de una página» (cancela la impresión) | «Y se lleva: una hoja con la fecha, los parámetros, la tabla de arribos y las escalas, o la imagen del mapa.» |
| 2:50 | 2. Interpolación y cierre | Abre «Acerca del modelo» y señala el enlace «Validación contra satélite» | «Revisamos las tres interpolaciones. Encontramos y corregimos una franja de mar junto a la costa donde las partículas se quedaban sin oleaje. Y seguimos midiendo el modelo contra el satélite: hoy, solo con oleaje, todavía no le gana a suponer que el sargazo no se mueve. Eso está publicado aquí.» |

## Si preguntan

| Pregunta | Respuesta corta |
|---|---|
| ¿Por qué marcaba tierra donde no había? | La costa del modelo era un polígono manual. Frente a Cancún, 4 de cada 10 partículas «varadas» quedaban a más de 1 km de tierra, hasta 3.8 km. |
| ¿De dónde sale la costa nueva? | De la línea de costa de OpenStreetMap, en celdas de unos 105 m. Coincide con otra fuente independiente (GSHHG) al 0.2 % en superficie de tierra. |
| ¿Qué no resuelve? | Canales de menos de ~200 m (la laguna Nichupté cuenta como tierra) y no distingue playa de manglar o arrecife. |
| ¿Cambiaron los resultados? | Sí. En el canal de Cozumel el varado pasa de 18 % a 99.5 % y frente a Sian Ka'an de 59 % a 99.7 %, porque antes las partículas se atoraban sin oleaje junto a la costa. Frente a Cancún, a 30 km, baja de 94 % a 77 %. |
| ¿Qué es «primer arribo»? | La hora en que la primera de las partículas simuladas toca ese tramo. Es una estimación del modelo, no una certeza. |
| ¿Los tramos son oficiales? | No, son una convención nuestra por latitud y longitud. Podemos ajustarlos a los que use SEMAR. |
| ¿El oleaje cambia con la hora? | El modelo y la interfaz ya interpolan entre bloques de 3 h; el archivo de muestra trae los 41 bloques iguales. |
| ¿Funciona sin internet? | La carta, el oleaje, la simulación y la exportación, sí. El satélite, las calles y las tipografías necesitan internet. |
| ¿La validación ya es con esta versión? | Todavía no: la publicada es con la versión anterior. Falta repetirla con la costa nueva. |
| ¿Qué falta para que sirva de pronóstico? | Viento y corrientes, un pronóstico de oleaje que cambie en el tiempo y ganarle a la persistencia en la validación. |

## Lo que no hay que decir

- Que el modelo predice arribos: es probabilístico y solo usa oleaje.
- Que la validación respalda esta versión: se hizo con la anterior.
- Que la rapidez de una partícula es la de la corriente: incluye la dispersión aleatoria.
