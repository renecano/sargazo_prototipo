// Exportación del resultado: imagen del mapa (PNG) y resumen de una página para imprimir o
// guardar como PDF. La imagen se compone en un lienzo propio con el mapa base, las capas, la
// escala gráfica (km y MN), la referencia de ola, la fecha y las atribuciones, de modo que las
// escalas siguen siendo verdad a cualquier tamaño de impresión.
import { CLASES_DENSIDAD, CELDA_DENSIDAD } from './datos.js';
import { ALFA_DENSIDAD, medirEscala, paleta, pintarCarta, PX_POR_METRO, trazarFlecha } from './capas.js';
import { arribosEnOrden } from './paneles.js';
import {
  el, fmtCoord, fmtCoordGM, fmtDistancia, fmtFechaLarga, fmtFechaQRoo, fmtFechaUTC, fmtNum, fmtPct, fmtRapidez, fmtRumbo,
} from './util.js';

const PAPEL = '#fbf6ea', TINTA = '#1d3557', TINTA_2 = '#3d5a80';
const FUENTE = '"IBM Plex Sans", "Segoe UI", sans-serif', MONO = '"IBM Plex Mono", Consolas, monospace';
export const LIMITES_MODELO = [
  'Pronóstico probabilístico: los porcentajes son fracciones de partículas simuladas, no certezas de arribo.',
  'Solo deriva por oleaje (Stokes) más dispersión aleatoria: sin viento ni corrientes.',
  'Período de ola supuesto (T = 4.0·√H); γ y K_h preliminares, sin calibrar.',
  'Costa de ~100 m (OpenStreetMap): no resuelve canales de menos de ~200 m ni distingue playa, manglar o arrecife.',
  'Más allá de 48 h la incertidumbre crece notablemente.',
];

function cargarImagen(url) {
  return new Promise((ok, mal) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = mal;
    img.src = url;
  });
}

function rectEnMapa(nodo, marco) {
  const r = nodo.getBoundingClientRect();
  return { x: r.left - marco.left, y: r.top - marco.top, w: r.width, h: r.height };
}

function caja(ctx, x, y, w, h) {
  ctx.fillStyle = 'rgba(251, 246, 234, 0.94)';
  ctx.strokeStyle = TINTA;
  ctx.lineWidth = 1;
  ctx.fillRect(x, y, w, h);
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
}

// Mapa base: las teselas que Leaflet tiene en pantalla (imágenes o lienzos de la carta propia).
function dibujarBase(ctx, mapa, est, marco, ancho, alto) {
  ctx.fillStyle = '#eef1ea';
  ctx.fillRect(0, 0, ancho, alto);
  if (est.base === 'calles') ctx.filter = 'sepia(0.3) saturate(0.72) brightness(1.03) contrast(0.94)';
  for (const t of mapa.getPane('tilePane').querySelectorAll('.leaflet-tile')) {
    if (t.tagName === 'IMG' && (!t.complete || !t.naturalWidth)) continue;
    const r = rectEnMapa(t, marco);
    if (r.x > ancho || r.y > alto || r.x + r.w < 0 || r.y + r.h < 0) continue;
    ctx.drawImage(t, r.x, r.y, r.w, r.h);
  }
  ctx.filter = 'none';
}

