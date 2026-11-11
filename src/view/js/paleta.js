// Paleta de la interfaz por mapa base. Es JSON estricto entre las dos marcas para que
// scripts/medir_contraste.py lea exactamente los mismos colores que usa el mapa.
//
// El sargazo va en púrpura sobre papel (carta y calles) y en rosa claro sobre la imagen de
// satélite: un tono que no existe en la tierra (ante, verde, gris) ni en el mar (crema, azul,
// turquesa) de ningún mapa base, y lejos del rojo de las varadas. Además del tono se usa la
// forma: cuadro relleno con borde para lo que flota, anillo hueco para lo varado y trama de
// líneas para la densidad. Los contrastes medidos están en docs/contraste.md.
//
// `sargazo` va de la partícula lenta a la rápida. `tierraCarta`, `marCarta`, `costaCarta` y
// `costaContexto` son los colores con que se pinta la carta propia.
export const PALETAS = /* paleta:inicio */ {
  "carta": {
    "tinta": "#1d3557", "reticula": "rgba(29, 53, 87, 0.16)", "rotuloReticula": "rgba(29, 53, 87, 0.55)",
    "rotulo": "#1d3557", "agua": "#2f6384", "halo": "rgba(251, 246, 234, 0.92)", "ola": "rgba(31, 92, 122, 0.78)",
    "sargazo": ["#a44ab8", "#7d1a8c", "#470852"], "bordeSargazo": "#fbf6ea",
    "densidad": "#7d1a8c", "zona": "#470852",
    "varada": "#c0392b", "haloVarada": "#fbf6ea",
    "fondo": "#eef1ea",
    "tierraCarta": [227, 211, 168], "marCarta": [238, 241, 234], "costaCarta": [29, 53, 87], "costaContexto": [138, 151, 168]
  },
  "calles": {
    "tinta": "#1d3557", "reticula": "rgba(29, 53, 87, 0.16)", "rotuloReticula": "rgba(29, 53, 87, 0.55)",
    "rotulo": "#1d3557", "agua": "#2f6384", "halo": "rgba(251, 246, 234, 0.92)", "ola": "rgba(31, 92, 122, 0.78)",
    "sargazo": ["#a44ab8", "#7d1a8c", "#470852"], "bordeSargazo": "#fbf6ea",
    "densidad": "#7d1a8c", "zona": "#470852",
    "varada": "#c0392b", "haloVarada": "#fbf6ea",
    "fondo": "#b9d3d4"
  },
  "satelite": {
    "tinta": "#fbf6ea", "reticula": "rgba(251, 246, 234, 0.20)", "rotuloReticula": "rgba(251, 246, 234, 0.75)",
    "rotulo": "#fffaf0", "agua": "#bfe3f2", "halo": "rgba(8, 18, 32, 0.80)", "ola": "rgba(196, 232, 245, 0.92)",
    "sargazo": ["#ff7dec", "#ffaef4", "#ffe1fc"], "bordeSargazo": "#1a0b2e",
    "densidad": "#ff9df1", "zona": "#ffe1fc",
    "varada": "#ff5a36", "haloVarada": "#1a0b2e",
    "fondo": "#10263f"
  }
} /* paleta:fin */;

export const paleta = (est) => PALETAS[est.base] || PALETAS.carta;

// "#rrggbb" → "rgba(r, g, b, a)"
export function conAlfa(hex, alfa) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alfa})`;
}
