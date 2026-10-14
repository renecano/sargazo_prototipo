// Orquestador de la interfaz de PMS: estado, mapa, línea de tiempo, hover e historial.
/* global L */
import { api, esperarTrabajo } from './api.js';
import { Campos, Simulacion } from './datos.js';
import { CapaCanvas, dibujarParticulas, dibujarViento, dibujarZona } from './capas.js';
import { cajaError, detalleValidacion, renderHistorial, renderResultado } from './paneles.js';
import { dirDesde, el, fmtFechaUTC, fmtHoraCancun, fmtLat, fmtLon, fmtNum, parseUTC, rumbo16, sumarHoras } from './util.js';

const $ = (id) => document.getElementById(id);
const DOMINIO = { oeste: -92, este: -84, sur: 16.92, norte: 23 };
const HORIZONTE_MAX = 120;
const VELOCIDAD_H_POR_S = 6;   // reproducción a velocidad fija
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

const est = {
  estado: 'validando',
  campos: null,
  sim: null,
  hora: 0,
  ver: { viento: true },
  punto: { lat: 21.12, lon: -86.66 },
  reproduciendo: false,
  historial: [],
  poligonosCosta: [],
  sinServidor: false,
  estadoPrevio: null,
};
window.pms = est; // facilita la inspección desde la consola y las pruebas de interfaz

// ---------------------------------------------------------------------------
// Mapa
// ---------------------------------------------------------------------------
const mapa = L.map('mapa', { minZoom: 5, maxZoom: 11, zoomSnap: 0.5, maxBounds: [[11, -100], [29, -76]] })
  .setView([20.6, -87.4], 7);
mapa.getContainer().classList.add('mapa-oscuro', 'seleccionando');
window.pmsMapa = mapa;
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
}).addTo(mapa);
mapa.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
L.control.scale({ imperial: false, position: 'bottomright' }).addTo(mapa);

for (const [nombre, z] of [['viento', 390], ['zona', 440], ['particulas', 460], ['trayectoria', 470]]) {
  mapa.createPane(nombre).style.zIndex = z;
}
const capaViento = new CapaCanvas({ pane: 'viento', nombre: 'viento', dibujar: (ctx, c) => dibujarViento(ctx, c, est) }).addTo(mapa);
const capaZona = new CapaCanvas({ pane: 'zona', nombre: 'zona', dibujar: (ctx, c) => dibujarZona(ctx, c, est) }).addTo(mapa);
const capaParticulas = new CapaCanvas({ pane: 'particulas', nombre: 'particulas', dibujar: (ctx, c) => dibujarParticulas(ctx, c, est) }).addTo(mapa);

L.rectangle([[DOMINIO.sur, DOMINIO.oeste], [DOMINIO.norte, DOMINIO.este]], {
  color: '#5f86a3', weight: 1, dashArray: '2 5', fill: false, interactive: false,
}).addTo(mapa);

const rend = L.svg({ pane: 'trayectoria' });
const lineaFutura = L.polyline([], { renderer: rend, color: '#ffffff', weight: 2, opacity: 0.3, dashArray: '3 6', interactive: false });
const lineaPasada = L.polyline([], { renderer: rend, color: '#ffffff', weight: 2.6, opacity: 0.95, interactive: false });
const marcaCentroide = L.circleMarker([0, 0], { renderer: rend, radius: 5, color: '#061420', weight: 2.5, fillColor: '#ffffff', fillOpacity: 1, interactive: false });
const grupoTrayectoria = L.layerGroup([lineaFutura, lineaPasada, marcaCentroide]);

const marcador = L.marker([est.punto.lat, est.punto.lon], {
  draggable: true, title: 'Punto de liberación (arrastrable)', zIndexOffset: 1000,
  icon: L.divIcon({
    className: 'marcador-liberacion', iconSize: [26, 34], iconAnchor: [13, 34],
    html: '<svg class="pin" viewBox="0 0 26 34"><path d="M13 33s11-11.6 11-20A11 11 0 0 0 2 13c0 8.4 11 20 11 20z" fill="#2bb3c0" stroke="#04202a" stroke-width="2"/><circle cx="13" cy="13" r="4.2" fill="#04202a"/></svg>',
  }),
}).addTo(mapa);

