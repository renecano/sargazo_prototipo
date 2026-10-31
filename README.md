# PMS · Predicción de Movimiento del Sargazo

**v0.3.0 · demo en línea: <https://pms-sargazo.vercel.app>**

PMS estima hacia dónde podría derivar un conglomerado de sargazo frente a la Península de
Yucatán durante los próximos 5 días (120 h). Lo hace con un **modelo de partículas
brownianas** que mueve cada partícula con la **deriva de Stokes de la ola de viento** de
SEMAR más un movimiento aleatorio. El resultado es una **probabilidad**, no una certeza: el
archivo de oleaje es de muestra, el modelo no incluye viento ni corrientes y sus
parámetros no están calibrados.

![PMS: resultado de 120 h frente a Cancún, pausado en +12 h, con el hover de la ola](docs/captura_resultado.png)

*Interfaz «carta náutica» en 1366×768: tres pasos (punto de liberación → ajustes →
resultado), flechas fijas de oleaje, partículas a flote y varadas, trayectoria central,
contorno de la zona probable P90, hover con la ola del nodo más cercano y línea de tiempo.*

---

## Contenido

1. [Qué cambió en la v0.3.0](#qué-cambió-en-la-v030)
2. [El único archivo de entrada](#el-único-archivo-de-entrada)
3. [El modelo browniano](#el-modelo-browniano)
4. [La interfaz y el recorrido guiado](#la-interfaz-y-el-recorrido-guiado)
5. [Ejemplo: 120 h frente a Cancún](#ejemplo-120-h-frente-a-cancún)
6. [Cómo correrlo en local (Windows / PowerShell)](#cómo-correrlo-en-local-windows--powershell)
7. [Despliegue](#despliegue)
8. [API](#api)
9. [Mapa del repositorio](#mapa-del-repositorio)
10. [Pruebas y rendimiento](#pruebas-y-rendimiento)
11. [Límites honestos](#límites-honestos)
12. [Preguntas para el profesor y SEMAR](#preguntas-para-el-profesor-y-semar)
13. [Créditos y atribuciones](#créditos-y-atribuciones)

---

## Qué cambió en la v0.3.0

| | v0.2.0 | v0.3.0 |
|---|---|---|
| Entrada | `salidadatos.txt` (viento) + `dirmarea.txt` (oleaje) | **Solo `dirmarea.txt`**; el viento se eliminó del repositorio y del código |
| Modelo | `pms-lagrangiano-0.2.0`: arrastre del viento α·u_w + difusión | **`pms-browniano-0.3.0`**: deriva de Stokes de la ola + movimiento browniano |
| Parámetros | α (arrastre del viento), K_h | **γ** (factor de la deriva por oleaje), **K_h** |
| Malla | La del viento; el oleaje se interpolaba (estaba desplazado 0.08°) | La **nativa** de `dirmarea.txt`, sin interpolar mallas |
| Interfaz | Panel oscuro a la izquierda y mapa | **«Carta náutica»**: tema claro, mapa a pantalla completa, **tres pasos** y **recorrido guiado** |

## El único archivo de entrada

`data/semar/dirmarea.txt`: oleaje de viento entregado por SEMAR como muestra. Está en este
repositorio **privado**; **no debe redistribuirse** sin autorización de SEMAR (ver
[`data/semar/README.md`](data/semar/README.md)).

| Elemento | Formato |
|---|---|
| Separador | `;` |
| Encabezado | `LON;LAT;dirolavto;alturaolavto` |
| Bloques | 41, cada uno empieza con `01OCT2026 00 h` (fecha base, hora base, hora de pronóstico h = 0, 3, …, 120) |
| Filas por bloque | 4 794: malla 94 × 51 de 0.16°, lon −98.00 … −83.12, lat 23 … 15 (de norte a sur, de oeste a este) |
| `dirolavto` | Dirección **desde** la que viene la ola de viento (grados, 0 = norte) |
| `alturaolavto` | Altura de la ola de viento (m) |
| Relleno | `-9.99e+08` = sin dato (tierra) → NaN |

**Dominio del modelo**: el recuadro de Yucatán alineado a esa malla, lon −92.08 … −84.08 y
lat 16.92 … 23.00: 51 × 39 = 1 989 nodos, de los cuales 1 295 tienen ola.

**Hallazgos del archivo de muestra** (verificados por el validador y por
`tests/test_validador.py::test_datos_reales_de_semar`):

- Los **41 bloques son idénticos** byte por byte: el oleaje no cambia en el tiempo. El validador
  lo reporta como advertencia y el modelo igual interpola entre bloques cada 3 h, así que
  funcionará sin cambios cuando lleguen datos que sí varíen.
- La fecha (1 oct 2026 00 UTC) es de muestra.
- En el dominio, la altura va de 0.11 a 1.82 m (media 1.02 m). Frente a Cancún la ola viene
  del ESE (~107°) con ~1.1 m.
- La máscara de mar del archivo y la costa poligonal del modelo difieren en 50 nodos
  (13 con ola sobre «tierra» del modelo, 37 sin ola sobre «mar» del modelo).

**El validador** (`src/ingestion/validador.py`) no se detiene en el primer error y reporta
cada hallazgo con la causa, el archivo y la acción. Revisa:

- encabezado y columnas, filas defectuosas y fecha legible (mapa propio de meses en inglés);
- horas +0 a +120 cada 3 h, sin huecos ni desorden;
- malla regular de 0.16°, rectangular, igual en todos los bloques, y cobertura del dominio;
- relleno → NaN, con dirección y altura faltando juntas;
- rangos: altura de 0 a 20 m y dirección de 0 a 360°;
- advertencia por bloques idénticos;
- comparación de la máscara de mar con la costa del modelo.

## El modelo browniano

`pms-browniano-0.3.0`. Para cada partícula y cada paso Δt = 1 h:

```
X(t+Δt) = X(t) + u_ola(X,t)·Δt + √(2·K_h·Δt)·ξ ,     ξ ~ N(0, 1) en cada eje

|u_ola| = γ · 2π³·H² / (g·T³)     hacia donde viaja la ola (dirolavto + 180°)
T = 4.0·√H                        período SUPUESTO (el archivo no trae período)
```

Es la **deriva de Stokes** superficial de una ola en aguas profundas. Con el período
supuesto se simplifica a |u_ola| ≈ γ · 0.0988·√H: con H = 1.25 m, T ≈ 4.5 s y
|u_ola| ≈ **0.11 m/s** (unos 9.5 km por día).

| Parámetro | Qué hace | Valor por defecto | Rango | Estado |
|---|---|---|---|---|
| **γ** | Escala la deriva de Stokes: 0 la apaga, 1 es la estimación base, 3 la triplica | 1 | 0–3 | Preliminar, sin calibrar |
| **K_h** | Intensidad del movimiento browniano: cuánto se dispersan las partículas al azar | 10 m²/s | 0–100 | Preliminar, sin calibrar |
| Radio inicial | Tamaño del conglomerado al soltarlo | 5 km | 0.5–50 | — |
| Partículas | Cuántas partículas representan al conglomerado | 2 000 | 100–5 000 | — |
| Horizonte | Horas simuladas | 120 h | 24–120 | — |
| Semilla | Misma semilla y mismos ajustes dan el mismo resultado | 2026 | — | — |

**El supuesto del período.** `dirmarea.txt` trae altura y dirección, pero no período. La
deriva de Stokes depende fuertemente del período (∝ 1/T³). T = 4.0·√H es una relación
empírica aproximada para mar de viento en desarrollo, documentada en `src/config.py`, en este
README y en la interfaz (paso 2, «Avanzado», y recorrido guiado). Si SEMAR entrega el
período, basta con usarlo en `src/model/campos.py`.

**Implementación** (`src/model/`):

- la altura se interpola de forma bilineal ignorando los nodos sin dato, y la dirección por
  sus componentes seno y coseno;
- la interpolación en el tiempo es lineal entre bloques;
- el término determinista se integra por punto medio (RK2);
- el paso de metros a grados corrige la longitud por cos(lat);
- una partícula queda **varada** en el último punto en mar del segmento (bisección contra la
  costa del modelo) y **fuera del dominio** si sale del recuadro;
- la semilla hace reproducibles las corridas.

**Salidas**:

- centroide de las partículas a flote;
- radio P90 a su alrededor;
- zona probable P90: el menor conjunto de celdas de 0.16° con el 90 % de las partículas;
- probabilidad de arribo por tramo de costa: Alta ≥ 30 %, Media ≥ 10 %, Baja ≥ 2 %, Muy baja;
- registro JSON con la huella SHA-256 de `dirmarea.txt` y una bitácora.

## La interfaz y el recorrido guiado

Diseño propio de **carta náutica**:

- papel crema, tinta azul marino, IBM Plex Sans para el texto y IBM Plex Mono para los datos;
- mapa de OpenStreetMap con sepia suave, retícula de grados y rosa de los vientos.

El mapa ocupa toda la pantalla y los controles flotan en **tres pasos**, uno a la vez, con
una barra arriba para ir y volver:

1. **Punto de liberación**: clic en el mar (o lat/lon); el círculo punteado es el radio.
2. **Ajustes**: horizonte y, plegado en «Avanzado», radio, partículas, γ, K_h y semilla, con
   una línea de explicación debajo de cada uno.
3. **Resultado**: % varado al final, los 3 tramos de costa con mayor probabilidad (Alta/Media/
   Baja) y el radio P90 a +120 h. Los parámetros, la huella y las advertencias están en
   «Detalles».

Además:

- **Línea de tiempo**: reproducir/pausa, deslizador 0–120 h y hora en UTC y en Cancún (UTC−5).
  Teclas: espacio, ← y →.
- **Oleaje**: flechas **estáticas** en una submalla (largo ∝ altura), con un solo interruptor.
- **Hover**: lat/lon con 3 decimales y la altura y dirección de la ola del nodo más cercano.
- **Historial** plegado: fecha, punto y % varado; clic para reabrir.
- **Estado** en una sola línea (validando / listo / calculando / error); el detalle aparece al
  hacer clic. Si el archivo no es válido, un velo muestra la causa, el archivo y la acción.

**Recorrido guiado.** Se abre solo la primera vez (se recuerda en `localStorage`) y siempre
está disponible con el botón «Recorrido guiado». Oscurece la pantalla, ilumina el elemento
del que habla y muestra una tarjeta con «Paso k de N» y los botones «Siguiente», «Atrás» y
«Saltar». Teclas: Esc salta; → y Enter avanzan.

Sus 11 pasos:

1. bienvenida;
2. los datos y las flechas de oleaje;
3. fijar el punto: **espera a que el usuario haga clic en el mar**;
4. el horizonte;
5. γ y K_h;
6. simular: **espera a que termine una simulación real frente a Cancún**;
7. cómo leer partículas, trayectoria y zona P90;
8. la línea de tiempo;
9. el resultado y por qué es probabilidad;
10. el historial;
11. cierre.

Tiene narración opcional en voz (Web Speech API, es-MX), apagada por defecto, con el botón
«Voz».

| Recorrido guiado | Datos inválidos (falta la hora +57) |
|---|---|
| ![Recorrido guiado](docs/captura_recorrido.png) | ![Error de datos](docs/captura_error.png) |

Capturas en 1366×768 y 1920×1080 en [`docs/capturas/`](docs/capturas/).

## Ejemplo: 120 h frente a Cancún

Liberación en 21.120° N, 86.660° O (~8 km al este de la zona hotelera), con los valores por
defecto (2 000 partículas, radio 5 km, γ = 1, K_h = 10 m²/s, semilla 2026):

| Resultado | Valor |
|---|---|
| Varado al final (+120 h) | **100 %**: primeras partículas a +8 h, mediana +27 h, últimas a +61 h |
| Cancún – Isla Mujeres | **96.5 % · Alta** (primer arribo a +8 h) |
| Costa Mujeres – Isla Blanca | **3.5 % · Baja** (primer arribo a +24 h) |
| Radio P90 | 5.3 km a +24 h y 4.5 km a +48 h; a +120 h no queda ninguna partícula a flote |
| Centroide | 14.8 km recorridos hacia el NO |

La ola viene del ESE frente a Cancún, así que la deriva de Stokes (~0.10 m/s) empuja el
conglomerado hacia la costa. Sin viento ni corrientes (la Corriente de Yucatán supera 1 m/s
hacia el norte), este resultado **no es un pronóstico operativo**.

## Cómo correrlo en local (Windows / PowerShell)

Requisitos: Python 3.12 o superior (probado con 3.14.0), Git y conexión a internet para el
mapa base.

```powershell
git clone https://github.com/renecano/sargazo_prototipo.git
cd sargazo_prototipo
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # si se bloquea: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install -r requirements-dev.txt
python main.py                          # abre http://localhost:8000 (lee data\semar\dirmarea.txt)
```

Opciones: `--puerto 8080`, `--host 0.0.0.0`, `--no-navegador`, `--datos <carpeta>` y
`--simulaciones <carpeta>`.

Pruebas y utilidades:

```powershell
python -m pytest                        # 102 pruebas rápidas
python -m pytest -m e2e                 # 15 pruebas de interfaz con Playwright (usa Microsoft Edge)
python scripts/capturar_pantalla.py     # capturas de docs/ en 1366×768 y 1920×1080
python scripts/medir_rendimiento.py     # tiempos y memoria → docs/rendimiento.md
python scripts/generar_fixtures.py --destino tmp\fixture --completo   # dirmarea.txt de prueba
```

## Despliegue

- **Vercel** (<https://pms-sargazo.vercel.app>). El proyecto `pms-sargazo` despliega `main`
  automáticamente en cada push. La función (`api/index.py`) incluye `src/` y
  `data/semar/dirmarea.txt`. En Vercel el historial vive en `/tmp` (efímero) y la interfaz usa
  los endpoints síncronos. **La demo es pública**: cualquiera con la URL ve el oleaje. Si
  SEMAR no lo autoriza, hay que activar Deployment Protection o retirar el archivo.
- **VPS Linux** (pendiente de acceso al servidor): [`docs/despliegue_vps.md`](docs/despliegue_vps.md)
  cubre clon en `/opt/pms`, venv, servicio systemd `pms`, puerto 8000, logs, actualización,
  reversa y desinstalación.

## API

| Método y ruta | Uso |
|---|---|
| `GET /api/salud` | Estado, versiones, si hay datos y si hay trabajos en segundo plano |
| `GET /api/validacion` · `POST /api/validacion` | Validación síncrona (con caché) o en segundo plano con progreso |
| `GET /api/campos` | Dirección y altura de ola por bloque en la malla del modelo, para las flechas y el hover |
| `GET /api/costa` | Costa del modelo y tramos de arribo (GeoJSON) |
| `POST /api/simulaciones` | Simula (lat, lon, radio_km, particulas, gamma, kh_m2s, horizonte_h, semilla), guarda y devuelve el registro |
| `POST /api/trabajos/simulacion` · `GET /api/trabajos/{id}` | Igual, en segundo plano, con progreso por hora |
| `GET /api/simulaciones` · `GET /api/simulaciones/{id}` | Historial y registro completo |

Los errores llegan como `{"detail": {"causa", "accion", "archivo"}}`:

- 409: datos no válidos;
- 422: parámetros fuera de rango o punto en tierra;
- 404: id inexistente.

Documentación interactiva en `/docs`.

## Mapa del repositorio

```
sargazo_prototipo/
├── main.py                       python main.py → http://localhost:8000
├── api/index.py · vercel.json    Función sin servidor para Vercel
├── data/semar/                   dirmarea.txt (repositorio privado; no redistribuir) y su README
├── data/simulations/             Simulaciones guardadas (JSON)
├── src/
│   ├── config.py                 Dominio, malla, archivo, γ, K_h y supuesto del período
│   ├── ingestion/                lector.py (formato SEMAR, relleno, malla) · validador.py
│   ├── model/                    campos (deriva de Stokes) · simulacion · costa · metricas · conversiones
│   ├── api/                      app.py · servicios.py · almacen.py
│   └── view/                     index.html · css/carta.css · js/ (main, recorrido, capas, datos, paneles…)
├── scripts/                      generar_fixtures.py · capturar_pantalla.py · medir_rendimiento.py
├── tests/                        Pruebas rápidas + tests/e2e/ (Playwright)
├── docs/                         Capturas, rendimiento y guía de despliegue en VPS
└── .github/workflows/ci.yml      CI: Windows y Ubuntu, Python 3.12 y 3.14, + e2e
```

## Pruebas y rendimiento

**102 pruebas rápidas** (`python -m pytest`) y **15 de interfaz** (`python -m pytest -m e2e`),
todas en verde en local.

| Archivo | Qué comprueba |
|---|---|
| `tests/test_lector.py` | Fechas `DDMMMAAAA HH [h]` (incluidas ilegibles), 41 bloques, relleno → NaN, filas defectuosas, malla de norte a sur |
| `tests/test_validador.py` | Fixture válido; bloques idénticos solo cuando lo son; cobertura del dominio; falta del archivo, fecha ilegible, columna ausente, hora faltante o desordenada, altura y dirección fuera de rango, relleno inconsistente, malla no rectangular o fuera del recuadro, máscara vs costa, otros archivos; archivo real |
| `tests/test_modelo.py` | Deriva de Stokes contra la fórmula y contra el desplazamiento analítico con K_h = 0 (en la dirección correcta, con cos(lat)), γ, reproducibilidad, dispersión √(2·K_h·t) ± 5 %, interpolación entre bloques y por seno/coseno, nodos de tierra ignorados, ninguna partícula sobre tierra, salida de dominio, métricas |
| `tests/test_api.py` | 200 y guardado con huella; reproducibilidad; trabajos con progreso; 409, 422 y 404; sin datos |
| `tests/e2e/test_interfaz.py` | Recorrido guiado (se abre una vez, «Saltar», completo de principio a fin), estado y detalle, los tres pasos, clic para liberar, flechas fijas, 120 h frente a Cancún, pausa, teclas, hover con ola, historial, punto en tierra, datos inválidos, sin datos |

**Rendimiento en local** (Windows 11, 8 GB de RAM; detalle en [`docs/rendimiento.md`](docs/rendimiento.md)):

| Operación | Tiempo |
|---|---|
| Validar `dirmarea.txt` | 0.27 s |
| 2 000 partículas × 120 h frente a Cancún | 0.13 s |
| 2 000 partículas × 120 h en mar abierto | 0.33 s |
| 5 000 partículas × 120 h en mar abierto | 0.62 s |
| Registro JSON (2 000 partículas) | 1.3 MB |

**En Vercel**, medido desde Windows (incluye la red):

| Operación | Tiempo |
|---|---|
| Validación (primera vez en la instancia) | 0.9 s |
| Validación (en caché) | 0.27 s |
| Campos de oleaje | 0.47 s |
| Simulación de 120 h frente a Cancún | 0.95 s |
| La app queda «lista» en el navegador | ~1.8 s |

**Arranque en frío.** No se pudo forzar uno limpio en Vercel, porque la instancia de producción
ya estaba caliente tras cada despliegue (`/api/salud` respondió en 0.30 s en la primera
petición). Con el mismo punto de entrada (`api/index.py`) medido en local cuesta ~1.0–1.1 s:
0.75 s de importar la app y 0.30 s de la primera validación. Está muy lejos del límite de 60 s
de la función, así que no fue necesario optimizar la lectura del archivo.

## Límites honestos

- **Datos de muestra**: los 41 bloques de `dirmarea.txt` son idénticos (el oleaje no cambia en
  120 h) y su fecha es de muestra.
- **Sin viento ni corrientes**: solo se usa la deriva por oleaje. Falta la Corriente de Yucatán
  y el arrastre directo del viento, que frente a Quintana Roo dominarían el transporte.
- **Período de ola supuesto** (T = 4.0·√H): la deriva de Stokes depende de T³; un período real
  distinto cambia mucho la velocidad.
- **Parámetros sin calibrar** (γ y K_h) y **sin validación contra observaciones** (boletines de
  SEMAR o detecciones de SaWS).
- **Costa aproximada** (decenas de vértices), que difiere de la máscara del archivo en 50 nodos;
  la malla de 0.16° (~17 km) no resuelve procesos costeros.
- **Dominio limitado** al recuadro de Yucatán y liberación única en t = 0.
- **Infraestructura mínima**: JSON en disco, sin usuarios ni autenticación. La demo de Vercel
  es pública y su historial es efímero. El CI de GitHub no corre hoy porque la cuenta no
  tiene minutos de Actions; las pruebas se corren en local.

## Preguntas para el profesor y SEMAR

1. ¿Hay **período de ola** (o espectro) para no suponer T = 4.0·√H?
2. ¿Los 41 bloques idénticos de `dirmarea.txt` son solo de muestra? ¿Cuándo habrá un
   pronóstico que cambie en el tiempo?
3. ¿Es correcto usar solo la ola de viento, o debe sumarse el mar de fondo (swell)?
4. ¿Qué rango de γ (fracción de la deriva de Stokes que siente el sargazo) es razonable?
5. ¿Se reincorporan viento y corrientes (CMEMS/HYCOM) en una siguiente versión?
6. ¿SEMAR autoriza mostrar el oleaje en una demo pública como la de Vercel?
7. ¿Contra qué boletines o detecciones validamos las trayectorias a 24 y 48 h?

## Créditos y atribuciones

**Equipo 2**: Marco Aurelio Tamez Robles, Claudia Vanessa Hermosillo Díaz,
René Emiliano Cano Fuentes, Alan Yael García Velázquez, José Luis Socorro Martínez y
José Ángel Vargas Carranza.

- Datos de oleaje: **Secretaría de Marina (SEMAR)**, archivo de muestra; no redistribuir.
- Mapa base © [colaboradores de OpenStreetMap](https://www.openstreetmap.org/copyright) (ODbL).
- [Leaflet](https://leafletjs.com) 1.9.4 (BSD-2-Clause), incluido en `src/view/vendor/leaflet/`.
- Tipografías [IBM Plex Sans y IBM Plex Mono](https://www.ibm.com/plex/) vía Google Fonts (SIL Open Font License).
- Referencias: SEMAR IOGMC (boletines de sargazo), USF SaWS y NOAA GNOME.

Código bajo licencia [MIT](LICENSE).
