// Orquestador de la interfaz de PMS v0.4.0 («carta náutica»): pasos 1→2→3, mapa,
// línea de tiempo, hover, historial, estado del sistema y recorrido guiado.
/* global L */
import { api, esperarTrabajo } from './api.js';
import { Campos, Simulacion } from './datos.js';
import { CapaCanvas, COLOR, dibujarOleaje, dibujarParticulas, dibujarReticula, dibujarZona } from './capas.js';
import { cajaError, detalleValidacion, renderHistorial, renderResultado } from './paneles.js';
import { Recorrido, recorridoVisto } from './recorrido.js';
import { el, fmtCoord, fmtFechaUTC, fmtHoraCancun, fmtLat, fmtLon, fmtNum, rumbo16, sumarHoras } from './util.js';

const $ = (id) => document.getElementById(id);
const DOMINIO = { oeste: -92.08, este: -84.08, sur: 16.92, norte: 23 };
const HORIZONTE_MAX = 120;
const VELOCIDAD_H_POR_S = 6;      // reproducción a velocidad fija
const CANCUN = { lat: 21.12, lon: -86.66 };

const est = {
  estado: 'validando',
  campos: null,
  sim: null,
  hora: 0,
  paso: 1,
  ver: { oleaje: true },
  punto: { ...CANCUN },
  reproduciendo: false,
  historial: [],
  poligonosCosta: [],
  sinServidor: false,
  estadoPrevio: null,
  puntoValidoEn: 0,          // cuándo se fijó por última vez un punto válido (para el recorrido)
  resultadoEn: 0,            // cuándo terminó la última simulación
};
window.pms = est; // facilita la inspección desde la consola y las pruebas de interfaz

// ---------------------------------------------------------------------------
// Mapa
// ---------------------------------------------------------------------------
const mapa = L.map('mapa', { zoomControl: false, minZoom: 5, maxZoom: 11, zoomSnap: 0.5, maxBounds: [[10, -102], [30, -74]] });
mapa.getContainer().classList.add('seleccionando');
window.pmsMapa = mapa;
L.control.zoom({ position: 'topright', zoomInTitle: 'Acercar', zoomOutTitle: 'Alejar' }).addTo(mapa);
L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(mapa);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
}).addTo(mapa);
mapa.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');

for (const [nombre, z] of [['reticula', 380], ['oleaje', 390], ['zona', 440], ['particulas', 460], ['trayectoria', 470]]) {
  mapa.createPane(nombre).style.zIndex = z;
}
const capaReticula = new CapaCanvas({ pane: 'reticula', nombre: 'reticula', dibujar: (ctx, c) => dibujarReticula(ctx, c) }).addTo(mapa);
const capaOleaje = new CapaCanvas({ pane: 'oleaje', nombre: 'oleaje', dibujar: (ctx, c) => dibujarOleaje(ctx, c, est) }).addTo(mapa);
const capaZona = new CapaCanvas({ pane: 'zona', nombre: 'zona', dibujar: (ctx, c) => dibujarZona(ctx, c, est) }).addTo(mapa);
const capaParticulas = new CapaCanvas({ pane: 'particulas', nombre: 'particulas', dibujar: (ctx, c) => dibujarParticulas(ctx, c, est) }).addTo(mapa);

L.rectangle([[DOMINIO.sur, DOMINIO.oeste], [DOMINIO.norte, DOMINIO.este]], {
  color: COLOR.tinta, weight: 1, opacity: 0.55, dashArray: '2 5', fill: false, interactive: false,
}).addTo(mapa);
mapa.fitBounds([[DOMINIO.sur, DOMINIO.oeste], [DOMINIO.norte, DOMINIO.este]], { paddingTopLeft: [360, 80], paddingBottomRight: [300, 70] });

