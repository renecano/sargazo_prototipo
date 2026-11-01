# PMS · Predicción de Movimiento del Sargazo

**v0.4.0 · demo en línea: <https://pms-sargazo.vercel.app> · validación: <https://pms-sargazo.vercel.app/validacion>**

PMS estima hacia dónde podría derivar un conglomerado de sargazo frente a la Península de
Yucatán durante los próximos 5 días (120 h). Lo hace con un **modelo de partículas
brownianas** que mueve cada partícula con la **deriva de Stokes de la ola de viento** de
SEMAR más un movimiento aleatorio. El resultado es una **probabilidad**, no una certeza: el
archivo de oleaje es de muestra y el modelo no incluye viento ni corrientes. **La validación
v0.4.0 contra el sargazo visto por satélite muestra que todavía no predice el movimiento mejor
que suponer que el sargazo se queda quieto** (ver abajo).

![PMS: resultado de 120 h frente a Cancún, pausado en +12 h, con el hover de la ola](docs/captura_resultado.png)

*Interfaz «carta náutica» en 1366×768: tres pasos (punto de liberación → ajustes →
resultado), flechas fijas de oleaje, partículas a flote y varadas, trayectoria central,
contorno de la zona probable P90, hover con la ola del nodo más cercano y línea de tiempo.*

---

## Contenido