async function dibujarVectores(ctx, mapa, marco) {
  for (const svg of mapa.getContainer().querySelectorAll('svg.leaflet-zoom-animated')) {
    const r = rectEnMapa(svg, marco);
    if (!r.w || !r.h) continue;
    const copia = svg.cloneNode(true);
    copia.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    copia.setAttribute('width', r.w);
    copia.setAttribute('height', r.h);
    copia.removeAttribute('style');
    const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(copia))}`;
    try { ctx.drawImage(await cargarImagen(url), r.x, r.y, r.w, r.h); } catch { /* un vector que no carga no detiene la exportación */ }
  }
}

function dibujarMarcador(ctx, mapa, punto) {
  const p = mapa.latLngToContainerPoint([punto.lat, punto.lon]);
  ctx.save();
  ctx.translate(p.x - 12, p.y - 32);
  ctx.fillStyle = TINTA;
  ctx.strokeStyle = PAPEL;
  ctx.lineWidth = 1.5;
  const pin = new Path2D('M12 31s10-10.6 10-18.5A10 10 0 0 0 2 12.5C2 20.4 12 31 12 31z');
  ctx.fill(pin);
  ctx.stroke(pin);
  ctx.fillStyle = '#b07d10';
  ctx.beginPath();
  ctx.arc(12, 12.5, 3.6, 0, 2 * Math.PI);
  ctx.fill();
  ctx.restore();
}

// Cartela: qué es, cuándo, de dónde salió y con qué límites.
function dibujarCartela(ctx, est, ancho) {
  const { sim } = est;
  const lineas = [];
  if (sim) {
    const f = sim.fecha(est.hora), p = sim.reg.parametros;
    lineas.push(`Hora ${fmtNum(est.hora, Number.isInteger(est.hora) ? 0 : 1)} de ${sim.H} · ${fmtFechaUTC(f)} · ${fmtFechaQRoo(f)} hora de Quintana Roo`);
    lineas.push(`Liberación ${fmtCoordGM(p.lat, p.lon)} · ${fmtNum(p.particulas)} partículas en ${fmtNum(p.radio_km, 1)} km · ${sim.id}`);
  } else if (est.campos) {
    lineas.push(`Oleaje de SEMAR · ${fmtFechaUTC(new Date(est.campos.inicio.getTime() + est.hora * 3600e3))}`);
  }
  lineas.push('Pronóstico probabilístico; solo oleaje, sin viento ni corrientes.');
  const alto = 30 + lineas.length * 15;
  const w = Math.min(ancho - 24, 560);
  caja(ctx, 12, 12, w, alto);
  ctx.fillStyle = TINTA;
  ctx.textBaseline = 'alphabetic';
  ctx.font = `600 13px ${FUENTE}`;
  ctx.fillText('PMS · Predicción de Movimiento del Sargazo', 22, 31);
  ctx.font = `11px ${MONO}`;
  ctx.fillStyle = TINTA_2;
  lineas.forEach((l, k) => ctx.fillText(l, 22, 48 + k * 15, w - 20));
}

// Escalas: barra doble (km y MN), norte, referencia de ola de 1 m y clases de densidad.
function dibujarEscalas(ctx, mapa, est, ancho, alto, atribucion) {
  const e = medirEscala(mapa);
  const w = 388, h = est.sim ? 98 : 62;
  const x = ancho - w - 12, y = alto - h - 12 - 16;
  caja(ctx, x, y, w, h);
  ctx.strokeStyle = TINTA;
  ctx.fillStyle = TINTA;
  ctx.lineWidth = 1.4;
  ctx.font = `10.5px ${MONO}`;
  ctx.textBaseline = 'middle';
  // Norte
  ctx.beginPath();
  ctx.moveTo(x + 18, y + 40); ctx.lineTo(x + 18, y + 12); ctx.moveTo(x + 13, y + 19); ctx.lineTo(x + 18, y + 11); ctx.lineTo(x + 23, y + 19);
  ctx.stroke();
  ctx.fillText('N', x + 14.5, y + 48);
  // Barras
  [[e.pxKm, `${fmtNum(e.km)} km`, y + 16], [e.pxMn, `${fmtNum(e.mn)} MN`, y + 34]].forEach(([px, texto, yy]) => {
    ctx.beginPath();
    ctx.moveTo(x + 40, yy - 4); ctx.lineTo(x + 40, yy + 4); ctx.lineTo(x + 40 + px, yy + 4); ctx.lineTo(x + 40 + px, yy - 4);
    ctx.stroke();
    ctx.fillText(texto, x + 48 + px, yy);
  });
  // Ola de referencia: 1 m, con la misma constante que el mapa
  ctx.strokeStyle = paleta({ base: 'carta' }).ola;
  ctx.beginPath();
  trazarFlecha(ctx, x + 272 + PX_POR_METRO / 2, y + 16, 1, 0, PX_POR_METRO);
  ctx.stroke();
  ctx.fillText('ola de 1 m', x + 278 + PX_POR_METRO, y + 16);
  if (est.sim) {
    const pal = paleta(est);
    const [r, g, b] = pal.densidad;
    const alfas = ALFA_DENSIDAD;
    CLASES_DENSIDAD.forEach((v, k) => {
      const xx = x + 12 + k * 62;
      ctx.fillStyle = pal.fondo; ctx.fillRect(xx, y + 60, 18, 12);
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alfas[k]})`; ctx.fillRect(xx, y + 60, 18, 12);
      ctx.strokeStyle = TINTA_2; ctx.lineWidth = 0.6; ctx.strokeRect(xx + 0.5, y + 60.5, 17, 11);
      ctx.fillStyle = TINTA;
      const tope = CLASES_DENSIDAD[k + 1];
      ctx.fillText(tope ? `${v}–${tope}` : `≥ ${v}`, xx + 22, y + 66);
    });
    ctx.fillStyle = TINTA_2;
    ctx.fillText(`% del sargazo liberado por celda de ${CELDA_DENSIDAD}° (≈ 4.4 × 4.2 km)`, x + 12, y + 85);
  }
  // Atribuciones
  ctx.font = `9.5px ${MONO}`;
  const anchoTexto = Math.min(ancho - 24, ctx.measureText(atribucion).width + 12);
  ctx.fillStyle = 'rgba(251, 246, 234, 0.9)';
  ctx.fillRect(ancho - anchoTexto - 12, alto - 22, anchoTexto, 14);
  ctx.fillStyle = TINTA_2;
  ctx.fillText(atribucion, ancho - anchoTexto - 6, alto - 15, anchoTexto - 8);
}