const rend = L.svg({ pane: 'trayectoria' });
const lineaFutura = L.polyline([], { renderer: rend, color: COLOR.tinta, weight: 1.6, opacity: 0.35, dashArray: '2 5', interactive: false });
const lineaPasada = L.polyline([], { renderer: rend, color: COLOR.tinta, weight: 2.4, opacity: 0.95, interactive: false });
const marcaCentroide = L.circleMarker([0, 0], { renderer: rend, radius: 4.5, color: COLOR.tinta, weight: 2, fillColor: '#fbf6ea', fillOpacity: 1, interactive: false });
const grupoTrayectoria = L.layerGroup([lineaFutura, lineaPasada, marcaCentroide]);

const marcador = L.marker([est.punto.lat, est.punto.lon], {
  draggable: true, title: 'Punto de liberación (arrastrable)', zIndexOffset: 1000,
  icon: L.divIcon({
    className: 'marcador-liberacion', iconSize: [24, 32], iconAnchor: [12, 32],
    html: '<svg width="24" height="32" viewBox="0 0 24 32"><path d="M12 31s10-10.6 10-18.5A10 10 0 0 0 2 12.5C2 20.4 12 31 12 31z" fill="#1d3557" stroke="#fbf6ea" stroke-width="1.5"/><circle cx="12" cy="12.5" r="3.6" fill="#b07d10"/></svg>',
  }),
}).addTo(mapa);
const circuloRadio = L.circle([est.punto.lat, est.punto.lon], {
  radius: 5000, color: COLOR.tinta, weight: 1.2, dashArray: '4 4', fillColor: COLOR.tinta, fillOpacity: 0.05, interactive: false,
}).addTo(mapa);

// ---------------------------------------------------------------------------
// Pasos 1 → 2 → 3
// ---------------------------------------------------------------------------
function irPaso(n) {
  if (n === 3 && !est.sim) return;
  est.paso = n;
  document.querySelectorAll('#hoja .paso').forEach((p) => { p.hidden = Number(p.dataset.paso) !== n; });
  document.querySelectorAll('#pasos button').forEach((b) => {
    if (Number(b.dataset.paso) === n) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
  });
  $('hoja').scrollTop = 0;
}
document.querySelectorAll('#pasos button').forEach((b) => b.addEventListener('click', () => irPaso(Number(b.dataset.paso))));
document.querySelectorAll('[data-ir]').forEach((b) => b.addEventListener('click', () => irPaso(Number(b.dataset.ir))));
$('btn-a-ajustes').addEventListener('click', () => irPaso(2));

// ---------------------------------------------------------------------------
// Estado del sistema en una línea (detalle con un clic)
// ---------------------------------------------------------------------------
let detalleEstado = [];
function ponerEstado(nombre, texto, detalle = null) {
  if (!['error', 'calculando', 'validando'].includes(nombre)) est.estadoPrevio = nombre;
  est.estado = nombre;
  $('estado').dataset.estado = nombre;
  $('estado-texto').textContent = texto;
  detalleEstado = [detalle].flat().filter(Boolean);
  $('estado-mas').hidden = detalleEstado.length === 0;
  $('estado-detalle').replaceChildren(...detalleEstado);
  $('estado-detalle').hidden = true;
  $('estado').setAttribute('aria-expanded', 'false');
  $('btn-simular').disabled = !est.campos || nombre === 'calculando' || nombre === 'validando';
}
$('estado').addEventListener('click', () => {
  if (!detalleEstado.length) return;
  const caja = $('estado-detalle');
  caja.hidden = !caja.hidden;
  $('estado').setAttribute('aria-expanded', String(!caja.hidden));
});

function mostrarVelo(contenido) {
  $('velo').hidden = !contenido;
  $('velo').replaceChildren(...(contenido ? [el('div', { class: 'velo-caja' }, contenido)] : []));
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
  document.title = `PMS ${salud.version_app} · Predicción de Movimiento del Sargazo`;
  est.sinServidor = salud.trabajos_en_segundo_plano === false;
  $('aviso-historial').hidden = !salud.almacenamiento_efimero;
  if (!salud.datos_disponibles) { sinDatos(); return; }
  await validar();
}