1. [¿El modelo se mueve como el sargazo real?](#el-modelo-se-mueve-como-el-sargazo-real)
2. [Qué cambió en la v0.4.0](#qué-cambió-en-la-v040)
3. [El único archivo de entrada](#el-único-archivo-de-entrada)
4. [El modelo browniano](#el-modelo-browniano)
5. [La interfaz y el recorrido guiado](#la-interfaz-y-el-recorrido-guiado)
6. [Ejemplo: 120 h frente a Cancún](#ejemplo-120-h-frente-a-cancún)
7. [Cómo correrlo en local (Windows / PowerShell)](#cómo-correrlo-en-local-windows--powershell)
8. [Despliegue](#despliegue)
9. [API](#api)
10. [Mapa del repositorio](#mapa-del-repositorio)
11. [Pruebas y rendimiento](#pruebas-y-rendimiento)
12. [Límites honestos](#límites-honestos)
13. [Siguiente paso](#siguiente-paso)
14. [Preguntas para el profesor y SEMAR](#preguntas-para-el-profesor-y-semar)
15. [Créditos y atribuciones](#créditos-y-atribuciones)

---

## ¿El modelo se mueve como el sargazo real?

El profesor preguntó cómo sabemos que el comportamiento del modelo es real. La v0.4.0 lo mide:
toma días de 2022–2026 con sargazo visto por satélite (AFAI de USF en NOAA AOML), siembra
partículas donde estaba, las mueve con el modelo usando el oleaje real de esas fechas
(MFWAM de Copernicus Marine, escrito como `dirmarea.txt` en el formato de SEMAR) y compara
contra lo que el satélite vio 3, 5 y 7 días después. La referencia mínima es suponer que el sargazo **no se
mueve** (persistencia, E0).

<!-- validacion:inicio (generado por scripts/validar.py; no editar a mano) -->
**Con datos satelitales 2022–2026, el modelo v0.3 (solo oleaje) no se distingue de suponer que el sargazo no se mueve; ni agregando corrientes (E4 Corriente SMOC total + browniano) se supera a la persistencia.**

FSS a 25 km (1 = perfecto) en 11 casos de evaluación 2025–2026 (γ y K_h de E3 calibrados con 14 casos anteriores), media e IC 95 %:

| Experimento | +3 d | +5 d | +7 d |
|---|---|---|---|
| E0 Persistencia | 0.375 [0.291–0.452] | 0.354 [0.272–0.424] | 0.364 [0.308–0.411] |
| E1 Solo browniano | 0.379 [0.294–0.455]<br>Δ vs E0 +0.004 [-0.001, +0.010] | 0.357 [0.275–0.429]<br>Δ vs E0 +0.003 [-0.004, +0.012] | 0.371 [0.313–0.420]<br>Δ vs E0 +0.007 [+0.001, +0.014] |
| E2 PMS v0.3 | 0.377 [0.296–0.449]<br>Δ vs E0 +0.002 [-0.017, +0.024] | 0.332 [0.254–0.404]<br>Δ vs E0 -0.022 [-0.045, +0.001] | 0.345 [0.280–0.410]<br>Δ vs E0 -0.019 [-0.055, +0.018] |
| E3 PMS calibrado | 0.378 [0.293–0.454]<br>Δ vs E0 +0.003 [-0.004, +0.009] | 0.352 [0.270–0.423]<br>Δ vs E0 -0.002 [-0.009, +0.006] | 0.363 [0.307–0.409]<br>Δ vs E0 -0.001 [-0.006, +0.005] |
| E4 Corriente SMOC total + browniano | 0.359 [0.270–0.437]<br>Δ vs E0 -0.016 [-0.077, +0.049] | 0.283 [0.215–0.346]<br>Δ vs E0 -0.071 [-0.134, -0.006] | 0.254 [0.190–0.315]<br>Δ vs E0 -0.110 [-0.165, -0.049] |
| E5 Corriente sin Stokes + viento 1 % + ola | 0.342 [0.261–0.416]<br>Δ vs E0 -0.033 [-0.091, +0.025] | 0.269 [0.200–0.333]<br>Δ vs E0 -0.085 [-0.144, -0.020] | 0.226 [0.162–0.289]<br>Δ vs E0 -0.138 [-0.187, -0.084] |
| E5 Corriente sin Stokes + viento 2 % + ola | 0.297 [0.227–0.366]<br>Δ vs E0 -0.078 [-0.125, -0.034] | 0.255 [0.186–0.317]<br>Δ vs E0 -0.099 [-0.152, -0.041] | 0.199 [0.137–0.259]<br>Δ vs E0 -0.165 [-0.209, -0.122] |
| E5 Corriente sin Stokes + viento 3 % + ola | 0.282 [0.213–0.351]<br>Δ vs E0 -0.093 [-0.145, -0.045] | 0.227 [0.169–0.280]<br>Δ vs E0 -0.126 [-0.173, -0.077] | 0.182 [0.122–0.244]<br>Δ vs E0 -0.182 [-0.228, -0.136] |

Reporte completo con método, casos y limitaciones: [docs/validacion.md](docs/validacion.md) · página en la app: `/validacion`.
<!-- validacion:fin -->

## Qué cambió en la v0.4.0

- **Validación** contra el sargazo observado por satélite: paquete `validacion/`,
  `python scripts/validar.py` (todo desde cero con un comando), resultados en
  [`docs/validacion/`](docs/validacion/), reporte en [`docs/validacion.md`](docs/validacion.md)
  (lo genera el script; verifica sus propios conteos),
  fuentes en [`docs/fuentes_validacion.md`](docs/fuentes_validacion.md) y página `/validacion`
  enlazada desde la leyenda.
- **Forzamientos de Copernicus Marine** (toolbox `copernicusmarine`, cuenta gratuita con
  `copernicusmarine login`; las credenciales no entran al repositorio): ola de viento MFWAM a
  0.083° (reanálisis de 0.2° antes de nov 2022) y corriente SMOC a 0.083°. El viento de E5 viene
  de ERA5 vía Open-Meteo. Una primera corrida con oleaje y corriente de Open-Meteo quedó bloqueada
  por su cuota diaria y se rehizo completa con Copernicus.
- **`scripts/generar_dirmarea.py`**: escribe un `dirmarea.txt` con la ola de viento real de una
  fecha, en el mismo formato que el de SEMAR (`python main.py --datos <carpeta>` lo usa).
- **El producto no cambia**: sigue usando solo `dirmarea.txt` y el modelo `pms-browniano-0.3.0`.
  `simular()` ahora delega en `integrar()` (posiciones iniciales y hora de inicio libres) con
  resultados idénticos byte a byte.
- **CI en verde** de nuevo ahora que el repositorio es público.

### Qué cambió en la v0.3.0

| | v0.2.0 | v0.3.0 |
|---|---|---|
| Entrada | `salidadatos.txt` (viento) + `dirmarea.txt` (oleaje) | **Solo `dirmarea.txt`**; el viento se eliminó del repositorio y del código |
| Modelo | `pms-lagrangiano-0.2.0`: arrastre del viento α·u_w + difusión | **`pms-browniano-0.3.0`**: deriva de Stokes de la ola + movimiento browniano |
| Parámetros | α (arrastre del viento), K_h | **γ** (factor de la deriva por oleaje), **K_h** |
| Malla | La del viento; el oleaje se interpolaba (estaba desplazado 0.08°) | La **nativa** de `dirmarea.txt`, sin interpolar mallas |
| Interfaz | Panel oscuro a la izquierda y mapa | **«Carta náutica»**: tema claro, mapa a pantalla completa, **tres pasos** y **recorrido guiado** |

## El único archivo de entrada

`data/semar/dirmarea.txt`: oleaje de viento entregado por SEMAR como muestra. El repositorio
es **público**, así que el archivo también lo es; está **pendiente confirmar la autorización de
SEMAR** para difundirlo (ver
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
python -m pytest                        # pruebas rápidas, sin red
python -m pytest -m e2e                 # pruebas de interfaz con Playwright (usa Microsoft Edge)
python scripts/capturar_pantalla.py     # capturas de docs/ en 1366×768 y 1920×1080
python scripts/medir_rendimiento.py     # tiempos y memoria → docs/rendimiento.md
python scripts/generar_fixtures.py --destino tmp\fixture --completo   # dirmarea.txt de prueba
```

Validación contra el sargazo observado (descarga a `data/validacion/`, fuera de git; ~2 h la
primera vez, minutos después con la caché):

```powershell
copernicusmarine login                  # solo la primera vez; pide usuario y contraseña de Copernicus Marine
python scripts/validar.py               # todo desde cero → docs/validacion/ y docs/validacion.md
python scripts/validar.py --solo-reporte                    # rehace tablas y figuras desde la caché
python scripts/generar_dirmarea.py --fecha 2026-10-01       # dirmarea.txt con ola real de una fecha
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
├── data/semar/                   dirmarea.txt de SEMAR (autorización de difusión por confirmar) y su README
├── data/simulations/             Simulaciones guardadas (JSON)
├── src/
│   ├── config.py                 Dominio, malla, archivo, γ, K_h y supuesto del período
│   ├── ingestion/                lector.py (formato SEMAR, relleno, malla) · validador.py
│   ├── model/                    campos (deriva de Stokes) · simulacion · costa · metricas · conversiones
│   ├── api/                      app.py · servicios.py · almacen.py
│   └── view/                     index.html · css/carta.css · js/ (main, recorrido, capas, datos, paneles…)
├── validacion/                   Validación v0.4.0: afai · inventario · casos · dirmarea · openmeteo · campos ·
│                                 experimentos · metricas · ejecutar · reporte · documento
├── data/validacion/              Caché de descargas de la validación (fuera de git y de Vercel)
├── scripts/                      validar.py · generar_dirmarea.py · generar_fixtures.py · capturar_pantalla.py ·
│                                 medir_rendimiento.py
├── tests/                        Pruebas rápidas + tests/fixtures (recorte de ERDDAP) + tests/e2e/ (Playwright)
├── docs/                         validacion.md · validacion/ (tablas, figuras, página) · fuentes_validacion.md ·
│                                 capturas, rendimiento y guía de despliegue en VPS
└── .github/workflows/ci.yml      CI: Windows y Ubuntu, Python 3.12 y 3.14, + e2e
```

## Pruebas y rendimiento

**149 pruebas rápidas** (`python -m pytest`, sin red) y **16 de interfaz** (`python -m pytest -m e2e`),
todas en verde en local y en el CI de GitHub Actions (Windows y Ubuntu, Python 3.12
y 3.14, más e2e): [corrida en verde](https://github.com/renecano/sargazo_prototipo/actions/runs/41160399072).

| Archivo | Qué comprueba |
|---|---|
| `tests/test_lector.py` | Fechas `DDMMMAAAA HH [h]` (incluidas ilegibles), 41 bloques, relleno → NaN, filas defectuosas, malla de norte a sur |
| `tests/test_validador.py` | Fixture válido; bloques idénticos solo cuando lo son; cobertura del dominio; falta del archivo, fecha ilegible, columna ausente, hora faltante o desordenada, altura y dirección fuera de rango, relleno inconsistente, malla no rectangular o fuera del recuadro, máscara vs costa, otros archivos; archivo real |
| `tests/test_modelo.py` | Deriva de Stokes contra la fórmula y contra el desplazamiento analítico con K_h = 0 (en la dirección correcta, con cos(lat)), γ, reproducibilidad, dispersión √(2·K_h·t) ± 5 %, interpolación entre bloques y por seno/coseno, nodos de tierra ignorados, ninguna partícula sobre tierra, salida de dominio, métricas |
| `tests/test_api.py` | 200 y guardado con huella; reproducibilidad; trabajos con progreso; 409, 422 y 404; sin datos; página `/validacion` y sus figuras |
| `tests/test_validacion.py` | Lector de ERDDAP con un recorte real (`tests/fixtures`); detección (franja, nubes y su borde, umbral adaptativo, regiones y franja de la costura); `generar_dirmarea` con formato idéntico al de SEMAR y aceptado por el validador y el modelo; Open-Meteo sin red (unidades, caché, cuota); campos encadenados y convenciones de corriente y viento; FSS analítico (1, 0, 2/3, 1 − d/n); MCC recupera desplazamientos sintéticos (también con nubes); Liu-Weisberg, bootstrap y contingencia; persistencia da FSS = 1 si nada se mueve; siembra; integrador del producto; selección de casos reproducible y sin traslape; veredicto contra E0 |
| `tests/e2e/test_interfaz.py` | Recorrido guiado (se abre una vez, «Saltar», completo de principio a fin), estado y detalle, los tres pasos, clic para liberar, flechas fijas, 120 h frente a Cancún, pausa, teclas, hover con ola, historial, punto en tierra, datos inválidos, sin datos; enlace de la leyenda a `/validacion` con tabla y figuras cargadas, sin desbordar en 1366 px ni en 390 px |

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

- **El modelo v0.3 no le gana a suponer que el sargazo no se mueve.** En la validación v0.4.0
  (casos de evaluación 2025–2026, FSS a 25 km) la diferencia contra la persistencia no es
  distinguible de cero en ningún horizonte; la calibración eligió el mínimo movimiento de la
  rejilla (γ = 0). Hoy PMS no aporta información sobre hacia dónde se mueve el sargazo más allá
  de dónde ya está. Tabla y reporte: [arriba](#el-modelo-se-mueve-como-el-sargazo-real) y
  [`docs/validacion.md`](docs/validacion.md).
- **Agregar corrientes, tal como se probó, empeora.** La corriente SMOC (con y sin viento) se
  acerca a la rapidez y la dirección del desplazamiento observado con el MCC, pero el FSS cae frente a la persistencia a +5 y
  +7 días y una parte de las partículas sale del recuadro con la Corriente de Yucatán. No basta
  con sumar la corriente: falta entender por qué la posición predicha se aleja de la observada.
- **La «verdad» satelital es ruidosa.** El AFAI de AOML tiene ruido del orden del umbral de la
  literatura, dos regiones de procesamiento con una costura y muchas nubes: se corrigió con un
  umbral adaptado al ruido, el fondo por región y máscaras, pero un FSS «útil» (~0.5) no lo
  alcanza ni la persistencia.
- **Datos de muestra**: los 41 bloques de `dirmarea.txt` de SEMAR son idénticos (el oleaje no
  cambia en 120 h). Comparado con la ola de viento real de ese día, su altura queda alta y la
  diferencia crece con las horas (ver el caso del 01/10/2026 en el reporte).
- **Período de ola supuesto** (T = 4.0·√H): contra el producto de oleaje de Copernicus el
  supuesto quedó cerca del período real de la ola de viento y la deriva de Stokes de la fórmula
  cerca de la del espectro completo (ver «Período y deriva de Stokes» en el reporte), así que no
  es la causa principal del desempeño.
- **Costa aproximada** (decenas de vértices), que difiere de la máscara del archivo en 50 nodos;
  la malla de 0.16° (~17 km) no resuelve procesos costeros.
- **Dominio limitado** al recuadro de Yucatán y liberación única en t = 0.
- **Infraestructura mínima**: JSON en disco, sin usuarios ni autenticación. La demo de Vercel
  es pública y su historial es efímero.

## Siguiente paso

1. **No usar PMS para decidir** hasta que una versión le gane a la persistencia con casos de
   evaluación; presentarlo como prototipo validado *negativamente*, con su evidencia.
2. **Diagnosticar por qué la corriente empeora**: comparar por caso el desplazamiento MCC con la
   corriente SMOC en el mismo punto, revisar la Corriente de Yucatán y el borde del recuadro
   (ampliar el dominio para no perder partículas), y probar la corriente euleriana sola.
3. **Mejorar la verdad**: segunda opinión con la detección Sentinel-3 OLCI (Debue et al., 2026)
   cuando su servidor responda, y más casos (temporadas con menos nube, criterios por zona).
4. **Calibrar con más libertad** solo con casos de calibración: factor de la corriente, del
   viento y de la ola a la vez, y volver a evaluar en casos nuevos.

## Preguntas para el profesor y SEMAR

1. ¿Los 41 bloques idénticos de `dirmarea.txt` son solo de muestra? ¿Cuándo habrá un
   pronóstico que cambie en el tiempo?
2. ¿SEMAR tiene corrientes o deriva observada (boyas, trayectorias de sargazo) para validar
   mejor que con el satélite?
3. ¿Contra qué boletines o detecciones de SEMAR comparamos los arribos a costa?
4. ¿Es correcto usar solo la ola de viento, o debe sumarse el mar de fondo (swell)?
5. ¿SEMAR autoriza mostrar el oleaje en una demo pública como la de Vercel?

## Créditos y atribuciones

**Equipo 2**: Marco Aurelio Tamez Robles, Claudia Vanessa Hermosillo Díaz,
René Emiliano Cano Fuentes, Alan Yael García Velázquez, José Luis Socorro Martínez y
José Ángel Vargas Carranza.

- Datos de oleaje: **Secretaría de Marina (SEMAR)**, archivo de muestra; difusión pendiente de autorización.
- Validación: AFAI de la **University of South Florida** (C. Hu) vía **NOAA AOML** Atlantic OceanWatch
  ERDDAP; oleaje **MFWAM** y corriente **SMOC** de **Copernicus Marine Service** (Mercator Ocean
  International): *Generated using E.U. Copernicus Marine Service Information; https://doi.org/10.48670/moi-00017, https://doi.org/10.48670/moi-00022, https://doi.org/10.48670/moi-00016*; viento **ERA5** (ECMWF / Copernicus) vía [Open-Meteo](https://open-meteo.com)
  (CC BY 4.0). Detalle en [`docs/fuentes_validacion.md`](docs/fuentes_validacion.md).
- Mapa base © [colaboradores de OpenStreetMap](https://www.openstreetmap.org/copyright) (ODbL).
- [Leaflet](https://leafletjs.com) 1.9.4 (BSD-2-Clause), incluido en `src/view/vendor/leaflet/`.
- Tipografías [IBM Plex Sans y IBM Plex Mono](https://www.ibm.com/plex/) vía Google Fonts (SIL Open Font License).
- Referencias: SEMAR IOGMC (boletines de sargazo), USF SaWS y NOAA GNOME.

Código bajo licencia [MIT](LICENSE).
