# Contraste de la paleta del sargazo

Generado por `python scripts/medir_contraste.py` el 2026-11-11 21:38 UTC. No editar a mano.

El sargazo se dibuja en púrpura sobre la carta y las calles y en rosa claro sobre el satélite: un tono que no aparece en la tierra ni en el mar de ningún mapa base. Además del tono, cada cosa tiene su forma: lo que flota es un cuadro relleno con borde, lo varado es un anillo hueco con halo y la densidad es una trama de líneas diagonales.

## Cómo se mide

- **Razón de contraste** WCAG 2.x entre dos colores: (L₁ + 0.05) / (L₂ + 0.05), con L la luminancia relativa. El criterio 1.4.11 pide al menos 3:1 para objetos gráficos.
- **Fondos.** En la carta propia son los colores con que se pinta. En el satélite y en las calles se miden en teselas reales de zoom 10 de ocho zonas del dominio (Cancún, canal de Cozumel, Tulum, Mahahual, Holbox, Progreso, mar abierto y Sian Ka'an): cada píxel se clasifica como tierra o mar con la máscara de costa del modelo. Se reporta la mediana y, como extremos, la mediana del decil más claro y del más oscuro. A las calles se les aplica el mismo filtro sepia que usa la interfaz.
- **Densidad y zona.** Se pintan con transparencia y solo sobre el mar: se mide el color de su línea ya mezclado con el mar del mapa base.
- **Daltonismo.** ΔE (CIE76) entre la partícula a flote media y lo que la rodea, con los colores transformados por las matrices de Machado, Oliveira y Fernandes (2009) para protanopía, deuteranopía y tritanopía completas.

## Carta propia

Fondos: tierra `#e3d3a8`, mar `#eef1ea`. Origen: constantes de la paleta (la carta se pinta con ellas).

| Elemento | Color | Forma | Tierra | Mar | 
|---|---|---|---|---|
| Partícula a flote, lenta | `#a44ab8` | cuadro relleno con borde | **3.3** | **4.3** | 
| Partícula a flote, media | `#7d1a8c` | cuadro relleno con borde | **5.9** | **7.7** | 
| Partícula a flote, rápida | `#470852` | cuadro relleno con borde | **9.9** | **12.9** | 
| Densidad 0.2–1 % (línea de la trama) | `#dccfdb` | trama diagonal | 1.0 | 1.3 | 
| Densidad 1–5 % (línea de la trama) | `#ccb0ce` | trama diagonal | 1.3 | 1.7 | 
| Densidad 5–20 % (línea de la trama) | `#ba8ebf` | trama diagonal | 1.8 | 2.4 | 
| Densidad ≥ 20 % (línea de la trama) | `#a86cb0` | trama diagonal | 2.6 | **3.4** | 
| Zona con el 90 % (línea) | `#683770` | línea fina | **6.0** | **7.8** | 
| Varado | `#c0392b` | anillo hueco con halo | **3.7** | **4.8** | 

Borde contra el relleno de la partícula (lenta, media, rápida): 4.6, 8.1, 13.7. Halo contra el anillo de lo varado: 5.0.

| Visión | ΔE vs tierra | ΔE vs mar | ΔE vs varado | ΔE vs su borde |
|---|---|---|---|---|
| visión normal | 100 | 96 | 81 | 98 |
| protanopía | 90 | 83 | 77 | 86 |
| deuteranopía | 80 | 73 | 83 | 77 |
| tritanopía | 59 | 72 | 52 | 72 |

## Calles

Fondos: tierra `#e6e5c9`, mar `#cedcd6`, tierra claro `#f7f7ed`, tierra oscuro `#aeb8a1`, mar claro `#cedcd6`, mar oscuro `#cedcd6`. Origen: teselas de zoom 10 clasificadas con la máscara de costa del modelo.

| Elemento | Color | Forma | Tierra | Mar | tierra claro | tierra oscuro | mar claro | mar oscuro |
|---|---|---|---|---|---|---|---|---|
| Partícula a flote, lenta | `#a44ab8` | cuadro relleno con borde | **3.9** | **3.5** | **4.6** | 2.4 | **3.5** | **3.5** |
| Partícula a flote, media | `#7d1a8c` | cuadro relleno con borde | **6.8** | **6.2** | **8.1** | **4.2** | **6.2** | **6.2** |
| Partícula a flote, rápida | `#470852` | cuadro relleno con borde | **11.5** | **10.4** | **13.7** | **7.1** | **10.4** | **10.4** |
| Densidad 0.2–1 % (línea de la trama) | `#c1bdca` | trama diagonal | 1.4 | 1.3 | 1.7 | 1.1 | 1.3 | 1.3 |
| Densidad 1–5 % (línea de la trama) | `#b6a2c0` | trama diagonal | 1.9 | 1.7 | 2.2 | 1.1 | 1.7 | 1.7 |
| Densidad 5–20 % (línea de la trama) | `#a983b4` | trama diagonal | 2.5 | 2.3 | 3.0 | 1.6 | 2.3 | 2.3 |
| Densidad ≥ 20 % (línea de la trama) | `#9c64a8` | trama diagonal | **3.4** | **3.1** | **4.1** | 2.1 | **3.1** | **3.1** |
| Zona con el 90 % (línea) | `#62326c` | línea fina | **7.5** | **6.7** | **8.8** | **4.6** | **6.7** | **6.7** |
| Varado | `#c0392b` | anillo hueco con halo | **4.2** | **3.8** | **5.0** | 2.6 | **3.8** | **3.8** |

Borde contra el relleno de la partícula (lenta, media, rápida): 4.6, 8.1, 13.7. Halo contra el anillo de lo varado: 5.0.

| Visión | ΔE vs tierra | ΔE vs mar | ΔE vs varado | ΔE vs su borde |
|---|---|---|---|---|
| visión normal | 100 | 92 | 81 | 98 |
| protanopía | 87 | 76 | 77 | 86 |
| deuteranopía | 77 | 65 | 83 | 77 |
| tritanopía | 67 | 69 | 52 | 72 |

## Satélite

Fondos: tierra `#223a35`, mar `#10223a`, tierra claro `#668267`, tierra oscuro `#172c2a`, mar claro `#1f6364`, mar oscuro `#0c1c36`. Origen: teselas de zoom 10 clasificadas con la máscara de costa del modelo.

| Elemento | Color | Forma | Tierra | Mar | tierra claro | tierra oscuro | mar claro | mar oscuro |
|---|---|---|---|---|---|---|---|---|
| Partícula a flote, lenta | `#ff7dec` | cuadro relleno con borde | **5.5** | **7.2** | 1.9 | **6.6** | **3.1** | **7.6** |
| Partícula a flote, media | `#ffaef4` | cuadro relleno con borde | **7.3** | **9.6** | 2.5 | **8.8** | **4.2** | **10.2** |
| Partícula a flote, rápida | `#ffe1fc` | cuadro relleno con borde | **10.1** | **13.3** | **3.5** | **12.2** | **5.8** | **14.1** |
| Densidad 0.2–1 % (línea de la trama) | `#363657` | trama diagonal | 1.1 | 1.4 | 2.7 | 1.3 | 1.7 | 1.5 |
| Densidad 1–5 % (línea de la trama) | `#584771` | trama diagonal | 1.5 | 1.9 | 1.9 | 1.8 | 1.2 | 2.1 |
| Densidad 5–20 % (línea de la trama) | `#7e5b8e` | trama diagonal | 2.2 | 2.9 | 1.3 | 2.6 | 1.2 | **3.0** |
| Densidad ≥ 20 % (línea de la trama) | `#a46eab` | trama diagonal | **3.1** | **4.1** | 1.1 | **3.8** | 1.8 | **4.4** |
| Zona con el 90 % (línea) | `#cfbbd5` | línea fina | **6.8** | **8.9** | 2.4 | **8.2** | **3.9** | **9.5** |
| Varado | `#ff5a36` | anillo hueco con halo | **3.9** | **5.2** | 1.4 | **4.7** | 2.2 | **5.5** |

Borde contra el relleno de la partícula (lenta, media, rápida): 8.3, 11.2, 15.4. Halo contra el anillo de lo varado: 6.0.

| Visión | ΔE vs tierra | ΔE vs mar | ΔE vs varado | ΔE vs su borde |
|---|---|---|---|---|
| visión normal | 81 | 78 | 82 | 79 |
| protanopía | 63 | 65 | 76 | 73 |
| deuteranopía | 64 | 70 | 80 | 76 |
| tritanopía | 72 | 80 | 61 | 79 |

## Lo que no llega a 3:1 y por qué

- **Las clases bajas de densidad** (menos de 5 % por celda) son tenues a propósito: poca opacidad es poco sargazo. La información de dónde hay sargazo la dan las partículas, que sí cumplen.
- **Sobre lo más claro del satélite** (playas, zonas urbanas y bajos de arena) el rosa claro pierde contraste de luminancia. Ahí cada partícula se distingue por su borde oscuro y por el tono, que no existe en la imagen.
- **Sobre lo más oscuro de las calles** (selva en verde) la partícula lenta, la más clara, queda cerca del mínimo; el borde claro la separa.