function sinDatos() {
  est.campos = null;
  ponerEstado('sin-datos', 'Sin datos de SEMAR', el('p', {}, 'Copia dirmarea.txt en data/semar/ y recarga la página.'));
  mostrarVelo([
    el('h2', {}, 'Falta el archivo de oleaje de SEMAR'),
    el('p', {}, 'Copia ', el('code', {}, 'dirmarea.txt'), ' en ', el('code', {}, 'data/semar/'), ' y recarga la página.'),
    el('p', {}, 'Formato y origen del archivo: data/semar/README.md.'),
  ]);
}

async function validar(forzar = false) {
  pausar();
  est.campos = null;
  mostrarVelo(null);
  ponerEstado('validando', 'Validando dirmarea.txt…');
  let rep;
  try {
    if (est.sinServidor) {
      rep = await api.validacion(forzar);
    } else {
      const { trabajo_id } = await api.validar(forzar);
      const t = await esperarTrabajo(trabajo_id, (tr) => { $('estado-texto').textContent = `Validando · ${tr.mensaje || ''}`; });
      if (t.estado === 'error') throw Object.assign(new Error(t.error.causa), { detalle: t.error });
      rep = t.resultado;
    }
  } catch (e) {
    ponerEstado('error', 'No se pudo validar el archivo', cajaError(e.detalle || { causa: e.message }));
    return;
  }
  if (!rep.valido) {
    const errores = rep.verificaciones.flatMap((v) => v.hallazgos.filter((h) => h.nivel === 'error'));
    const primero = errores[0] || { detalle: 'Error de validación.' };
    ponerEstado('error', `Error en los datos: ${primero.detalle}`,
      [cajaError({ causa: primero.detalle, archivo: primero.archivo, accion: primero.accion }),
        errores.length > 1 ? detalleValidacion(rep, { soloErrores: true }) : null]);
    mostrarVelo([
      el('h2', {}, 'El archivo de oleaje no pasó la validación'),
      el('p', {}, 'No se puede simular hasta corregirlo.'),
      cajaError({ causa: primero.detalle, archivo: primero.archivo, accion: primero.accion }),
      errores.length > 1 ? el('p', {}, `Hay ${errores.length} errores en total: ábralos en «detalle», arriba a la izquierda.`) : null,
    ]);
    return;
  }
  try {
    est.campos = new Campos(await api.campos());
  } catch (e) {
    ponerEstado('error', 'No se pudieron cargar los datos de oleaje', cajaError(e.detalle || { causa: e.message }));
    return;
  }
  const avisos = rep.verificaciones.reduce((n, v) => n + v.hallazgos.filter((h) => h.nivel === 'advertencia').length, 0);
  if (est.sim) estadoResultado();
  else ponerEstado('listo', `Listo · dirmarea.txt validado${avisos ? ` (${avisos} avisos)` : ''}`, avisos ? detalleValidacion(rep) : null);
  configurarLineaTiempo();
  redibujar();
  if (!recorridoVisto()) recorrido.iniciar();
}

// ---------------------------------------------------------------------------
// Punto de liberación y ajustes
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
    return 'Fuera del recuadro punteado de la malla (lat 16.92…23.00, lon −92.08…−84.08).';
  }
  if (est.poligonosCosta.some((a) => dentroDePoligono(lon, lat, a))) return 'El punto está en tierra. Elige un punto en el mar.';
  return null;
}

function fijarPunto(lat, lon, { mover = true } = {}) {
  est.punto = { lat, lon };
  $('p-lat').value = lat.toFixed(3);
  $('p-lon').value = lon.toFixed(3);
  if (mover) marcador.setLatLng([lat, lon]);
  circuloRadio.setLatLng([lat, lon]);
  const problema = problemaPunto(lat, lon);
  $('aviso-punto').hidden = !problema;
  $('aviso-punto').textContent = problema || '';
  if (!problema) est.puntoValidoEn = performance.now();
}

