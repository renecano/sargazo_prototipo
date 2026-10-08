// Capas canvas sobre Leaflet: sargazo (densidad por celda de 0.16°, zona P90 y partículas) y malla.
/* global L */
import { A_FLOTE, VARADA } from './datos.js';

// Capa canvas genérica anclada a un "pane" del mapa. Se reubica al terminar cada
// movimiento y expone una proyección Web Mercator rápida para miles de puntos.
export const CapaCanvas = L.Layer.extend({
  initialize(opciones) {
    L.setOptions(this, opciones);
    this.dibujar = opciones.dibujar || (() => {});
  },
  onAdd(mapa) {
    this._mapa = mapa;
    this.canvas = L.DomUtil.create('canvas', 'capa-canvas');
    this.canvas.dataset.capa = this.options.nombre || '';
    mapa.getPane(this.options.pane).appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    mapa.on('moveend resize zoomend viewreset', this.reiniciar, this);
    mapa.on('zoomstart', this._ocultar, this);
    this.reiniciar();
  },
  onRemove(mapa) {
    mapa.off('moveend resize zoomend viewreset', this.reiniciar, this);
    mapa.off('zoomstart', this._ocultar, this);
    this.canvas.remove();
  },
  _ocultar() { this.canvas.style.visibility = 'hidden'; },
  reiniciar() {
    const m = this._mapa;
    const tam = m.getSize();
    const dpr = window.devicePixelRatio || 1;
    this.origen = m.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(this.canvas, this.origen);
    this.canvas.width = Math.round(tam.x * dpr);
    this.canvas.height = Math.round(tam.y * dpr);
    this.canvas.style.width = `${tam.x}px`;
    this.canvas.style.height = `${tam.y}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.ancho = tam.x;
    this.alto = tam.y;
    this.escala = 256 * Math.pow(2, m.getZoom());
    const po = m.getPixelOrigin();
    this.dx = -po.x - this.origen.x;
    this.dy = -po.y - this.origen.y;
    this.canvas.style.visibility = 'visible';
    this.redibujar();
  },
  x(lon) { return ((lon + 180) / 360) * this.escala + this.dx; },
  y(lat) {
    const s = Math.sin((lat * Math.PI) / 180);
    return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * this.escala + this.dy;
  },
  redibujar() {
    if (!this.ctx) return;
    this.ctx.clearRect(0, 0, this.ancho, this.alto);
    this.dibujar(this.ctx, this);
  },
});

// ---------------------------------------------------------------------------
// Sargazo: densidad por celda, zona P90 y partículas.
// ---------------------------------------------------------------------------
// Probabilidad por celda (% de partículas). Rampa secuencial ámbar (color del sargazo).
export const CORTES_DENSIDAD = [0.005, 0.02, 0.05, 0.1, 0.2];
export const RAMPA_DENSIDAD = ['rgba(226,176,73,0.16)', 'rgba(226,176,73,0.28)', 'rgba(232,160,58,0.40)',
  'rgba(236,140,46,0.52)', 'rgba(240,118,40,0.62)'];
export const COLOR_SARGAZO = '#f0c35a';
export const COLOR_VARADA = '#ff6b5b';

export function dibujarDensidad(ctx, c, est) {
  const { sim, campos, hora, ver } = est;
  if (!sim || !campos || (!ver.densidad && !ver.zona)) return;
  const d = sim.densidad(hora, campos);
  const medio = campos.resolucion / 2;
  const celda = (k) => {
    const i = Math.floor(k / campos.nx), j = k % campos.nx;
    const lon = campos.lon0 + j * campos.dlon, lat = campos.lat0 + i * campos.dlat;
    return [c.x(lon - medio), c.y(lat + medio), c.x(lon + medio), c.y(lat - medio), i, j];
  };
  if (ver.densidad) {
    for (const [k, n] of d.conteo) {
      const p = n / sim.N;
      let b = 0;
      while (b < CORTES_DENSIDAD.length - 1 && p >= CORTES_DENSIDAD[b + 1]) b++;
      const [x0, y0, x1, y1] = celda(k);
      ctx.fillStyle = RAMPA_DENSIDAD[b];
      ctx.fillRect(x0 + 0.5, y0 + 0.5, x1 - x0 - 1, y1 - y0 - 1);
    }
  }
  if (ver.zona && d.zona.size) {
    // Contorno de la unión de celdas: solo los bordes que no comparten con otra celda de la zona.
    ctx.strokeStyle = 'rgba(255,255,255,0.92)';
    ctx.lineWidth = 1.6;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    for (const k of d.zona) {
      const [x0, y0, x1, y1, i, j] = celda(k);
      const tiene = (ii, jj) => ii >= 0 && jj >= 0 && ii < campos.ny && jj < campos.nx && d.zona.has(ii * campos.nx + jj);
      if (!tiene(i + 1, j)) { ctx.moveTo(x0, y0); ctx.lineTo(x1, y0); }
      if (!tiene(i - 1, j)) { ctx.moveTo(x0, y1); ctx.lineTo(x1, y1); }
      if (!tiene(i, j - 1)) { ctx.moveTo(x0, y0); ctx.lineTo(x0, y1); }
      if (!tiene(i, j + 1)) { ctx.moveTo(x1, y0); ctx.lineTo(x1, y1); }
    }
    ctx.stroke();
    ctx.setLineDash([]);
    if (!ver.densidad) {
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      for (const k of d.zona) { const [x0, y0, x1, y1] = celda(k); ctx.fillRect(x0, y0, x1 - x0, y1 - y0); }
    }
  }
}

export function dibujarParticulas(ctx, c, est) {
  const { sim, hora, ver } = est;
  if (!sim || !ver.particulas) return;
  const o = hora * sim.N;
  const tam = sim.N > 3000 ? 1.6 : 2.0;
  ctx.fillStyle = COLOR_SARGAZO;
  ctx.globalAlpha = 0.85;
  for (let n = 0; n < sim.N; n++) {
    if (sim.estado(n, hora) !== A_FLOTE) continue;
    ctx.fillRect(c.x(sim.lon[o + n]) - tam / 2, c.y(sim.lat[o + n]) - tam / 2, tam, tam);
  }
  ctx.globalAlpha = 1;
  // Varadas: anillo coral para que no dependan solo del color.
  ctx.strokeStyle = COLOR_VARADA;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  for (let n = 0; n < sim.N; n++) {
    if (sim.estado(n, hora) !== VARADA) continue;
    const x = c.x(sim.lon[o + n]), y = c.y(sim.lat[o + n]);
    ctx.moveTo(x + 2.6, y);
    ctx.arc(x, y, 2.6, 0, 2 * Math.PI);
  }
  ctx.stroke();
}

export function dibujarMalla(ctx, c, est) {
  const { campos, ver } = est;
  if (!campos || !ver.malla) return;
  const medio = campos.resolucion / 2;
  ctx.strokeStyle = 'rgba(160,200,230,0.18)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let j = 0; j <= campos.nx; j++) {
    const x = Math.round(c.x(campos.lon0 - medio + j * campos.dlon)) + 0.5;
    ctx.moveTo(x, c.y(campos.latMax + medio));
    ctx.lineTo(x, c.y(campos.lat0 - medio));
  }
  for (let i = 0; i <= campos.ny; i++) {
    const y = Math.round(c.y(campos.lat0 - medio + i * campos.dlat)) + 0.5;
    ctx.moveTo(c.x(campos.lon0 - medio), y);
    ctx.lineTo(c.x(campos.lonMax + medio), y);
  }
  ctx.stroke();
  // Nodos con dato de mar
  ctx.fillStyle = 'rgba(160,200,230,0.35)';
  for (let i = 0; i < campos.ny; i++) {
    for (let j = 0; j < campos.nx; j++) {
      if (!campos.mar[i * campos.nx + j]) continue;
      ctx.fillRect(c.x(campos.lon0 + j * campos.dlon) - 1, c.y(campos.lat0 + i * campos.dlat) - 1, 2, 2);
    }
  }
}
