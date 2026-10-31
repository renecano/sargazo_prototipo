// Capas canvas sobre Leaflet con estilo de carta náutica: retícula, flechas de oleaje,
// contorno de la zona P90 y partículas.
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

export const COLOR = {
  tinta: '#1d3557',          // azul marino de carta
  reticula: 'rgba(29, 53, 87, 0.16)',
  ola: 'rgba(31, 92, 122, 0.70)',
  sargazo: '#b07d10',
  varada: '#c0392b',
  zona: '#1d3557',
};
export const PX_POR_METRO = 22;          // largo de la flecha: 1 m de altura de ola = 22 px
const SEPARACION_MIN_PX = 34;            // las flechas se dibujan en una submalla para no saturar

// Retícula de 1° con rótulos en el borde, como en una carta náutica.
export function dibujarReticula(ctx, c) {
  const oeste = Math.floor(c.lon(0) / 5) * 5, este = Math.ceil(c.lon(c.ancho));
  const norte = Math.ceil(c.lat(0)), sur = Math.floor(c.lat(c.alto) / 5) * 5;
  const pxPorGrado = c.escala / 360;
  const paso = [0.5, 1, 2, 5].find((p) => p * pxPorGrado >= 80) || 5;
  ctx.strokeStyle = COLOR.reticula;
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
  ctx.fillStyle = 'rgba(29, 53, 87, 0.55)';
  ctx.font = '10px "IBM Plex Mono", Consolas, monospace';
  ctx.textBaseline = 'middle';
  for (let lat = sur; lat <= norte; lat += paso) {
    const y = c.y(lat);
    if (y < 150 || y > c.alto - 300) continue;      // deja libres la cabecera, la rosa y la leyenda
    ctx.fillText(`${Math.abs(lat).toFixed(paso < 1 ? 1 : 0)}°${lat >= 0 ? 'N' : 'S'}`, c.ancho - 46, y - 7);
  }
  for (let lon = oeste; lon <= este; lon += paso) {
    const x = c.x(lon);
    if (x < 380 || x > c.ancho - 60) continue;
    ctx.fillText(`${Math.abs(lon).toFixed(paso < 1 ? 1 : 0)}°${lon >= 0 ? 'E' : 'O'}`, x + 4, c.alto - 84);
  }
}

// Flechas estáticas de oleaje: apuntan HACIA donde viaja la ola; el largo es proporcional a la altura.
export function dibujarOleaje(ctx, c, est) {
  const { campos, hora, ver } = est;
  if (!campos || !ver.oleaje) return;
  const pxNodo = Math.abs(c.x(campos.lon0 + campos.dlon) - c.x(campos.lon0));
  const paso = Math.max(2, Math.ceil(SEPARACION_MIN_PX / pxNodo));
  ctx.strokeStyle = COLOR.ola;
  ctx.fillStyle = COLOR.ola;
  ctx.lineWidth = 1.2;
  ctx.lineCap = 'round';
  for (let i = 0; i < campos.ny; i += paso) {
    for (let j = 0; j < campos.nx; j += paso) {
      const o = campos.ola(i * campos.nx + j, hora);
      if (!o || o.altura < 0.02) continue;
      const xc = c.x(campos.lon0 + j * campos.dlon), yc = c.y(campos.lat0 + i * campos.dlat);
      if (xc < -40 || yc < -40 || xc > c.ancho + 40 || yc > c.alto + 40) continue;
      const hacia = ((o.desde + 180) * Math.PI) / 180;
      const ux = Math.sin(hacia), uy = -Math.cos(hacia);   // en pantalla el norte es −y
      const largo = Math.max(6, o.altura * PX_POR_METRO);
      const xa = xc - ux * largo * 0.5, ya = yc - uy * largo * 0.5;
      const xp = xc + ux * largo * 0.5, yp = yc + uy * largo * 0.5;
      ctx.beginPath(); ctx.moveTo(xa, ya); ctx.lineTo(xp, yp); ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(xp, yp);
      ctx.lineTo(xp - ux * 5 - uy * 2.6, yp - uy * 5 + ux * 2.6);
      ctx.lineTo(xp - ux * 5 + uy * 2.6, yp - uy * 5 - ux * 2.6);
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
  ctx.fillStyle = 'rgba(29, 53, 87, 0.07)';
  ctx.strokeStyle = COLOR.zona;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([6, 4]);
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
  const tam = sim.N > 3000 ? 1.8 : 2.2;
  ctx.fillStyle = COLOR.sargazo;
  ctx.globalAlpha = 0.8;
  for (let n = 0; n < sim.N; n++) {
    if (sim.estado(n, hora) !== A_FLOTE) continue;
    ctx.fillRect(c.x(sim.lon[o + n]) - tam / 2, c.y(sim.lat[o + n]) - tam / 2, tam, tam);
  }
  ctx.globalAlpha = 1;
  // Varadas: anillo rojo para que no dependan solo del color.
  ctx.strokeStyle = COLOR.varada;
  ctx.lineWidth = 1.3;
  ctx.beginPath();
  for (let n = 0; n < sim.N; n++) {
    if (sim.estado(n, hora) !== VARADA) continue;
    const x = c.x(sim.lon[o + n]), y = c.y(sim.lat[o + n]);
    ctx.moveTo(x + 2.6, y);
    ctx.arc(x, y, 2.6, 0, 2 * Math.PI);
  }
  ctx.stroke();
}
