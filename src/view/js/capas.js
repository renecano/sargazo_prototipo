// Capas del mapa con estilo de carta náutica: la carta propia (tierra y costa del modelo),
// retícula, densidad y zona P90, partículas con estela, flechas de oleaje y rótulos.
/* global L */
import { A_FLOTE, CELDA_DENSIDAD, CLASES_DENSIDAD, CLASES_RAPIDEZ_KN, HORAS_ESTELA, VARADA } from './datos.js';
import { MS_A_NUDOS } from './util.js';

// ---------------------------------------------------------------------------
// Paletas: tinta sobre papel (carta y calles) o trazo claro sobre imagen (satélite)
// ---------------------------------------------------------------------------
export const PALETAS = {
  carta: {
    tinta: '#1d3557', reticula: 'rgba(29, 53, 87, 0.16)', rotuloReticula: 'rgba(29, 53, 87, 0.55)',
    rotulo: '#1d3557', agua: '#2f6384', halo: 'rgba(251, 246, 234, 0.92)',
    ola: 'rgba(31, 92, 122, 0.78)', varada: '#c0392b',
    rapidez: ['#d6a531', '#a8740c', '#6a3f02'],                 // lenta, media, rápida
    densidad: [176, 125, 16], zona: '#1d3557', fondo: '#eef1ea',
  },
  satelite: {
    tinta: '#fbf6ea', reticula: 'rgba(251, 246, 234, 0.20)', rotuloReticula: 'rgba(251, 246, 234, 0.75)',
    rotulo: '#fffaf0', agua: '#bfe3f2', halo: 'rgba(8, 18, 32, 0.80)',
    ola: 'rgba(196, 232, 245, 0.92)', varada: '#ff6a5c',
    rapidez: ['#ffe9a3', '#ffc23d', '#ff8a1f'],
    densidad: [255, 196, 61], zona: '#fbf6ea', fondo: '#10263f',
  },
};
PALETAS.calles = PALETAS.carta;
export const paleta = (est) => PALETAS[est.base] || PALETAS.carta;

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
const TINTA_CARTA = {
  mar: [238, 241, 234], tierra: [232, 219, 181], contexto: [232, 219, 181],
  costa: [29, 53, 87], costaContexto: [138, 151, 168],
};