function leerParametros() {
  const n = (id) => Number($(id).value);
  return {
    lat: n('p-lat'), lon: n('p-lon'), radio_km: n('p-radio'), particulas: n('p-n'),
    gamma: n('p-gamma'), kh_m2s: n('p-kh'), horizonte_h: n('p-horizonte'), semilla: n('p-semilla'),
  };
}

function escribirParametros(p) {
  $('p-radio').value = p.radio_km;
  $('p-n').value = p.particulas;
  $('p-gamma').value = p.gamma;
  $('p-kh').value = p.kh_m2s;
  $('p-horizonte').value = p.horizonte_h;
  $('p-semilla').value = p.semilla;
  $('v-horizonte').textContent = `${p.horizonte_h} h`;
  circuloRadio.setRadius(p.radio_km * 1000);
  fijarPunto(p.lat, p.lon);
}

// ---------------------------------------------------------------------------
// Simulación
// ---------------------------------------------------------------------------
async function simular() {
  if (!est.campos) return;
  const invalido = [...document.querySelectorAll('#hoja input')].find((i) => !i.checkValidity());
  if (invalido) {
    const paso = Number(invalido.closest('.paso').dataset.paso);
    irPaso(paso);
    if (invalido.closest('#avanzado')) $('avanzado').open = true;
    invalido.reportValidity();
    return;
  }
  const p = leerParametros();
  const problema = problemaPunto(p.lat, p.lon);
  if (problema) { mostrarError({ causa: problema, accion: 'Vuelve al paso 1 y haz clic en el mar dentro del recuadro punteado.' }); return; }
  pausar();
  ponerEstado('calculando', `Calculando ${p.horizonte_h} h…`);
  let reg;
  try {
    if (est.sinServidor) {
      reg = await api.simularSincrono(p);
    } else {
      const { trabajo_id } = await api.simular(p);
      const t = await esperarTrabajo(trabajo_id, (tr) => { $('estado-texto').textContent = `Calculando · +${tr.avance} de ${tr.total} h`; });
      if (t.estado === 'error') { mostrarError(t.error); return; }
      reg = t.resultado;
    }
  } catch (e) {
    mostrarError(e.detalle || { causa: e.message });
    return;
  }
  await cargarHistorial();
  await abrirSimulacion(reg, { reproducir: true });
  est.resultadoEn = performance.now();
}

function mostrarError(detalle) {
  ponerEstado('error', `Error: ${detalle.causa}`, cajaError(detalle));
  $('btn-simular').disabled = !est.campos;
}

function estadoResultado() {
  ponerEstado('resultado', `Resultado de ${est.sim.H} h guardado · ${fmtNum(est.sim.reg.resumen.varadas_pct, 1)} % varado`);
}

async function abrirSimulacion(reg, { reproducir = false } = {}) {
  pausar();
  est.sim = new Simulacion(reg);
  escribirParametros(reg.parametros);
  configurarLineaTiempo();
  lineaFutura.setLatLngs(reg.resultados.series.centroide.filter(Boolean).map((c) => [c[1], c[0]]));
  grupoTrayectoria.addTo(mapa);
  renderResultado($('resultado'), est.sim);
  $('pasos').querySelector('[data-paso="3"]').disabled = false;
  irPaso(3);
  estadoResultado();
  mapa.fitBounds(limitesSimulacion().pad(0.3), { paddingTopLeft: [370, 90], paddingBottomRight: [300, 80], maxZoom: 10 });
  ponerHora(0);
  marcarHistorial();
  if (reproducir) reproducir_();
}