// ---------------------------------------------------------------------------
// Estado en una línea (el detalle se despliega con un clic)
// ---------------------------------------------------------------------------
function ponerEstado(nombre, texto, detalle = null) {
  if (!['error', 'calculando', 'validando'].includes(nombre)) est.estadoPrevio = nombre;
  est.estado = nombre;
  $('estado').dataset.estado = nombre;
  $('estado-texto').textContent = texto;
  const nodos = [detalle].flat().filter(Boolean);
  $('estado-detalle').replaceChildren(...nodos);
  $('estado-detalle').hidden = true;
  $('btn-detalle').hidden = nodos.length === 0;
  $('btn-detalle').textContent = 'Ver detalle';
  $('btn-detalle').setAttribute('aria-expanded', 'false');
  $('btn-simular').disabled = !est.campos || nombre === 'calculando' || nombre === 'validando';
}

$('btn-detalle').addEventListener('click', () => {
  const caja = $('estado-detalle');
  caja.hidden = !caja.hidden;
  $('btn-detalle').textContent = caja.hidden ? 'Ver detalle' : 'Ocultar detalle';
  $('btn-detalle').setAttribute('aria-expanded', String(!caja.hidden));
});

function mostrarVelo(contenido) {
  $('velo').hidden = !contenido;
  $('velo').replaceChildren(...(contenido ? [el('div', { class: 'velo-caja' }, contenido)] : []));
}

function fmtFechaFuente(iso) {
  const d = parseUTC(iso);
  return `${d.getUTCDate()} ${MESES[d.getUTCMonth()]} ${d.getUTCFullYear()} ${String(d.getUTCHours()).padStart(2, '0')} UTC`;
}

// ---------------------------------------------------------------------------
// Datos: validación y carga
// ---------------------------------------------------------------------------
async function iniciar() {
  let salud;
  try {
    salud = await api.salud();
  } catch (e) {
    ponerEstado('error', 'Sin conexión con el servidor', cajaError(e.detalle || { causa: e.message }));
    return;
  }
  $('version').textContent = `Equipo 2 · PMS v${salud.version_app} · modelo ${salud.version_modelo}`;
  est.sinServidor = salud.trabajos_en_segundo_plano === false;
  $('aviso-historial').hidden = !salud.almacenamiento_efimero;
  if (!salud.datos_disponibles) { sinDatos(); return; }
  await validar();
}

function sinDatos() {
  est.campos = null;
  ponerEstado('sin-datos', 'Sin datos de SEMAR', el('p', {}, 'Copia salidadatos.txt y dirmarea.txt en data/semar/ y recarga la página.'));
  mostrarVelo([
    el('h2', {}, 'Faltan los datos de SEMAR'),
    el('p', {}, 'Copia ', el('code', {}, 'salidadatos.txt'), ' (viento) y ', el('code', {}, 'dirmarea.txt'),
      ' (oleaje) en ', el('code', {}, 'data/semar/'), ' y recarga la página.'),
    el('p', {}, 'Formato y origen de los archivos: data/semar/README.md.'),
  ]);
}

async function validar(forzar = false) {
  pausar();
  est.campos = null;
  mostrarVelo(null);
  ponerEstado('validando', 'Validando datos de SEMAR…');
  let rep;
  try {
    if (est.sinServidor) {
      rep = await api.validacion(forzar);
    } else {
      const { trabajo_id } = await api.validar(forzar);
      const t = await esperarTrabajo(trabajo_id, (tr) => { $('estado-texto').textContent = `Validando… ${tr.mensaje || ''}`; });
      if (t.estado === 'error') throw Object.assign(new Error(t.error.causa), { detalle: t.error });
      rep = t.resultado;
    }
  } catch (e) {
    ponerEstado('error', 'No se pudieron validar los datos', cajaError(e.detalle || { causa: e.message }));
    return;
  }
  if (!rep.valido) {
    const errores = rep.verificaciones.flatMap((v) => v.hallazgos.filter((h) => h.nivel === 'error'));
    const primero = errores[0] || { detalle: 'Error de validación.' };
    ponerEstado('error', `Error en los datos: ${primero.detalle}`,
      [cajaError({ causa: primero.detalle, archivo: primero.archivo, accion: primero.accion }),
        errores.length > 1 ? detalleValidacion(rep, { soloErrores: true }) : null]);
    mostrarVelo([
      el('h2', {}, 'Los datos no pasaron la validación'),
      el('p', {}, 'No se puede simular hasta corregirlos. La causa, el archivo y la acción están en «Ver detalle», en el panel izquierdo.'),
    ]);
    return;
  }
  try {
    est.campos = new Campos(await api.campos());
  } catch (e) {
    ponerEstado('error', 'No se pudieron cargar los campos', cajaError(e.detalle || { causa: e.message }));
    return;
  }
  const d = est.campos.datos;
  $('fuente').textContent = `Datos SEMAR · viento ${fmtFechaFuente(d.inicio_utc)}${d.viento_estacionario ? ' (fijo)' : ` (${d.viento_horas} horas)`}`;
  $('aviso-modelo').textContent = `Pronóstico probabilístico; ${d.viento_estacionario ? 'viento fijo de t = 0' : 'viento de SEMAR'}; ${d.corrientes ? 'con corrientes' : 'sin corrientes'}.`;
  const avisos = rep.verificaciones.reduce((n, v) => n + v.hallazgos.filter((h) => h.nivel === 'advertencia').length, 0);
  if (est.sim) {
    estadoResultado();
  } else {
    ponerEstado('listo', `Listo para simular${avisos ? ` · ${avisos} avisos en los datos` : ''}`, avisos ? detalleValidacion(rep) : null);
  }
  configurarLineaTiempo();
  redibujar();
}

