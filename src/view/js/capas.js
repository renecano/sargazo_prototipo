// Capas del mapa con estilo de carta náutica: la carta propia (tierra y costa del modelo),
// retícula, densidad y zona P90, partículas con estela, flechas de oleaje y rótulos.
/* global L */
import { A_FLOTE, CELDA_DENSIDAD, CLASES_DENSIDAD, CLASES_RAPIDEZ_KN, HORAS_ESTELA, VARADA } from './datos.js';
import { conAlfa, paleta, PALETAS } from './paleta.js';
import { MS_A_NUDOS } from './util.js';

export { paleta, PALETAS };

export const PX_POR_METRO = 22;          // largo de la flecha de ola: 1 m de altura = 22 px, en cualquier zoom
const SEPARACION_MIN_PX = 34;            // las flechas fijas se dibujan en una submalla para no saturar
export const ALFA_DENSIDAD = [0.16, 0.30, 0.46, 0.62];
const ALFA_ESTELA = [0.50, 0.38, 0.28, 0.19, 0.12, 0.06];

// ---------------------------------------------------------------------------
// Capa canvas genérica anclada a un «pane». Se redibuja al terminar cada movimiento, acompaña
// la animación de zoom (no parpadea) y expone una proyección Web Mercator rápida.
// `margen` (px) agranda el lienzo alrededor de la vista para que al arrastrar no se vea el borde.
// ---------------------------------------------------------------------------
export const CapaCanvas = L.Layer.extend({
  initialize(opciones) {
    L.setOptions(this, opciones);
    this.dibujar = opciones.dibujar || (() => {});
    this.mg = opciones.margen || 0;
  },
  onAdd(mapa) {
    this._mapa = mapa;
    this.canvas = L.DomUtil.create('canvas', 'capa-canvas leaflet-zoom-animated');
    this.canvas.dataset.capa = this.options.nombre || '';
    mapa.getPane(this.options.pane).appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    mapa.on('moveend resize zoomend viewreset', this.reiniciar, this);
    if (mapa.options.zoomAnimation && L.Browser.any3d) mapa.on('zoomanim', this._animarZoom, this);
    this.reiniciar();
  },
  onRemove(mapa) {
    mapa.off('moveend resize zoomend viewreset', this.reiniciar, this);
    mapa.off('zoomanim', this._animarZoom, this);
    this.canvas.remove();
  },
  _animarZoom(e) {
    const escala = this._mapa.getZoomScale(e.zoom, this.zoom);
    const posicion = this._mapa._latLngToNewLayerPoint(this._esquina, e.zoom, e.center);
    L.DomUtil.setTransform(this.canvas, posicion, escala);
  },
  reiniciar() {
    const m = this._mapa;
    const tam = m.getSize();
    const dpr = window.devicePixelRatio || 1;
    const mg = this.mg;
    this.origen = m.containerPointToLayerPoint([-mg, -mg]);
    this._esquina = m.containerPointToLatLng([-mg, -mg]);
    L.DomUtil.setPosition(this.canvas, this.origen);
    this.ancho = tam.x + 2 * mg;
    this.alto = tam.y + 2 * mg;
    this.canvas.width = Math.round(this.ancho * dpr);
    this.canvas.height = Math.round(this.alto * dpr);
    this.canvas.style.width = `${this.ancho}px`;
    this.canvas.style.height = `${this.alto}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.vistaAncho = tam.x;
    this.vistaAlto = tam.y;
    this.zoom = m.getZoom();
    this.escala = 256 * Math.pow(2, this.zoom);
    const po = m.getPixelOrigin();
    this.dx = -po.x - this.origen.x;
    this.dy = -po.y - this.origen.y;
    this.redibujar();
  },
  // Coordenadas del lienzo (la vista empieza en `mg`, `mg`).
  x(lon) { return ((lon + 180) / 360) * this.escala + this.dx; },
  y(lat) {
    const s = Math.sin((lat * Math.PI) / 180);
    return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * this.escala + this.dy;
  },
  lon(x) { return ((x - this.dx) / this.escala) * 360 - 180; },
  lat(y) {
    const n = Math.PI - (2 * Math.PI * (y - this.dy)) / this.escala;
    return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  },
  redibujar() {
    if (!this.ctx) return;
    this.ctx.clearRect(0, 0, this.ancho, this.alto);
    this.dibujar(this.ctx, this);
  },
});

// ---------------------------------------------------------------------------
// Carta propia: mar, tierra y línea de costa pintados píxel a píxel con la máscara del modelo.
// La costa que se ve ES la costa con la que el modelo decide qué vara. No usa internet.
// ---------------------------------------------------------------------------
// Dos reglas para que la tierra angosta se vea (la barra de Isla Blanca, al norte de Cancún,
// mide 300 m en su parte más delgada; Isla Contoy, 400 m):
//  1. Cobertura. Cada píxel se muestrea en tantos puntos como celdas de la máscara abarca
//     (hasta 4 × 4): si alguno es tierra, el píxel es tierra. Una franja de una celda no se
//     pierde entre dos muestras.
//  2. Grosor mínimo. Una franja de 1 o 2 píxeles de ancho (medida en horizontal o en vertical)
//     se pintaría entera con la tinta de la línea de costa y parecería una raya, no tierra. En
//     ese caso el píxel se rellena de tierra y la línea de costa se traza por fuera, en el
//     píxel de mar contiguo: la franja queda de al menos 3 píxeles (tinta, tierra, tinta),
//     exagerada en un píxel por lado.
export const MUESTRAS_MAX = 4;

export function pintarCarta(ctx, costa, px0, py0, z, ancho, alto, dpr) {
  const escala = 256 * Math.pow(2, z);
  const B = 3;                                       // borde: hasta 2 vecinos para medir el grosor, más 1
  const W = ancho + 2 * B, H = alto + 2 * B;
  const gradosPx = 360 / (escala * dpr);
  const n = Math.max(1, Math.min(MUESTRAS_MAX, Math.ceil(gradosPx / costa.t.paso)));
  const lons = new Float64Array(W * n), lats = new Float64Array(H * n);
  for (let x = 0; x < W; x++) {
    for (let a = 0; a < n; a++) lons[x * n + a] = ((px0 + (x - B + (a + 0.5) / n) / dpr) / escala) * 360 - 180;
  }
  for (let y = 0; y < H; y++) {
    for (let a = 0; a < n; a++) {
      const m = Math.PI - (2 * Math.PI * (py0 + (y - B + (a + 0.5) / n) / dpr)) / escala;
      lats[y * n + a] = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(m) - Math.exp(-m)));
    }
  }
  // Clase de cada píxel: 0 mar, 1 tierra del modelo, 2 tierra de contexto. Gana la tierra.
  const clases = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      let c = 0;
      for (let a = 0; a < n && c !== 1; a++) {
        const lat = lats[y * n + a];
        for (let b = 0; b < n; b++) {
          const k = costa.clase(lons[x * n + b], lat);
          if (k === 1) { c = 1; break; }
          if (k === 2) c = 2;
        }
      }
      clases[y * W + x] = c;
    }
  }
  // Delgada: tierra cuya franja mide 1 o 2 píxeles de ancho, en horizontal o en vertical.
  const delgada = new Uint8Array(W * H);
  for (let y = 2; y < H - 2; y++) {
    for (let x = 2; x < W - 2; x++) {
      const k = y * W + x;
      if (!clases[k]) continue;
      const horizontal = 1 + (clases[k - 1] ? (clases[k - 2] ? 2 : 1) : 0) + (clases[k + 1] ? (clases[k + 2] ? 2 : 1) : 0);
      const vertical = 1 + (clases[k - W] ? (clases[k - 2 * W] ? 2 : 1) : 0) + (clases[k + W] ? (clases[k + 2 * W] ? 2 : 1) : 0);
      if (horizontal <= 2 || vertical <= 2) delgada[k] = 1;
    }
  }
  const T = PALETAS.carta;
  const img = ctx.createImageData(ancho, alto);
  const d = img.data;
  for (let y = 0; y < alto; y++) {
    for (let x = 0; x < ancho; x++) {
      const k = (y + B) * W + (x + B);
      const c = clases[k];
      let rgb;
      if (c === 0) {
        const vecina = delgada[k - 1] ? clases[k - 1] : delgada[k + 1] ? clases[k + 1] : delgada[k - W] ? clases[k - W] : delgada[k + W] ? clases[k + W] : 0;
        rgb = vecina === 1 ? T.costaCarta : vecina === 2 ? T.costaContexto : T.marCarta;
      } else if (!delgada[k] && (clases[k - 1] === 0 || clases[k + 1] === 0 || clases[k - W] === 0 || clases[k + W] === 0)) {
        rgb = c === 1 ? T.costaCarta : T.costaContexto;
      } else rgb = T.tierraCarta;
      const o = (y * ancho + x) * 4;
      d[o] = rgb[0]; d[o + 1] = rgb[1]; d[o + 2] = rgb[2]; d[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

export const CapaCarta = L.GridLayer.extend({
  options: { costa: null, updateWhenZooming: false, keepBuffer: 2 },
  createTile(coords) {
    const tam = this.getTileSize();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const lienzo = L.DomUtil.create('canvas', 'leaflet-tile');
    lienzo.width = Math.round(tam.x * dpr);
    lienzo.height = Math.round(tam.y * dpr);
    pintarCarta(lienzo.getContext('2d'), this.options.costa, coords.x * tam.x, coords.y * tam.y, coords.z,
      lienzo.width, lienzo.height, dpr);
    return lienzo;
  },
});

// ---------------------------------------------------------------------------
// Retícula con rótulos en el borde, como en una carta náutica
// ---------------------------------------------------------------------------
export function dibujarReticula(ctx, c, est) {
  const p = paleta(est);
  const oeste = Math.floor(c.lon(0) / 5) * 5, este = Math.ceil(c.lon(c.ancho));
  const norte = Math.ceil(c.lat(0)), sur = Math.floor(c.lat(c.alto) / 5) * 5;
  const pxPorGrado = c.escala / 360;
  const paso = [0.25, 0.5, 1, 2, 5].find((v) => v * pxPorGrado >= 80) || 5;
  ctx.strokeStyle = p.reticula;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let lon = oeste; lon <= este; lon += paso) {
    const x = Math.round(c.x(lon)) + 0.5;
    ctx.moveTo(x, 0); ctx.lineTo(x, c.alto);
  }
  for (let lat = sur; lat <= norte; lat += paso) {
    const y = Math.round(c.y(lat)) + 0.5;
    ctx.moveTo(0, y); ctx.lineTo(c.ancho, y);
  }
  ctx.stroke();
  ctx.fillStyle = p.rotuloReticula;
  ctx.font = '10px "IBM Plex Mono", Consolas, monospace';
  ctx.textBaseline = 'middle';
  const dec = paso < 1 ? (paso < 0.5 ? 2 : 1) : 0;
  for (let lat = sur; lat <= norte; lat += paso) {
    const y = c.y(lat);
    if (y < 150 || y > c.alto - 190) continue;      // deja libres la cabecera y la leyenda
    ctx.fillText(`${Math.abs(lat).toFixed(dec)}°${lat >= 0 ? 'N' : 'S'}`, c.ancho - 50, y - 7);
  }
  for (let lon = oeste; lon <= este; lon += paso) {
    const x = c.x(lon);
    if (x < 380 || x > c.ancho - 330) continue;
    ctx.fillText(`${Math.abs(lon).toFixed(dec)}°${lon >= 0 ? 'E' : 'O'}`, x + 4, c.alto - 92);
  }
}

// ---------------------------------------------------------------------------
// Densidad (% del sargazo liberado por celda de 0.04°) y zona con el 90 %.
//
// No se pintan cuadros: el valor de cada celda se interpola hacia sus vecinas, de modo que la
// mancha tiene bordes suaves; lleva una trama de líneas diagonales (textura, no solo color)
// y se recorta píxel a píxel con la máscara de costa. La zona con el 90 % es una línea fina
// achaflanada, sin esquinas rectas.
// ---------------------------------------------------------------------------
export function claseDensidad(pct) {
  let k = -1;
  while (k + 1 < CLASES_DENSIDAD.length && pct >= CLASES_DENSIDAD[k + 1]) k++;
  return k;
}

const LADO_MAX_PX = 1400;          // tope del lienzo auxiliar de la densidad
let trama = null;
function tramaDiagonal() {
  if (trama) return trama;
  trama = document.createElement('canvas');
  trama.width = trama.height = 6;
  const g = trama.getContext('2d');
  g.fillStyle = 'rgba(0, 0, 0, 0.46)';              // entre líneas queda el 46 % de la opacidad
  g.fillRect(0, 0, 6, 6);
  g.strokeStyle = '#000';
  g.lineWidth = 1.6;
  g.beginPath();
  for (const k of [-6, 0, 6]) { g.moveTo(k - 1, 7); g.lineTo(k + 7, -1); }
  g.stroke();
  return trama;
}

// Contorno a medio camino (0.5) de un campo 0…1 dado en los centros de celda: «marching
// squares» con interpolación lineal. Devuelve segmentos [i0, j0, i1, j1] en índices de celda.
export function contorno(campo, nx, ny) {
  const seg = [];
  const corte = (a, b) => (0.5 - a) / (b - a);
  for (let i = 0; i < ny - 1; i++) {
    for (let j = 0; j < nx - 1; j++) {
      const a = campo[i * nx + j], b = campo[i * nx + j + 1], c = campo[(i + 1) * nx + j + 1], d = campo[(i + 1) * nx + j];
      const caso = (a >= 0.5 ? 1 : 0) | (b >= 0.5 ? 2 : 0) | (c >= 0.5 ? 4 : 0) | (d >= 0.5 ? 8 : 0);
      if (caso === 0 || caso === 15) continue;
      const S = [i, j + corte(a, b)], E = [i + corte(b, c), j + 1], N = [i + 1, j + corte(d, c)], O = [i + corte(a, d), j];
      const une = (p, q) => seg.push(p[0], p[1], q[0], q[1]);
      switch (caso) {
        case 1: case 14: une(O, S); break;
        case 2: case 13: une(S, E); break;
        case 3: case 12: une(O, E); break;
        case 4: case 11: une(E, N); break;
        case 6: case 9: une(S, N); break;
        case 7: case 8: une(O, N); break;
        case 5: une(O, S); une(E, N); break;
        default: une(S, E); une(O, N); break;        // caso 10
      }
    }
  }
  return seg;
}

export function dibujarDensidad(ctx, c, est) {
  const { sim, costa } = est;
  est.densidadDibujada = null;
  if (!sim || !est.ver.densidad) return;
  const d = sim.densidad(est.hora);
  if (!d.celdas.length) return;
  const p = paleta(est);
  const lado = CELDA_DENSIDAD, M = 2;                // margen de 2 celdas para que el borde se desvanezca
  let i0 = Infinity, i1 = -Infinity, j0 = Infinity, j1 = -Infinity;
  for (const k of d.celdas) { i0 = Math.min(i0, k.i); i1 = Math.max(i1, k.i); j0 = Math.min(j0, k.j); j1 = Math.max(j1, k.j); }
  i0 -= M; j0 -= M; i1 += M; j1 += M;
  const nx = j1 - j0 + 1, ny = i1 - i0 + 1;
  // Recuadro de la malla en pantalla y su parte visible.
  const xa = c.x(sim.lon0 + j0 * lado), xb = c.x(sim.lon0 + (j1 + 1) * lado);
  const ya = c.y(sim.lat0 + (i1 + 1) * lado), yb = c.y(sim.lat0 + i0 * lado);
  const X0 = Math.max(0, Math.floor(xa)), X1 = Math.min(c.ancho, Math.ceil(xb));
  const Y0 = Math.max(0, Math.floor(ya)), Y1 = Math.min(c.alto, Math.ceil(yb));
  if (X1 <= X0 || Y1 <= Y0) return;

  // 1. Campo de opacidad: un píxel por celda (fila 0 al norte), escalado con suavizado.
  const chico = document.createElement('canvas');
  chico.width = nx; chico.height = ny;
  const gc = chico.getContext('2d');
  const img = gc.createImageData(nx, ny);
  const n = parseInt(p.densidad.slice(1), 16);
  for (let k = 0; k < nx * ny; k++) { img.data[4 * k] = (n >> 16) & 255; img.data[4 * k + 1] = (n >> 8) & 255; img.data[4 * k + 2] = n & 255; }
  const zona = new Float32Array(nx * ny);
  for (const k of d.celdas) {
    const clase = claseDensidad(k.pct);
    const q = (i1 - k.i) * nx + (k.j - j0);
    if (clase >= 0) img.data[4 * q + 3] = Math.round(255 * ALFA_DENSIDAD[clase]);
    if (k.p90) zona[(k.i - i0) * nx + (k.j - j0)] = 1;
  }
  gc.putImageData(img, 0, 0);

  const dpr = Math.min(window.devicePixelRatio || 1, LADO_MAX_PX / Math.max(X1 - X0, Y1 - Y0));
  const w = Math.max(1, Math.round((X1 - X0) * dpr)), h = Math.max(1, Math.round((Y1 - Y0) * dpr));
  const grande = document.createElement('canvas');
  grande.width = w; grande.height = h;
  const g = grande.getContext('2d', { willReadFrequently: true });
  g.imageSmoothingEnabled = true;
  g.imageSmoothingQuality = 'high';
  g.drawImage(chico, (xa - X0) * dpr, (ya - Y0) * dpr, (xb - xa) * dpr, (yb - ya) * dpr);
  // 2. Trama diagonal: textura además de color.
  g.globalCompositeOperation = 'destination-in';
  g.fillStyle = g.createPattern(tramaDiagonal(), 'repeat');
  g.fillRect(0, 0, w, h);
  g.globalCompositeOperation = 'source-over';
  // 3. Recorte a la costa: ningún píxel de tierra conserva opacidad.
  let pintados = 0, recortados = 0;
  if (costa) {
    const datos = g.getImageData(0, 0, w, h);
    const px = datos.data;
    const lons = new Float64Array(w);
    for (let x = 0; x < w; x++) lons[x] = c.lon(X0 + (x + 0.5) / dpr);
    for (let y = 0; y < h; y++) {
      const lat = c.lat(Y0 + (y + 0.5) / dpr);
      for (let x = 0; x < w; x++) {
        const o = 4 * (y * w + x) + 3;
        if (!px[o]) continue;
        if (costa.enTierra(lons[x], lat)) { px[o] = 0; recortados++; } else pintados++;
      }
    }
    g.putImageData(datos, 0, 0);
  }
  ctx.drawImage(grande, X0, Y0, X1 - X0, Y1 - Y0);

  // 4. Zona con el 90 %: contorno fino a medio camino entre las celdas de la zona y sus vecinas
  // (sale achaflanado, sin esquinas rectas, y encierra también una franja de una sola celda).
  // Solo se traza sobre el mar.
  const seg = contorno(zona, nx, ny);
  const lon = (j) => sim.lon0 + (j0 + j + 0.5) * lado, lat = (i) => sim.lat0 + (i0 + i + 0.5) * lado;
  ctx.strokeStyle = conAlfa(p.zona, 0.8);
  ctx.lineWidth = 1.1;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  let tramos = 0;
  for (let k = 0; k < seg.length; k += 4) {
    const la0 = lat(seg[k]), lo0 = lon(seg[k + 1]), la1 = lat(seg[k + 2]), lo1 = lon(seg[k + 3]);
    if (costa && costa.enTierra((lo0 + lo1) / 2, (la0 + la1) / 2)) continue;
    ctx.moveTo(c.x(lo0), c.y(la0));
    ctx.lineTo(c.x(lo1), c.y(la1));
    tramos++;
  }
  ctx.stroke();
  est.densidadDibujada = { celdas: d.celdas.length, pintados, recortados, tramosZona: tramos, rect: [X0, Y0, X1, Y1] };
}

// ---------------------------------------------------------------------------
// Partículas: posición interpolada entre horas, estela de las últimas horas (más larga y más
// oscura = más rápida) y anillo para las varadas. El tamaño del símbolo sigue al zoom.
// ---------------------------------------------------------------------------
export function radioParticula(zoom) {
  return Math.max(0.8, Math.min(2.0, 0.8 + (zoom - 6) * 0.22));
}
export function claseRapidez(ms) {
  const kn = ms * MS_A_NUDOS;
  return kn < CLASES_RAPIDEZ_KN[0] ? 0 : kn < CLASES_RAPIDEZ_KN[1] ? 1 : 2;
}

// Detalle de las estelas: en cuántos tramos de opacidad se parte cada una. Lo caro no es el
// JavaScript sino el trazado del lienzo, que el navegador hace después: por eso se mide el
// tiempo entre cuadros seguidos (reproducción o arrastre del deslizador). Si pasa de 45 ms
// (menos de ~22 cuadros/s) se baja un nivel; si se sostiene por debajo de 20 ms, se sube. Un
// cuadro aislado (pausa) siempre se dibuja completo.
const NIVELES_ESTELA = [6, 3, 2, 1];
const MS_BAJAR = 45, MS_SUBIR = 20, MS_SEGUIDO = 300, CUADROS_PARA_BAJAR = 4, CUADROS_PARA_SUBIR = 45;
const bufer = { n: 0, x: [], y: [], clase: null, flota: null, nivel: 0, periodo: 0, enNivel: 0, ultimo: 0, anillo: null, claveAnillo: '' };
function reservar(n) {
  if (bufer.n >= n) return;
  bufer.n = n;
  bufer.x = Array.from({ length: HORAS_ESTELA + 1 }, () => new Float32Array(n));
  bufer.y = Array.from({ length: HORAS_ESTELA + 1 }, () => new Float32Array(n));
  bufer.clase = new Uint8Array(n);
  bufer.flota = new Uint8Array(n);
}

// El siguiente cuadro se dibuja con las estelas completas (al pausar o al dejar de arrastrar).
export function estelasCompletas() { bufer.ultimo = 0; }
export const TRAMOS_ESTELA_COMPLETA = NIVELES_ESTELA[0];

// El anillo de «varada» se pinta una vez en un lienzo pequeño y se estampa: miles de arcos por
// cuadro son lo más caro de dibujar cuando casi todo el sargazo ya llegó a la costa.
function selloAnillo(color, halo, radio) {
  const dpr = window.devicePixelRatio || 1;
  const clave = `${color}|${halo}|${radio.toFixed(2)}|${dpr}`;
  if (bufer.claveAnillo === clave) return bufer.anillo;
  const lado = Math.ceil(2 * radio + 6);
  const lienzo = document.createElement('canvas');
  lienzo.width = lienzo.height = Math.ceil(lado * dpr);
  const g = lienzo.getContext('2d');
  g.scale(dpr, dpr);
  // Halo del color contrario al mapa y, encima, el anillo: se lee sobre tierra, mar o sargazo.
  for (const [trazo, grosor] of [[halo, 3.2], [color, 1.5]]) {
    g.strokeStyle = trazo;
    g.lineWidth = grosor;
    g.beginPath();
    g.arc(lado / 2, lado / 2, radio, 0, 2 * Math.PI);
    g.stroke();
  }
  bufer.anillo = { lienzo, lado };
  bufer.claveAnillo = clave;
  return bufer.anillo;
}

export function dibujarParticulas(ctx, c, est) {
  const { sim } = est;
  if (!sim) return;
  const inicio = performance.now();
  const seguido = inicio - bufer.ultimo < MS_SEGUIDO;
  if (!seguido) { bufer.nivel = 0; bufer.enNivel = 0; bufer.periodo = 0; } else {
    bufer.periodo = bufer.periodo ? 0.7 * bufer.periodo + 0.3 * (inicio - bufer.ultimo) : inicio - bufer.ultimo;
    bufer.enNivel++;
    if (bufer.periodo > MS_BAJAR && bufer.enNivel > CUADROS_PARA_BAJAR && bufer.nivel < NIVELES_ESTELA.length - 1) {
      bufer.nivel++; bufer.enNivel = 0; bufer.periodo = 0;
    } else if (bufer.periodo < MS_SUBIR && bufer.enNivel > CUADROS_PARA_SUBIR && bufer.nivel > 0) {
      bufer.nivel--; bufer.enNivel = 0; bufer.periodo = 0;
    }
  }
  bufer.ultimo = inicio;
  const p = paleta(est);
  const t = est.hora, N = sim.N;
  const h0 = Math.min(sim.H, Math.floor(t));
  const radio = radioParticula(c.zoom);
  reservar(N);
  const pos = [0, 0], vel = [0, 0];
  const X = bufer.x, Y = bufer.y;
  let aFlote = 0, varadas = 0, sobreTierra = 0;
  // Cuadro 0: posición actual (interpolada). Cuadros 1…: horas guardadas h0, h0 − 1, …
  const cuadros = est.ver.estelas ? Math.min(HORAS_ESTELA, h0 + 1) : 0;
  for (let n = 0; n < N; n++) {
    const e = sim.estado(n, t);
    bufer.flota[n] = e === A_FLOTE ? 1 : e === VARADA ? 2 : 0;
    if (!bufer.flota[n]) continue;
    if (e === A_FLOTE) sim.posVisible(n, t, pos, est.costa); else sim.pos(n, t, pos);
    X[0][n] = c.x(pos[0]);
    Y[0][n] = c.y(pos[1]);
    if (est.costa && est.costa.enTierra(pos[0], pos[1])) sobreTierra++;
    if (e !== A_FLOTE) { varadas++; continue; }
    aFlote++;
    sim.velocidad(n, t, vel);
    bufer.clase[n] = claseRapidez(Math.hypot(vel[0], vel[1]));
    for (let s = 1; s <= cuadros; s++) {
      const o = (h0 - s + 1) * N + n;
      X[s][n] = c.x(sim.lon[o]);
      Y[s][n] = c.y(sim.lat[o]);
    }
  }

  // Estelas: cada tramo de opacidad es una polilínea por partícula, en un solo trazo por clase.
  const tramos = Math.min(NIVELES_ESTELA[bufer.nivel], cuadros);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.lineWidth = Math.max(1, radio * 0.75);
  // Borde de cada partícula a flote, del color contrario al mapa: la separa de la tierra, del
  // mar y de la densidad aunque no se distinga el tono.
  const borde = radio + 0.9;
  ctx.fillStyle = p.bordeSargazo;
  ctx.globalAlpha = 0.85;
  for (let n = 0; n < N; n++) {
    if (bufer.flota[n] === 1) ctx.fillRect(X[0][n] - borde, Y[0][n] - borde, 2 * borde, 2 * borde);
  }
  for (let k = 0; k < 3; k++) {
    ctx.strokeStyle = p.sargazo[k];
    for (let g = 0; g < tramos; g++) {
      const s0 = Math.floor((g * cuadros) / tramos), s1 = Math.floor(((g + 1) * cuadros) / tramos);
      let alfa = 0;
      for (let q = s0; q < s1; q++) alfa += ALFA_ESTELA[q];
      ctx.globalAlpha = alfa / (s1 - s0);
      ctx.beginPath();
      for (let n = 0; n < N; n++) {
        if (bufer.flota[n] !== 1 || bufer.clase[n] !== k) continue;
        ctx.moveTo(X[s0][n], Y[s0][n]);
        for (let q = s0 + 1; q <= s1; q++) ctx.lineTo(X[q][n], Y[q][n]);
      }
      ctx.stroke();
    }
  }
  // Los cuadros van al final, encima de todas las estelas.
  ctx.globalAlpha = 1;
  for (let k = 0; k < 3; k++) {
    ctx.fillStyle = p.sargazo[est.ver.estelas ? k : 1];
    for (let n = 0; n < N; n++) {
      if (bufer.flota[n] !== 1 || bufer.clase[n] !== k) continue;
      ctx.fillRect(X[0][n] - radio, Y[0][n] - radio, 2 * radio, 2 * radio);
    }
  }
  // Varadas: anillo, para que no dependan solo del color.
  if (varadas) {
    const { lienzo, lado } = selloAnillo(p.varada, p.haloVarada, radio + 1.6);
    for (let n = 0; n < N; n++) {
      if (bufer.flota[n] === 2) ctx.drawImage(lienzo, X[0][n] - lado / 2, Y[0][n] - lado / 2, lado, lado);
    }
  }

  est.dibujo = { aFlote, varadas, sobreTierra, radio, hora: t, tramosEstela: tramos, ms: performance.now() - inicio };
}

// ---------------------------------------------------------------------------
// Oleaje fijo: una flecha por nodo con dato, HACIA donde viaja la ola. El largo es la altura
// a escala (PX_POR_METRO), sin mínimos: la referencia «1 m» vale en cualquier zoom.
// ---------------------------------------------------------------------------
export function trazarFlecha(ctx, xc, yc, ux, uy, largo) {
  const xa = xc - ux * largo * 0.5, ya = yc - uy * largo * 0.5;
  const xp = xc + ux * largo * 0.5, yp = yc + uy * largo * 0.5;
  const punta = Math.min(5, largo * 0.45), ala = punta * 0.52;
  ctx.moveTo(xa, ya); ctx.lineTo(xp, yp);
  ctx.moveTo(xp - ux * punta - uy * ala, yp - uy * punta + ux * ala);
  ctx.lineTo(xp, yp);
  ctx.lineTo(xp - ux * punta + uy * ala, yp - uy * punta - ux * ala);
}

export function dibujarOleajeFijo(ctx, c, est) {
  const { campos, hora } = est;
  est.flechas = [];
  if (!campos || !est.ver.oleaje) return;
  const pxNodo = Math.abs(c.x(campos.lon0 + campos.dlon) - c.x(campos.lon0));
  const paso = Math.max(1, Math.ceil(SEPARACION_MIN_PX / pxNodo));
  const o = new Float64Array(3);
  ctx.strokeStyle = paleta(est).ola;
  ctx.lineWidth = 1.25;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  for (let i = 0; i < campos.ny; i += paso) {
    for (let j = 0; j < campos.nx; j += paso) {
      if (!campos.nodoConDato(i, j, hora)) continue;
      const lon = campos.lon0 + j * campos.dlon, lat = campos.lat0 + i * campos.dlat;
      const xc = c.x(lon), yc = c.y(lat);
      if (xc < -40 || yc < -40 || xc > c.ancho + 40 || yc > c.alto + 40) continue;
      if (!campos.muestrear(lon, lat, hora, o) || o[0] < 0.02) continue;
      const largo = o[0] * PX_POR_METRO;
      trazarFlecha(ctx, xc, yc, o[1], -o[2], largo);          // en pantalla el norte es −y
      est.flechas.push({ lon, lat, altura: o[0], largo });
    }
  }
  ctx.stroke();
}

// ---------------------------------------------------------------------------
// Rótulos de localidades: aparecen según el zoom y su rango, sin encimarse.
// ---------------------------------------------------------------------------
const ZOOM_MINIMO = { 1: 0, 2: 7.5, 3: 9, 4: 10.5 };
const AGUA = new Set(['bay', 'strait', 'reef', 'archipelago']);
const TAMANO = { 1: 12.5, 2: 11.5, 3: 11, 4: 10.5 };

function choca(a, cajas) {
  for (const b of cajas) if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) return true;
  return false;
}

export function dibujarRotulos(ctx, c, est) {
  est.rotulos = [];
  if (!est.localidades || !est.ver.localidades) return;
  const p = paleta(est);
  const cajas = [];
  ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round';
  for (const l of est.localidades) {
    const zmin = AGUA.has(l.tipo) ? Math.max(8, ZOOM_MINIMO[l.rango]) : ZOOM_MINIMO[l.rango];
    if (c.zoom < zmin) continue;
    const x = c.x(l.lon), y = c.y(l.lat);
    if (x < -20 || y < -20 || x > c.ancho + 20 || y > c.alto + 20) continue;
    const agua = AGUA.has(l.tipo), isla = l.tipo === 'island' || l.tipo === 'islet' || l.tipo === 'cape';
    const tam = TAMANO[l.rango];
    ctx.font = `${agua || isla ? 'italic ' : ''}${l.rango === 1 ? 600 : 500} ${tam}px "IBM Plex Sans", "Segoe UI", sans-serif`;
    const w = ctx.measureText(l.nombre).width, h = tam + 4;
    const punto = agua || isla ? 0 : 3.2;
    // Candidatos: a la derecha, a la izquierda, arriba y abajo del punto (centrado si no hay punto).
    const candidatos = punto
      ? [{ x: x + 7, y: y - h / 2 }, { x: x - 7 - w, y: y - h / 2 }, { x: x - w / 2, y: y - h - 5 }, { x: x - w / 2, y: y + 5 }]
      : [{ x: x - w / 2, y: y - h / 2 }];
    const marca = { x: x - 5, y: y - 5, w: 10, h: 10 };
    if (punto && choca(marca, cajas)) continue;
    const libre = candidatos.map((k) => ({ x: k.x - 2, y: k.y - 1, w: w + 4, h: h + 2 })).find((k) => !choca(k, cajas));
    if (!libre) continue;
    cajas.push(libre);
    if (punto) cajas.push(marca);
    if (punto) {
      ctx.fillStyle = p.halo;
      ctx.strokeStyle = p.rotulo;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      if (l.puerto) { ctx.moveTo(x, y - 4.2); ctx.lineTo(x + 4.2, y); ctx.lineTo(x, y + 4.2); ctx.lineTo(x - 4.2, y); ctx.closePath(); }
      else ctx.arc(x, y, punto, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
    }
    ctx.lineWidth = 3;
    ctx.strokeStyle = p.halo;
    ctx.strokeText(l.nombre, libre.x + 2, libre.y + 1 + h / 2);
    ctx.fillStyle = agua ? p.agua : p.rotulo;
    ctx.fillText(l.nombre, libre.x + 2, libre.y + 1 + h / 2);
    est.rotulos.push({ nombre: l.nombre, tipo: l.tipo, rango: l.rango, puerto: !!l.puerto, x: libre.x, y: libre.y, w: libre.w, h: libre.h });
  }
}

// ---------------------------------------------------------------------------
// Barra de escala doble (km y millas náuticas) que sigue al zoom y a la latitud.
// ---------------------------------------------------------------------------
function redondo(maximo) {
  const p = Math.pow(10, Math.floor(Math.log10(maximo)));
  const f = maximo / p;
  return (f >= 5 ? 5 : f >= 2 ? 2 : 1) * p;
}

export function medirEscala(mapa, anchoMaxPx = 120) {
  const tam = mapa.getSize();
  const y = tam.y / 2;
  const metrosPorPx = mapa.distance(mapa.containerPointToLatLng([tam.x / 2 - 50, y]), mapa.containerPointToLatLng([tam.x / 2 + 50, y])) / 100;
  const km = redondo((metrosPorPx * anchoMaxPx) / 1000);
  const mn = redondo((metrosPorPx * anchoMaxPx) / 1852);
  return { metrosPorPx, km, mn, pxKm: (km * 1000) / metrosPorPx, pxMn: (mn * 1852) / metrosPorPx };
}