function limitesSimulacion() {
  const b = L.latLngBounds([[est.sim.reg.parametros.lat, est.sim.reg.parametros.lon]]);
  for (const h of [0, Math.floor(est.sim.H / 2), est.sim.H]) {
    const o = h * est.sim.N;
    for (let n = 0; n < est.sim.N; n += 9) b.extend([est.sim.lat[o + n], est.sim.lon[o + n]]);
  }
  return b;
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
  const anteriorBloque = est.campos ? est.campos.bloque(est.hora) : 0;
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
  if (est.campos && est.campos.bloque(est.hora) !== anteriorBloque) capaOleaje.redibujar();
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
// Hover: coordenadas y ola del nodo más cercano
// ---------------------------------------------------------------------------
let ultimoHover = null;
let pendienteHover = false;

function mostrarHover(e) {
  const tt = $('tooltip');
  const { lat, lng: lon } = e.latlng;
  const nodo = est.campos && est.campos.nodoCercano(lon, lat);
  const ola = nodo ? est.campos.ola(nodo.k, est.hora) : null;
  tt.replaceChildren(
    el('div', { 'data-prueba': 'tt-coord' }, el('b', {}, `${fmtLat(lat)} · ${fmtLon(lon)}`)),
    nodo ? el('div', { 'data-prueba': 'tt-ola' }, ola
      ? `Ola ${fmtNum(ola.altura, 2)} m · desde ${fmtNum(ola.desde)}° (${rumbo16(ola.desde)})`
      : 'Ola: sin dato (tierra)') : null,
  );
  tt.hidden = false;
  const p = e.originalEvent ? { x: e.originalEvent.clientX, y: e.originalEvent.clientY } : mapa.latLngToContainerPoint(e.latlng);
  const w = tt.offsetWidth, h = tt.offsetHeight;
  tt.style.left = `${p.x + 16 + w > window.innerWidth - 10 ? p.x - w - 14 : p.x + 16}px`;
  tt.style.top = `${p.y + 16 + h > window.innerHeight - 70 ? p.y - h - 12 : p.y + 16}px`;
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
  renderHistorial($('lista-hist'), $('hist-n'), est.historial, est.sim && est.sim.id, abrirDesdeHistorial);
}

function mostrarHistorial(abierto) {
  $('historial').hidden = !abierto;
  $('btn-historial').setAttribute('aria-expanded', String(abierto));
}

async function abrirDesdeHistorial(id) {
  if (est.estado === 'calculando' || est.estado === 'validando' || !est.campos) return;
  try {
    await abrirSimulacion(await api.simulacion(id));
    mostrarHistorial(false);
  } catch (e) {
    mostrarError(e.detalle || { causa: e.message });
  }
}

// ---------------------------------------------------------------------------
// Recorrido guiado
// ---------------------------------------------------------------------------
function rectMapa(limites) {
  const nw = mapa.latLngToContainerPoint(limites.getNorthWest());
  const se = mapa.latLngToContainerPoint(limites.getSouthEast());
  return { left: nw.x, top: nw.y, width: se.x - nw.x, height: se.y - nw.y };
}

const ZONA_CLIC = L.latLngBounds([[20.92, -86.70], [21.36, -86.36]]);   // mar frente a Cancún

const recorrido = new Recorrido($('recorrido'), [
  {
    titulo: 'Bienvenido a PMS',
    texto: [
      'PMS estima hacia dónde podría derivar un conglomerado de sargazo frente a la Península de Yucatán durante los próximos 5 días.',
      'Este recorrido le muestra cada función con una simulación real frente a Cancún. Toma unos dos minutos; puede saltarlo y volver a abrirlo con «Recorrido guiado».',
    ],
    alEntrar: () => { pausar(); mostrarHistorial(false); $('estado-detalle').hidden = true; },
  },
  {
    titulo: 'Los datos: el oleaje de SEMAR',
    texto: [
      'PMS usa un solo archivo de SEMAR, dirmarea.txt: altura y dirección de la ola de viento en una malla de 0.16° (unos 17 km), cada 3 horas hasta +120 h. El archivo actual es una muestra: sus 41 horas son idénticas.',
      'Las flechas del mapa apuntan hacia donde viaja la ola; su largo es proporcional a la altura (la referencia es 1 m). Este interruptor las muestra u oculta.',
    ],
    objetivo: () => $('chip-oleaje'),
  },
  {
    titulo: 'Paso 1 · Fije el punto de liberación',
    texto: [
      'Haga clic en el mar, dentro del recuadro iluminado frente a Cancún, para soltar el conglomerado. El círculo punteado es su radio inicial.',
      'Fuera del recorrido también puede escribir la latitud y la longitud en la hoja de la izquierda o arrastrar el marcador.',
    ],
    alEntrar: () => { irPaso(1); mapa.setView([21.12, -86.53], 9.5, { animate: false }); },
    objetivo: () => rectMapa(ZONA_CLIC),
    esperar: {
      texto: 'Esperando un clic en el mar…',
      listo: (inicio) => est.puntoValidoEn > inicio,
      hecho: () => `Punto fijado: ${fmtCoord(est.punto.lat, est.punto.lon)}.`,
    },
  },
  {
    titulo: 'Paso 2 · El horizonte',
    texto: [
      'El horizonte es cuántas horas hacia adelante se calcula la deriva: de 24 a 120 h (5 días).',
      'A mayor horizonte, mayor incertidumbre: la nube de partículas se abre con el tiempo. Para este recorrido usaremos 120 h.',
    ],
    alEntrar: () => { irPaso(2); $('p-horizonte').value = '120'; $('v-horizonte').textContent = '120 h'; $('avanzado').open = false; },
    objetivo: () => $('campo-horizonte'),
  },
  {
    titulo: 'γ y K_h: los parámetros del modelo',
    texto: [
      'PMS mueve cada partícula con la deriva de Stokes de la ola más un movimiento browniano. γ escala esa deriva (0 la apaga, 1 es la estimación base); K_h es la intensidad del movimiento aleatorio que dispersa las partículas.',
      'Como el archivo no trae el período de la ola, se supone T = 4.0·√H. Ambos parámetros son preliminares y no están calibrados; los dejaremos en sus valores por defecto.',
    ],
    alEntrar: () => { irPaso(2); $('avanzado').open = true; },
    alSalir: () => { $('avanzado').open = false; },
    objetivo: () => $('avanzado'),
  },
  {
    titulo: 'Simular',
    texto: ['Presione «Simular». PMS calculará 2 000 partículas hora por hora durante 120 h y guardará la simulación en el historial.'],
    alEntrar: () => { irPaso(2); $('avanzado').open = false; },
    objetivo: () => $('btn-simular'),
    esperar: {
      texto: 'Esperando a que termine la simulación…',
      listo: (inicio) => est.resultadoEn > inicio,
      hecho: () => `Simulación lista: ${fmtNum(est.sim.reg.resumen.varadas_pct, 1)} % varado a +${est.sim.H} h.`,
    },
  },
  {
    titulo: 'Cómo leer el mapa',
    texto: [
      'Cada punto ocre es una partícula a flote y cada anillo rojo, una varada en la costa. La línea azul marino es la trayectoria central: el centroide de las partículas a flote.',
      'El contorno punteado es la zona probable P90: las celdas de 0.16° donde está el 90 % de las partículas en esa hora.',
    ],
    alEntrar: () => {
      pausar();
      mapa.fitBounds(limitesSimulacion().pad(0.3), { paddingTopLeft: [420, 120], paddingBottomRight: [420, 120], maxZoom: 10, animate: false });
      ponerHora(Math.min(12, horaMaxima()));
    },
    objetivo: () => (est.sim ? rectMapa(limitesSimulacion().pad(0.15)) : null),
  },
  {
    titulo: 'La línea de tiempo',
    texto: [
      'Reproduzca o pause la animación y recorra las horas con el deslizador. La hora aparece en UTC y en hora de Cancún (UTC−5).',
      'Atajos: espacio para reproducir o pausar; ← y → para retroceder o avanzar una hora. Al pausar se conservan la hora y la posición de las partículas.',
    ],
    objetivo: () => $('linea-tiempo'),
  },
  {
    titulo: 'Paso 3 · El resultado',
    texto: [
      'Aquí está el porcentaje de partículas varadas al final, los tramos de costa con mayor probabilidad de arribo y el radio P90.',
      'Son probabilidades del modelo, es decir, la fracción de partículas simuladas; no son certezas. Los datos son de muestra y el modelo no incluye viento ni corrientes. En «Detalles» están los parámetros y la huella del archivo.',
    ],
    alEntrar: () => irPaso(3),
    objetivo: () => $('hoja'),
  },
  {
    titulo: 'El historial',
    texto: ['Cada simulación se guarda. Desde «Historial» puede volver a abrir cualquiera: se restauran sus ajustes y su resultado.'],
    alEntrar: () => mostrarHistorial(true),
    alSalir: () => mostrarHistorial(false),
    objetivo: () => $('historial'),
  },
  {
    titulo: 'Listo',
    texto: [
      'Ya conoce el flujo completo: punto de liberación, ajustes y resultado. Puede repetir este recorrido cuando quiera con el botón «Recorrido guiado».',
      'Recuerde que PMS es un pronóstico probabilístico de muestra: úselo para explorar escenarios, no como una predicción de arribo exacta.',
    ],
  },
]);
window.pmsRecorrido = recorrido;
$('btn-recorrido').addEventListener('click', () => recorrido.iniciar());

// ---------------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------------
function redibujar() {
  capaOleaje.redibujar();
  capaZona.redibujar();
  capaParticulas.redibujar();
  actualizarTrayectoria();
}

mapa.on('click', (e) => {
  if (est.estado === 'calculando' || !est.campos) return;
  fijarPunto(e.latlng.lat, e.latlng.lng);
  if (est.paso === 3 && !window.pmsRecorridoActivo) irPaso(1);
});
marcador.on('drag', (e) => circuloRadio.setLatLng(e.target.getLatLng()));
marcador.on('dragend', (e) => { const p = e.target.getLatLng(); fijarPunto(p.lat, p.lng, { mover: false }); });
for (const id of ['p-lat', 'p-lon']) {
  $(id).addEventListener('change', () => {
    const lat = Number($('p-lat').value), lon = Number($('p-lon').value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) fijarPunto(lat, lon);
  });
}
$('p-radio').addEventListener('input', () => { const r = Number($('p-radio').value); if (r > 0) circuloRadio.setRadius(r * 1000); });
$('p-horizonte').addEventListener('input', () => { $('v-horizonte').textContent = `${$('p-horizonte').value} h`; });
$('btn-simular').addEventListener('click', simular);
$('ver-oleaje').addEventListener('change', (e) => { est.ver.oleaje = e.target.checked; capaOleaje.redibujar(); });
$('btn-historial').addEventListener('click', () => mostrarHistorial($('historial').hidden));
$('btn-play').addEventListener('click', () => (est.reproduciendo ? pausar() : reproducir_()));
$('lt-slider').addEventListener('input', (e) => { pausar(); ponerHora(Number(e.target.value)); });
mapa.on('moveend zoomend', () => capaReticula.redibujar());

document.addEventListener('keydown', (e) => {
  if (window.pmsRecorridoActivo) return;
  const activo = document.activeElement;
  if (activo && ['INPUT', 'SELECT', 'TEXTAREA'].includes(activo.tagName) && activo.type !== 'range') return;
  if (e.code === 'Space') { e.preventDefault(); if (est.reproduciendo) pausar(); else reproducir_(); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); pausar(); ponerHora(est.hora - 1); }
  else if (e.code === 'ArrowRight') { e.preventDefault(); pausar(); ponerHora(est.hora + 1); }
  else if (e.code === 'Escape') { mostrarHistorial(false); $('estado-detalle').hidden = true; }
});

// Costa del modelo, solo para avisar antes de simular si el punto cae en tierra.
api.costa().then((gj) => {
  est.poligonosCosta = gj.features.filter((f) => f.properties.tipo === 'costa').map((f) => f.geometry.coordinates[0]);
  fijarPunto(est.punto.lat, est.punto.lon);
}).catch(() => {});

fijarPunto(est.punto.lat, est.punto.lon);
irPaso(1);
configurarLineaTiempo();
iniciar().then(cargarHistorial);