export function pintarCarta(ctx, costa, px0, py0, z, ancho, alto, dpr) {
  const escala = 256 * Math.pow(2, z);
  const W = ancho + 2, H = alto + 2;
  const lons = new Float64Array(W), lats = new Float64Array(H);
  for (let x = 0; x < W; x++) lons[x] = ((px0 + (x - 0.5) / dpr) / escala) * 360 - 180;
  for (let y = 0; y < H; y++) {
    const n = Math.PI - (2 * Math.PI * (py0 + (y - 0.5) / dpr)) / escala;
    lats[y] = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  }
  // En zoom lejano un píxel abarca muchas celdas: se toman 4 muestras y gana la tierra, para
  // que los cayos e islas angostas no desaparezcan.
  const gradosPx = 360 / (escala * dpr);
  const fino = gradosPx > 3 * costa.t.paso;
  const q = gradosPx / 4;
  const clases = new Uint8Array(W * H);
  for (let y = 0; y < H; y++) {
    const lat = lats[y], fila = y * W;
    for (let x = 0; x < W; x++) {
      const lon = lons[x];
      let c = costa.clase(lon, lat);
      if (fino && c === 0) {
        c = costa.clase(lon - q, lat - q) || costa.clase(lon + q, lat - q) || costa.clase(lon - q, lat + q) || costa.clase(lon + q, lat + q);
      }
      clases[fila + x] = c;
    }
  }
  const img = ctx.createImageData(ancho, alto);
  const d = img.data;
  const T = TINTA_CARTA;
  for (let y = 0; y < alto; y++) {
    for (let x = 0; x < ancho; x++) {
      const k = (y + 1) * W + (x + 1);
      const c = clases[k];
      let rgb = c === 0 ? T.mar : c === 1 ? T.tierra : T.contexto;
      if (c !== 0 && (clases[k - 1] === 0 || clases[k + 1] === 0 || clases[k - W] === 0 || clases[k + W] === 0)) {
        rgb = c === 1 ? T.costa : T.costaContexto;
      }
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
// Densidad (% del sargazo liberado por celda de 0.04°) y contorno de la zona P90.
// Nada se pinta sobre tierra: las celdas que tocan la costa se recortan con la máscara.
// ---------------------------------------------------------------------------
export function claseDensidad(pct) {
  let k = -1;
  while (k + 1 < CLASES_DENSIDAD.length && pct >= CLASES_DENSIDAD[k + 1]) k++;
  return k;
}

function soloMar(costa, lon, lat, lado) {
  if (!costa) return true;
  for (let a = 0; a <= 2; a++) for (let b = 0; b <= 2; b++) if (costa.enTierra(lon + (a * lado) / 2, lat + (b * lado) / 2)) return false;
  return true;
}

export function dibujarDensidad(ctx, c, est) {
  const { sim, costa } = est;
  if (!sim || !est.ver.densidad) return;
  const p = paleta(est);
  const d = sim.densidad(est.hora);
  const lado = CELDA_DENSIDAD;
  const [r, g, b] = p.densidad;
  const enZona = new Set(d.celdas.filter((k) => k.p90).map((k) => k.i * 4096 + k.j));
  const trazos = [];
  for (const celda of d.celdas) {
    const lon = sim.lon0 + celda.j * lado, lat = sim.lat0 + celda.i * lado;
    const x0 = c.x(lon), x1 = c.x(lon + lado), y0 = c.y(lat + lado), y1 = c.y(lat);
    if (x1 < 0 || y1 < 0 || x0 > c.ancho || y0 > c.alto) continue;
    const clase = claseDensidad(celda.pct);
    const n = Math.max(1, Math.min(24, Math.ceil((x1 - x0) / 4)));
    const entera = soloMar(costa, lon, lat, lado);
    if (clase >= 0) {
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${ALFA_DENSIDAD[clase]})`;
      if (entera) ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      else {
        const sub = lado / n;
        for (let a = 0; a < n; a++) {
          const ya = c.y(lat + (a + 1) * sub), yb = c.y(lat + a * sub);
          for (let q = 0; q < n; q++) {
            if (costa.enTierra(lon + (q + 0.5) * sub, lat + (a + 0.5) * sub)) continue;
            const xa = x0 + ((x1 - x0) * q) / n;
            ctx.fillRect(xa, ya, (x1 - x0) / n + 0.5, yb - ya + 0.5);
          }
        }
      }
    }
    if (!celda.p90) continue;
    // Lados de la celda que dan hacia fuera de la zona P90 (solo los tramos que están en el mar).
    const lados = [
      [celda.i + 1, celda.j, lon, lat + lado, lon + lado, lat + lado],
      [celda.i - 1, celda.j, lon, lat, lon + lado, lat],
      [celda.i, celda.j - 1, lon, lat, lon, lat + lado],
      [celda.i, celda.j + 1, lon + lado, lat, lon + lado, lat + lado],
    ];
    for (const [vi, vj, ax, ay, bx, by] of lados) {
      if (enZona.has(vi * 4096 + vj)) continue;
      for (let q = 0; q < n; q++) {
        const f0 = q / n, f1 = (q + 1) / n, fm = (q + 0.5) / n;
        if (costa && costa.enTierra(ax + (bx - ax) * fm, ay + (by - ay) * fm)) continue;
        trazos.push(c.x(ax + (bx - ax) * f0), c.y(ay + (by - ay) * f0), c.x(ax + (bx - ax) * f1), c.y(ay + (by - ay) * f1));
      }
    }
  }
  ctx.strokeStyle = p.zona;
  ctx.lineWidth = 1.4;
  ctx.setLineDash([6, 4]);
  ctx.beginPath();
  for (let k = 0; k < trazos.length; k += 4) { ctx.moveTo(trazos[k], trazos[k + 1]); ctx.lineTo(trazos[k + 2], trazos[k + 3]); }
  ctx.stroke();
  ctx.setLineDash([]);
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

const bufer = { n: 0, x: [], y: [], clase: null, flota: null };
function reservar(n) {
  if (bufer.n >= n) return;
  bufer.n = n;
  bufer.x = Array.from({ length: HORAS_ESTELA + 1 }, () => new Float32Array(n));
  bufer.y = Array.from({ length: HORAS_ESTELA + 1 }, () => new Float32Array(n));
  bufer.clase = new Uint8Array(n);
  bufer.flota = new Uint8Array(n);
}

export function dibujarParticulas(ctx, c, est) {
  const { sim } = est;
  if (!sim) return;
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
  est.dibujo = { aFlote, varadas, sobreTierra, radio, hora: t };

  ctx.lineCap = 'round';
  ctx.lineWidth = Math.max(1, radio * 0.75);
  for (let k = 0; k < 3; k++) {
    ctx.strokeStyle = p.rapidez[k];
    for (let s = 0; s < cuadros; s++) {
      ctx.globalAlpha = ALFA_ESTELA[s];
      ctx.beginPath();
      for (let n = 0; n < N; n++) {
        if (bufer.flota[n] !== 1 || bufer.clase[n] !== k) continue;
        ctx.moveTo(X[s][n], Y[s][n]);
        ctx.lineTo(X[s + 1][n], Y[s + 1][n]);
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 0.9;
    ctx.fillStyle = p.rapidez[est.ver.estelas ? k : 1];
    for (let n = 0; n < N; n++) {
      if (bufer.flota[n] !== 1 || bufer.clase[n] !== k) continue;
      ctx.fillRect(X[0][n] - radio, Y[0][n] - radio, 2 * radio, 2 * radio);
    }
  }
  ctx.globalAlpha = 1;
  // Varadas: anillo, para que no dependan solo del color.
  ctx.strokeStyle = p.varada;
  ctx.lineWidth = 1.3;
  ctx.beginPath();
  const ra = radio + 1.1;
  for (let n = 0; n < N; n++) {
    if (bufer.flota[n] !== 2) continue;
    ctx.moveTo(X[0][n] + ra, Y[0][n]);
    ctx.arc(X[0][n], Y[0][n], ra, 0, 2 * Math.PI);
  }
  ctx.stroke();
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