// ---------------------------------------------------------------------------
// Punto de liberación y parámetros
// ---------------------------------------------------------------------------
function dentroDePoligono(lon, lat, anillo) {
  let dentro = false;
  for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i++) {
    const [xi, yi] = anillo[i], [xj, yj] = anillo[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) dentro = !dentro;
  }
  return dentro;
}

function problemaPunto(lat, lon) {
  if (!(lat >= DOMINIO.sur && lat <= DOMINIO.norte && lon >= DOMINIO.oeste && lon <= DOMINIO.este)) {
    return 'El punto está fuera del recuadro de la malla (lat 16.92…23.00, lon −92.00…−84.00).';
  }
  if (est.poligonosCosta.some((a) => dentroDePoligono(lon, lat, a))) {
    return 'El punto está en tierra según la costa del modelo. Elige un punto en el mar.';
  }
  return null;
}

function fijarPunto(lat, lon, { mover = true } = {}) {
  est.punto = { lat, lon };
  $('p-lat').value = lat.toFixed(3);
  $('p-lon').value = lon.toFixed(3);
  if (mover) marcador.setLatLng([lat, lon]);
  const problema = problemaPunto(lat, lon);
  $('aviso-punto').hidden = !problema;
  $('aviso-punto').textContent = problema || '';
}

function leerParametros() {
  const n = (id) => Number($(id).value);
  return {
    lat: n('p-lat'), lon: n('p-lon'), radio_km: n('p-radio'), particulas: n('p-n'),
    alpha_pct: n('p-alpha'), kh_m2s: n('p-kh'), horizonte_h: n('p-horizonte'), semilla: n('p-semilla'),
  };
}

function escribirParametros(p) {
  $('p-radio').value = p.radio_km;
  $('p-n').value = p.particulas;
  $('p-alpha').value = p.alpha_pct;
  $('p-kh').value = p.kh_m2s;
  $('p-horizonte').value = p.horizonte_h;
  $('p-semilla').value = p.semilla;
  $('v-horizonte').textContent = `${p.horizonte_h} h`;
  fijarPunto(p.lat, p.lon);
}

// ---------------------------------------------------------------------------
// Simulación
// ---------------------------------------------------------------------------
async function simular() {
  if (!est.campos) return;
  const invalido = [...document.querySelectorAll('#parametros input')].find((i) => !i.checkValidity());
  if (invalido) {
    $('avanzadas').open = $('avanzadas').open || invalido.closest('#avanzadas') !== null;
    invalido.reportValidity();
    return;
  }
  const p = leerParametros();
  const problema = problemaPunto(p.lat, p.lon);
  if (problema) { mostrarError({ causa: problema, accion: 'Haz clic en un punto del mar dentro del recuadro punteado.' }); return; }
  pausar();
  ponerEstado('calculando', `Calculando ${p.horizonte_h} h…`);
  let reg;
  try {
    if (est.sinServidor) {
      reg = await api.simularSincrono(p);
    } else {
      const { trabajo_id } = await api.simular(p);
      const t = await esperarTrabajo(trabajo_id, (tr) => { $('estado-texto').textContent = `Calculando… +${tr.avance} de ${tr.total} h`; });
      if (t.estado === 'error') { mostrarError(t.error); return; }
      reg = t.resultado;
    }
  } catch (e) {
    mostrarError(e.detalle || { causa: e.message });
    return;
  }
  await cargarHistorial();
  await abrirSimulacion(reg, { reproducir: true });
}

function mostrarError(detalle) {
  const volver = () => (est.estadoPrevio === 'resultado' && est.sim ? estadoResultado() : ponerEstado('listo', 'Listo para simular'));
  ponerEstado('error', `Error: ${detalle.causa}`, [cajaError(detalle), el('button', { type: 'button', class: 'enlace', onclick: volver }, 'Entendido')]);
}

