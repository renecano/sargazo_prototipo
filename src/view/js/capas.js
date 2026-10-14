// Capas canvas sobre Leaflet: flechas estáticas de viento, contorno de la zona P90 y partículas.
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

export const COLOR_SARGAZO = '#f0c35a';
export const COLOR_VARADA = '#ff6b5b';
export const COLOR_VIENTO = 'rgba(160, 205, 240, 0.62)';
export const PX_POR_MS = 2.4;            // largo de la flecha: 10 m/s = 24 px
const SEPARACION_MIN_PX = 30;            // las flechas se dibujan en una submalla para no saturar

// Flechas estáticas del viento (dirección HACIA la que sopla, largo ∝ velocidad).
export function dibujarViento(ctx, c, est) {
  const { campos, hora, ver } = est;
  if (!campos || !ver.viento) return;
  const pxNodo = Math.abs(c.x(campos.lon0 + campos.dlon) - c.x(campos.lon0));
  const paso = Math.max(2, Math.ceil(SEPARACION_MIN_PX / pxNodo));
  ctx.strokeStyle = COLOR_VIENTO;
  ctx.fillStyle = COLOR_VIENTO;
  ctx.lineWidth = 1.3;
  ctx.lineCap = 'round';
  for (let i = 0; i < campos.ny; i += paso) {
    for (let j = 0; j < campos.nx; j += paso) {
      const uv = campos.viento(i * campos.nx + j, hora);
      if (!uv) continue;
      const xc = c.x(campos.lon0 + j * campos.dlon), yc = c.y(campos.lat0 + i * campos.dlat);
      if (xc < -40 || yc < -40 || xc > c.ancho + 40 || yc > c.alto + 40) continue;
      const vel = Math.hypot(uv[0], uv[1]);
      if (vel < 0.05) continue;
      // Flecha centrada en el nodo; en pantalla el norte es −y.
      const largo = vel * PX_POR_MS, ux = uv[0] / vel, uy = -uv[1] / vel;
      const xa = xc - ux * largo * 0.5, ya = yc - uy * largo * 0.5;
      const xp = xc + ux * largo * 0.5, yp = yc + uy * largo * 0.5;
      ctx.beginPath();
      ctx.moveTo(xa, ya);
      ctx.lineTo(xp, yp);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(xp, yp);
      ctx.lineTo(xp - ux * 5 - uy * 3, yp - uy * 5 + ux * 3);
      ctx.lineTo(xp - ux * 5 + uy * 3, yp - uy * 5 - ux * 3);
      ctx.closePath();
      ctx.fill();
    }
  }
}

// Contorno de la zona probable P90 (unión de celdas de 0.16°).
export function dibujarZona(ctx, c, est) {
  const { sim, campos, hora } = est;
  if (!sim || !campos) return;
  const zona = sim.zonaP90(hora, campos);
  if (!zona.size) return;
  const medio = campos.resolucion / 2;
  const tiene = (i, j) => i >= 0 && j >= 0 && i < campos.ny && j < campos.nx && zona.has(i * campos.nx + j);
  ctx.fillStyle = 'rgba(255,255,255,0.05)';
  ctx.strokeStyle = 'rgba(255,255,255,0.9)';
  ctx.lineWidth = 1.6;
  ctx.setLineDash([5, 3]);
  ctx.beginPath();
  for (const k of zona) {
    const i = Math.floor(k / campos.nx), j = k % campos.nx;
    const lon = campos.lon0 + j * campos.dlon, lat = campos.lat0 + i * campos.dlat;
    const x0 = c.x(lon - medio), x1 = c.x(lon + medio), y0 = c.y(lat + medio), y1 = c.y(lat - medio);
    ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    if (!tiene(i + 1, j)) { ctx.moveTo(x0, y0); ctx.lineTo(x1, y0); }
    if (!tiene(i - 1, j)) { ctx.moveTo(x0, y1); ctx.lineTo(x1, y1); }
    if (!tiene(i, j - 1)) { ctx.moveTo(x0, y0); ctx.lineTo(x0, y1); }
    if (!tiene(i, j + 1)) { ctx.moveTo(x1, y0); ctx.lineTo(x1, y1); }
  }
  ctx.stroke();
  ctx.setLineDash([]);
}

export function dibujarParticulas(ctx, c, est) {
  const { sim, hora } = est;
  if (!sim) return;
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