// Compone el mapa actual en un lienzo. Si el mapa base de internet no deja leer sus píxeles
// (política del servidor de teselas), se sustituye por la carta propia y se avisa.
export async function componerImagen(mapa, est, atribucion) {
  const tam = mapa.getSize();
  const dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
  const marco = mapa.getContainer().getBoundingClientRect();
  let sustituido = false;

  async function componer(usarCartaPropia) {
    const lienzo = document.createElement('canvas');
    lienzo.width = Math.round(tam.x * dpr);
    lienzo.height = Math.round(tam.y * dpr);
    const ctx = lienzo.getContext('2d');
    if (usarCartaPropia) {
      const po = mapa.getPixelBounds().min;
      pintarCarta(ctx, est.costa, po.x, po.y, mapa.getZoom(), lienzo.width, lienzo.height, dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    } else {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      dibujarBase(ctx, mapa, est, marco, tam.x, tam.y);
    }
    for (const c of mapa.getContainer().querySelectorAll('canvas.capa-canvas')) {
      const r = rectEnMapa(c, marco);
      ctx.drawImage(c, r.x, r.y, r.w, r.h);
    }
    await dibujarVectores(ctx, mapa, marco);
    dibujarMarcador(ctx, mapa, est.punto);
    dibujarCartela(ctx, est, tam.x);
    dibujarEscalas(ctx, mapa, est, tam.x, tam.y, atribucion);
    return lienzo;
  }

  let lienzo = await componer(false);
  try {
    lienzo.getContext('2d').getImageData(0, 0, 1, 1);
  } catch {
    sustituido = true;
    lienzo = await componer(true);
  }
  return { lienzo, sustituido };
}

export function nombreArchivo(est, extension) {
  const hora = String(Math.round(est.hora)).padStart(3, '0');
  return `pms_${est.sim ? est.sim.id : 'oleaje'}_h${hora}.${extension}`;
}

export function descargarLienzo(lienzo, nombre) {
  return new Promise((listo) => {
    lienzo.toBlob((blob) => {
      const a = el('a', { href: URL.createObjectURL(blob), download: nombre });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      listo(blob.size);
    }, 'image/png');
  });
}

// Resumen de una página: se arma en #informe (oculto en pantalla, único visible al imprimir).
export function armarInforme(contenedor, mapa, est, lienzo, { atribucion, fuentes }) {
  const { sim } = est;
  const r = sim.reg, s = r.resumen, p = r.parametros;
  const arribos = arribosEnOrden(sim);
  const rapideces = sim.series.rapidez_centroide_ms.filter((v) => v !== null);
  const media = rapideces.length ? rapideces.reduce((a, b) => a + b, 0) / rapideces.length : null;
  const e = medirEscala(mapa);
  const fila = (k, v) => el('tr', {}, el('th', {}, k), el('td', {}, v));
  contenedor.replaceChildren(
    el('header', {},
      el('h1', {}, 'PMS · Predicción de Movimiento del Sargazo'),
      el('p', {}, `Resumen de la simulación ${r.id} · generado el ${fmtFechaLarga(new Date())} · PMS ${r.version_app}, modelo ${r.version_modelo}`)),
    el('div', { class: 'inf-dos' },
      el('table', { class: 'inf-param' },
        el('caption', {}, 'Simulación'),
        el('tbody', {},
          fila('Datos de oleaje', `${r.datos.archivo} de ${r.datos.fuente}, inicio ${fmtFechaUTC(sim.inicio)}${r.datos.bloques_identicos ? ' (bloques idénticos: oleaje constante)' : ''}`),
          fila('Punto de liberación', `${fmtCoord(p.lat, p.lon)} · ${fmtCoordGM(p.lat, p.lon)}`),
          fila('Conglomerado', `${fmtNum(p.particulas)} partículas en un radio de ${fmtDistancia(p.radio_km)}`),
          fila('Horizonte', `${sim.H} h (hasta ${fmtFechaUTC(sim.fecha(sim.H))})`),
          fila('Parámetros', `γ = ${fmtNum(p.gamma, 1)} · K_h = ${fmtNum(p.kh_m2s, 1)} m²/s · semilla ${p.semilla}`),
          fila('Huella del archivo', `SHA-256 ${r.datos.huella_sha256.slice(0, 24)}…`))),
      el('table', { class: 'inf-param' },
        el('caption', {}, 'Resultado'),
        el('tbody', {},
          fila('Varado al final', `${fmtNum(s.varadas_pct, 1)} % · a flote ${fmtNum(s.a_flote_pct, 1)} % · fuera del dominio ${fmtNum(s.fuera_pct, 1)} %`),
          fila('Trayectoria central', `${fmtDistancia(s.distancia_centroide_km)} · rumbo neto ${fmtRumbo(s.rumbo_neto_grados)}`),
          fila('Rapidez media', media === null ? '—' : fmtRapidez(media)),
          fila('Mapa', `Hora ${fmtNum(est.hora, 0)} de ${sim.H}: ${fmtFechaUTC(sim.fecha(est.hora))} · ${fmtFechaQRoo(sim.fecha(est.hora))} hora de Quintana Roo`),
          fila('Escalas', `Gráficas, dibujadas en el mapa: ${fmtNum(e.km)} km y ${fmtNum(e.mn)} MN; flecha de ola de 1 m; densidad en % del sargazo por celda de ${CELDA_DENSIDAD}°`)))),
    el('img', { class: 'inf-mapa', src: lienzo.toDataURL('image/png'), alt: 'Mapa de la simulación' }),
    el('table', { class: 'inf-arribos', 'data-prueba': 'informe-arribos' },
      el('caption', {}, 'Arribos por tramo de costa (hora de Quintana Roo, UTC−5)'),
      el('thead', {}, el('tr', {}, ['Tramo de costa', 'Primer arribo', 'UTC', 'Arribo mediano', 'Llega', 'Recorre'].map((t) => el('th', {}, t)))),
      el('tbody', {}, arribos.length ? arribos.map((a) => el('tr', {},
        el('td', {}, a.nombre),
        el('td', {}, `${fmtFechaQRoo(sim.fecha(a.primer_arribo_h))} (hora ${a.primer_arribo_h})`),
        el('td', {}, fmtFechaUTC(sim.fecha(a.primer_arribo_h))),
        el('td', {}, `hora ${a.arribo_mediano_h}`),
        el('td', {}, `${fmtPct(a.probabilidad, 1)} · ${a.etiqueta}`),
        el('td', {}, fmtDistancia(a.distancia_km))))
        : el('tr', {}, el('td', { colspan: 6 }, `Ninguna partícula llegó a la costa en ${sim.H} h.`)))),
    el('div', { class: 'inf-pie' },
      el('div', {}, el('h2', {}, 'Límites del modelo'), el('ul', {}, LIMITES_MODELO.map((t) => el('li', {}, t)))),
      el('div', {}, el('h2', {}, 'Fuentes'), el('ul', {}, fuentes.map((t) => el('li', {}, t)), el('li', {}, `Mapa: ${atribucion}`)))),
  );
}