function estadoResultado() {
  const s = est.sim;
  ponerEstado('resultado', `Resultado de ${s.H} h guardado · ${fmtNum(s.reg.resumen.varadas_pct, 1)} % varadas`);
}

async function abrirSimulacion(reg, { reproducir = false } = {}) {
  pausar();
  est.sim = new Simulacion(reg);
  escribirParametros(reg.parametros);
  configurarLineaTiempo();
  lineaFutura.setLatLngs(reg.resultados.series.centroide.filter(Boolean).map((c) => [c[1], c[0]]));
  grupoTrayectoria.addTo(mapa);
  const panel = $('resultado');
  renderResultado(panel, est.sim, () => { panel.hidden = true; });
  panel.hidden = false;
  estadoResultado();
  // Encuadre: liberación + posiciones finales.
  const b = L.latLngBounds([[reg.parametros.lat, reg.parametros.lon]]);
  const o = est.sim.H * est.sim.N;
  for (let n = 0; n < est.sim.N; n += 7) b.extend([est.sim.lat[o + n], est.sim.lon[o + n]]);
  mapa.fitBounds(b.pad(0.25), { paddingTopLeft: [40, 60], paddingBottomRight: [320, 80], maxZoom: 10 });
  ponerHora(0);
  marcarHistorial();
  if (reproducir) reproducir_();
}

// ---------------------------------------------------------------------------
// Línea de tiempo
// ---------------------------------------------------------------------------
const horaMaxima = () => (est.sim ? est.sim.H : HORIZONTE_MAX);

function configurarLineaTiempo() {
  $('lt-slider').max = String(horaMaxima());
  ponerHora(Math.min(est.hora, horaMaxima()));
}

function ponerHora(h) {
  est.hora = Math.max(0, Math.min(horaMaxima(), Math.round(h)));
  $('lt-slider').value = String(est.hora);
  $('lt-h').textContent = `+${est.hora} h`;
  const t0 = est.sim ? est.sim.inicio : (est.campos ? est.campos.inicio : null);
  if (t0) {
    const f = sumarHoras(t0, est.hora);
    $('lt-utc').textContent = fmtFechaUTC(f);
    $('lt-local').textContent = fmtHoraCancun(f);
  }
  actualizarTrayectoria();
  if (est.campos && est.campos.tiempos.length > 1) capaViento.redibujar();
  capaZona.redibujar();
  capaParticulas.redibujar();
  if (ultimoHover) mostrarHover(ultimoHover);
}

function actualizarTrayectoria() {
  if (!est.sim) { mapa.removeLayer(grupoTrayectoria); return; }
  const c = est.sim.series.centroide;
  const pasadas = [];
  let actual = null;
  for (let h = 0; h <= est.hora; h++) if (c[h]) { pasadas.push([c[h][1], c[h][0]]); actual = c[h]; }
  lineaPasada.setLatLngs(pasadas);
  if (actual) marcaCentroide.setLatLng([actual[1], actual[0]]).setStyle({ opacity: 1, fillOpacity: 1 });
  else marcaCentroide.setStyle({ opacity: 0, fillOpacity: 0 });
}

let animacion = null;
function reproducir_() {
  if (est.reproduciendo) return;
  if (est.hora >= horaMaxima()) ponerHora(0);
  est.reproduciendo = true;
  $('linea-tiempo').classList.add('reproduciendo');
  $('btn-play').setAttribute('aria-label', 'Pausar');
  let ultimo = performance.now(), acumulado = 0;
  const intervalo = 1000 / VELOCIDAD_H_POR_S;
  const paso = (t) => {
    if (!est.reproduciendo) return;
    acumulado += t - ultimo;
    ultimo = t;
    if (acumulado >= intervalo) {
      acumulado %= intervalo;
      if (est.hora >= horaMaxima()) { pausar(); return; }
      ponerHora(est.hora + 1);
    }
    animacion = requestAnimationFrame(paso);
  };
  animacion = requestAnimationFrame(paso);
}

function pausar() {
  est.reproduciendo = false;
  if (animacion) cancelAnimationFrame(animacion);
  animacion = null;
  $('linea-tiempo').classList.remove('reproduciendo');
  $('btn-play').setAttribute('aria-label', 'Reproducir');
}

// ---------------------------------------------------------------------------
// Hover: coordenadas, viento y ola del nodo más cercano
// ---------------------------------------------------------------------------
let ultimoHover = null;
let pendienteHover = false;

