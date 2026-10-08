// Utilidades de formato y decodificación compartidas por la interfaz.

const ESPACIO_MILES = ' '; // espacio fino no separable: 2 000

export function fmtNum(n, dec = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const [ent, frac] = Math.abs(n).toFixed(dec).split('.');
  const miles = ent.replace(/\B(?=(\d{3})+(?!\d))/g, ESPACIO_MILES);
  return (n < 0 ? '−' : '') + miles + (frac ? '.' + frac : '');
}

export function fmtPct(fraccion, dec = 1) {
  return `${fmtNum(fraccion * 100, dec)} %`;
}

// Coordenadas siempre con 3 decimales y hemisferio: 21.123° N · 86.654° O
export function fmtLat(lat) {
  return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? 'N' : 'S'}`;
}
export function fmtLon(lon) {
  return `${Math.abs(lon).toFixed(3)}° ${lon >= 0 ? 'E' : 'O'}`;
}
export function fmtCoord(lat, lon) {
  return `${fmtLat(lat)} · ${fmtLon(lon)}`;
}

const RUMBOS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO'];
export function rumbo16(grados) {
  return RUMBOS[Math.floor((((grados % 360) + 360) % 360) / 22.5 + 0.5) % 16];
}

// (u, v) "hacia" → dirección meteorológica "desde" (viento)
export function dirDesde(u, v) {
  return ((Math.atan2(-u, -v) * 180) / Math.PI + 360) % 360;
}
// (u, v) → rumbo "hacia" (corriente, deriva)
export function dirHacia(u, v) {
  return ((Math.atan2(u, v) * 180) / Math.PI + 360) % 360;
}

export const MS_A_NUDOS = 1 / 0.514444;

// ---- Fechas: UTC y hora local de Cancún (UTC−5 todo el año) ----
const DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const dos = (n) => String(n).padStart(2, '0');

export function parseUTC(iso) {
  // "2026-10-01T00:00Z" o "2026-10-01T00:00:00Z"
  return new Date(iso.length === 17 ? iso.replace('Z', ':00Z') : iso);
}
export function fmtFechaUTC(d) {
  return `${DIAS[d.getUTCDay()]} ${dos(d.getUTCDate())} ${MESES[d.getUTCMonth()]} · ${dos(d.getUTCHours())}:00 UTC`;
}
export function fmtHoraCancun(d) {
  const l = new Date(d.getTime() - 5 * 3600 * 1000);
  return `${DIAS[l.getUTCDay()]} ${dos(l.getUTCHours())}:00 Cancún (UTC−5)`;
}
export function fmtFechaCorta(iso) {
  const d = parseUTC(iso);
  const l = new Date(d.getTime() - 5 * 3600 * 1000);
  return `${dos(l.getUTCDate())} ${MESES[l.getUTCMonth()]} ${dos(l.getUTCHours())}:${dos(l.getUTCMinutes())}`;
}
export function sumarHoras(d, h) {
  return new Date(d.getTime() + h * 3600 * 1000);
}

// ---- Base64 → arreglos tipados (little-endian, como los genera la API) ----
export function b64aBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}
export function b64a(b64, Tipo) {
  const bytes = b64aBytes(b64);
  return new Tipo(bytes.buffer, bytes.byteOffset, bytes.byteLength / Tipo.BYTES_PER_ELEMENT);
}

export function el(etiqueta, attrs = {}, ...hijos) {
  const n = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? '' : v);
  }
  for (const h of hijos.flat(Infinity)) {
    if (h === null || h === undefined || h === false) continue;
    n.append(h instanceof Node ? h : document.createTextNode(String(h)));
  }
  return n;
}

export const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
