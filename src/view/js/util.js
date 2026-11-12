// Utilidades de formato y decodificación compartidas por la interfaz.

const ESPACIO_MILES = ' '; // espacio fino no separable: 2 000

export function fmtNum(n, dec = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const [ent, frac] = Math.abs(n).toFixed(dec).split('.');
  const miles = ent.replace(/\B(?=(\d{3})+(?!\d))/g, ESPACIO_MILES);
  return (n < 0 ? '−' : '') + miles + (frac ? '.' + frac : '');
}

export function fmtPct(fraccion, dec = 1) {
  return `${fmtNum(fraccion * 100, dec)} %`;
}

// ---- Coordenadas: decimales (3) y grados con minutos decimales, como en una carta ----
export function fmtLat(lat) {
  return `${Math.abs(lat).toFixed(3)}° ${lat >= 0 ? 'N' : 'S'}`;
}
export function fmtLon(lon) {
  return `${Math.abs(lon).toFixed(3)}° ${lon >= 0 ? 'E' : 'O'}`;
}
export function fmtCoord(lat, lon) {
  return `${fmtLat(lat)} · ${fmtLon(lon)}`;
}
// 21.12 → «21° 07.20′ N»; −86.66 → «086° 39.60′ O» (la longitud lleva tres cifras de grados).
export function fmtGradosMin(valor, esLatitud) {
  const abs = Math.abs(valor);
  let grados = Math.floor(abs);
  let minutos = Math.round((abs - grados) * 6000) / 100;
  if (minutos >= 60) { grados += 1; minutos = 0; }
  const hemisferio = esLatitud ? (valor >= 0 ? 'N' : 'S') : (valor >= 0 ? 'E' : 'O');
  return `${String(grados).padStart(esLatitud ? 2 : 3, '0')}° ${minutos.toFixed(2).padStart(5, '0')}′ ${hemisferio}`;
}
export function fmtCoordGM(lat, lon) {
  return `${fmtGradosMin(lat, true)} · ${fmtGradosMin(lon, false)}`;
}

const RUMBOS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO'];
export function rumbo16(grados) {
  return RUMBOS[Math.floor((((grados % 360) + 360) % 360) / 22.5 + 0.5) % 16];
}
export function fmtRumbo(grados) {
  const g = Math.round((((grados % 360) + 360) % 360)) % 360;
  return `${String(g).padStart(3, '0')}° (${rumbo16(g)})`;
}

// (u, v) → rumbo «hacia» (deriva)
export function dirHacia(u, v) {
  return ((Math.atan2(u, v) * 180) / Math.PI + 360) % 360;
}

// ---- Unidades navales ----
export const KM_POR_MN = 1.852;            // 1 milla náutica = 1 852 m (exacto)
export const MS_A_NUDOS = 1 / 0.514444;
export const MS_A_KMH = 3.6;

export function fmtDistancia(km, dec = 1) {
  if (km === null || km === undefined) return '—';
  return `${fmtNum(km, dec)} km · ${fmtNum(km / KM_POR_MN, dec)} MN`;
}
export function fmtRapidez(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  return `${fmtNum(ms * MS_A_NUDOS, 2)} kn · ${fmtNum(ms * MS_A_KMH, 2)} km/h`;
}

// ---- Fechas: UTC y hora de Quintana Roo (UTC−5 todo el año, sin horario de verano) ----
const DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const dos = (n) => String(n).padStart(2, '0');
export const DESFASE_QROO_H = -5;

export function parseUTC(iso) {
  // "2026-10-01T00:00Z" o "2026-10-01T00:00:00Z"
  return new Date(iso.length === 17 ? iso.replace('Z', ':00Z') : iso);
}
const local = (d) => new Date(d.getTime() + DESFASE_QROO_H * 3600 * 1000);
export function fmtFechaUTC(d) {
  return `${DIAS[d.getUTCDay()]} ${dos(d.getUTCDate())} ${MESES[d.getUTCMonth()]} · ${dos(d.getUTCHours())}:${dos(d.getUTCMinutes())} UTC`;
}
export function fmtFechaQRoo(d) {
  const l = local(d);
  return `${DIAS[l.getUTCDay()]} ${dos(l.getUTCDate())} ${MESES[l.getUTCMonth()]} · ${dos(l.getUTCHours())}:${dos(l.getUTCMinutes())}`;
}
// Fecha de inicio de los datos de oleaje para la cabecera: «1 oct 2026».
export function fmtFechaDatos(d) {
  return `${d.getUTCDate()} ${MESES[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function fmtDiaMes(d) {
  return `${dos(d.getUTCDate())} ${MESES[d.getUTCMonth()]}`;
}
export function fmtFechaCorta(iso) {
  const l = local(parseUTC(iso));
  return `${dos(l.getUTCDate())} ${MESES[l.getUTCMonth()]} ${dos(l.getUTCHours())}:${dos(l.getUTCMinutes())}`;
}
export function fmtFechaLarga(d) {
  return `${dos(d.getUTCDate())} ${MESES[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${dos(d.getUTCHours())}:${dos(d.getUTCMinutes())} UTC`;
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
export const acotar = (v, a, b) => Math.max(a, Math.min(b, v));