function mostrarHover(e) {
  const tt = $('tooltip');
  const { lat, lng: lon } = e.latlng;
  const filas = [];
  const nodo = est.campos && est.campos.nodoCercano(lon, lat);
  if (nodo) {
    const uv = est.campos.viento(nodo.k, est.hora);
    if (uv) {
      const d = dirDesde(uv[0], uv[1]);
      filas.push(['Viento', `${fmtNum(Math.hypot(uv[0], uv[1]), 1)} m/s desde ${fmtNum(d)}° (${rumbo16(d)})`]);
    } else {
      filas.push(['Viento', 'sin dato (tierra)']);
    }
    const ola = est.campos.ola(nodo.k, est.hora);
    filas.push(['Ola', ola ? `${fmtNum(ola.altura, 1)} m desde ${fmtNum(ola.dir)}° (${rumbo16(ola.dir)})` : 'sin dato']);
  }
  tt.replaceChildren(
    el('div', { class: 'tt-coord', 'data-prueba': 'tt-coord' }, `${fmtLat(lat)} · ${fmtLon(lon)}`),
    filas.length ? el('dl', {}, filas.map(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])) : null,
  );
  tt.hidden = false;
  const zona = mapa.getContainer().getBoundingClientRect();
  const p = e.containerPoint;
  const w = tt.offsetWidth, h = tt.offsetHeight;
  tt.style.left = `${p.x + 16 + w > zona.width ? Math.max(4, p.x - w - 16) : p.x + 16}px`;
  tt.style.top = `${p.y + 16 + h > zona.height - 70 ? p.y - h - 12 : p.y + 16}px`;
}

mapa.on('mousemove', (e) => {
  ultimoHover = e;
  if (pendienteHover) return;
  pendienteHover = true;
  requestAnimationFrame(() => { pendienteHover = false; if (ultimoHover) mostrarHover(ultimoHover); });
});
mapa.getContainer().addEventListener('mouseleave', () => { ultimoHover = null; $('tooltip').hidden = true; });

// ---------------------------------------------------------------------------
// Historial
// ---------------------------------------------------------------------------
async function cargarHistorial() {
  try { est.historial = await api.simulaciones(); } catch { est.historial = []; }
  marcarHistorial();
}

function marcarHistorial() {
  renderHistorial($('lista-hist'), $('hist-contador'), est.historial, est.sim && est.sim.id, abrirDesdeHistorial);
}

async function abrirDesdeHistorial(id) {
  if (est.estado === 'calculando' || est.estado === 'validando' || !est.campos) return;
  try {
    await abrirSimulacion(await api.simulacion(id));
  } catch (e) {
    mostrarError(e.detalle || { causa: e.message });
  }
}

// ---------------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------------
function redibujar() {
  capaViento.redibujar();
  capaZona.redibujar();
  capaParticulas.redibujar();
  actualizarTrayectoria();
}

mapa.on('click', (e) => { if (est.estado !== 'calculando') fijarPunto(e.latlng.lat, e.latlng.lng); });
marcador.on('dragend', (e) => { const p = e.target.getLatLng(); fijarPunto(p.lat, p.lng, { mover: false }); });
for (const id of ['p-lat', 'p-lon']) {
  $(id).addEventListener('change', () => {
    const lat = Number($('p-lat').value), lon = Number($('p-lon').value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) fijarPunto(lat, lon);
  });
}
$('p-horizonte').addEventListener('input', () => { $('v-horizonte').textContent = `${$('p-horizonte').value} h`; });
$('btn-simular').addEventListener('click', simular);
$('ver-viento').addEventListener('change', (e) => { est.ver.viento = e.target.checked; capaViento.redibujar(); });
$('btn-play').addEventListener('click', () => (est.reproduciendo ? pausar() : reproducir_()));
$('lt-slider').addEventListener('input', (e) => { pausar(); ponerHora(Number(e.target.value)); });

document.addEventListener('keydown', (e) => {
  const activo = document.activeElement;
  if (activo && ['INPUT', 'SELECT', 'TEXTAREA'].includes(activo.tagName) && activo.type !== 'range') return;
  if (e.code === 'Space') { e.preventDefault(); if (est.reproduciendo) pausar(); else reproducir_(); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); pausar(); ponerHora(est.hora - 1); }
  else if (e.code === 'ArrowRight') { e.preventDefault(); pausar(); ponerHora(est.hora + 1); }
});

// Costa del modelo, solo para avisar antes de simular si el punto cae en tierra.
api.costa().then((gj) => {
  est.poligonosCosta = gj.features.filter((f) => f.properties.tipo === 'costa').map((f) => f.geometry.coordinates[0]);
  fijarPunto(est.punto.lat, est.punto.lon);
}).catch(() => {});

fijarPunto(est.punto.lat, est.punto.lon);
configurarLineaTiempo();
iniciar().then(cargarHistorial);
