// Orquestador de la interfaz de PMS v0.5.0 («carta náutica»): pasos 1→2→3, mapa base y capas,
// línea de tiempo con fechas reales, escalas, hover, tabla de arribos, exportación, historial,
// estado del sistema y recorrido guiado.
/* global L */
import { api, esperarTrabajo } from './api.js';
import { Campos, CLASES_DENSIDAD, Costa, Simulacion } from './datos.js';
import {
  ALFA_DENSIDAD, CapaCanvas, CapaCarta, dibujarDensidad, dibujarOleajeFijo, dibujarParticulas, dibujarReticula, dibujarRotulos, medirEscala,
  paleta, PX_POR_METRO,
} from './capas.js';
import { OleajeAnimado } from './oleaje.js';
import { cajaError, detalleValidacion, renderHistorial, renderResultado } from './paneles.js';
import { armarInforme, componerImagen, descargarLienzo, nombreArchivo } from './exportar.js';
import { Recorrido, recorridoVisto } from './recorrido.js';
import {
  acotar, el, fmtCoord, fmtCoordGM, fmtDiaMes, fmtFechaQRoo, fmtFechaUTC, fmtLat, fmtLon, fmtNum, fmtRapidez, fmtRumbo, rumbo16,
  sumarHoras,
} from './util.js';

const $ = (id) => document.getElementById(id);
const DOMINIO = { oeste: -92.08, este: -84.08, sur: 16.92, norte: 23 };
const HORIZONTE_MAX = 120;
const CANCUN = { lat: 21.12, lon: -86.66 };
const RADIO_HOVER_PX = 9;
const movimientoReducido = window.matchMedia('(prefers-reduced-motion: reduce)');

const est = {
  estado: 'validando',
  campos: null,
  costa: null,
  localidades: null,
  sim: null,
  hora: 0,                   // hora de pronóstico; fraccionaria mientras se reproduce
  paso: 1,
  base: 'carta',
  ver: { oleaje: true, animar: !movimientoReducido.matches, estelas: true, densidad: true, localidades: true },
  velocidad: 6,              // horas de pronóstico por segundo
  salto: 6,                  // horas de los botones de salto
  punto: { ...CANCUN },
  reproduciendo: false,
  historial: [],
  sinServidor: false,
  estadoPrevio: null,
  puntoValidoEn: 0,          // cuándo se fijó por última vez un punto válido (para el recorrido)
  resultadoEn: 0,            // cuándo terminó la última simulación
  arriboElegido: null,
  flechas: [],               // flechas de oleaje dibujadas en el último cuadro (para las pruebas)
  rotulos: [],               // rótulos colocados
  dibujo: null,              // cuenta de partículas del último cuadro
  escala: null,
  ultimaExportacion: null,
};
window.pms = est; // facilita la inspección desde la consola y las pruebas de interfaz

// ---------------------------------------------------------------------------
// Mapa, mapas base y capas
// ---------------------------------------------------------------------------
const mapa = L.map('mapa', { zoomControl: false, minZoom: 5, maxZoom: 11, zoomSnap: 0.5, maxBounds: [[10, -102], [30, -74]] });
mapa.getContainer().classList.add('seleccionando');
window.pmsMapa = mapa;
L.control.zoom({ position: 'topright', zoomInTitle: 'Acercar', zoomOutTitle: 'Alejar' }).addTo(mapa);
mapa.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
mapa.attributionControl.addAttribution('costa y localidades © <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>');

const ATRIBUCION = {
  carta: 'Carta propia: costa de OpenStreetMap (ODbL); tierra fuera del dominio de Natural Earth',
  satelite: 'Sentinel-2 cloudless 2016 de EOX IT Services GmbH (contiene datos Copernicus Sentinel modificados), CC BY 4.0',
  calles: '© colaboradores de OpenStreetMap',
};
const bases = {
  carta: null,   // se crea al cargar la máscara de costa
  satelite: L.tileLayer('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg', {
    maxZoom: 11, crossOrigin: 'anonymous', className: 'tesela-satelite',
    attribution: '<a href="https://cloudless.eox.at">Sentinel-2 cloudless 2016</a> de EOX IT Services GmbH (contiene datos Copernicus Sentinel modificados), <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>',
  }),
  calles: L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, crossOrigin: 'anonymous', className: 'tesela-calles',
    attribution: 'mapa base © <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
  }),
};

for (const [nombre, z] of [['reticula', 380], ['densidad', 400], ['oleaje', 410], ['particulas', 460], ['trayectoria', 470], ['rotulos', 480]]) {
  const pane = mapa.createPane(nombre);
  pane.style.zIndex = z;
  pane.style.pointerEvents = 'none';
}
let oleaje = null;
const animando = () => !!(oleaje && est.campos && est.ver.oleaje && est.ver.animar);
const capaReticula = new CapaCanvas({ pane: 'reticula', nombre: 'reticula', dibujar: (ctx, c) => dibujarReticula(ctx, c, est) }).addTo(mapa);
const capaDensidad = new CapaCanvas({ pane: 'densidad', nombre: 'densidad', margen: 200, dibujar: (ctx, c) => dibujarDensidad(ctx, c, est) }).addTo(mapa);
const capaOleaje = new CapaCanvas({
  pane: 'oleaje', nombre: 'oleaje',
  dibujar: (ctx, c) => { if (animando()) { oleaje.sembrar(); oleaje.avanzar(0); } else dibujarOleajeFijo(ctx, c, est); },
}).addTo(mapa);
const capaParticulas = new CapaCanvas({ pane: 'particulas', nombre: 'particulas', margen: 200, dibujar: (ctx, c) => dibujarParticulas(ctx, c, est) }).addTo(mapa);
const capaRotulos = new CapaCanvas({ pane: 'rotulos', nombre: 'rotulos', dibujar: (ctx, c) => dibujarRotulos(ctx, c, est) }).addTo(mapa);
oleaje = new OleajeAnimado(capaOleaje, est);

const recuadro = L.rectangle([[DOMINIO.sur, DOMINIO.oeste], [DOMINIO.norte, DOMINIO.este]], {
  weight: 1, opacity: 0.55, dashArray: '2 5', fill: false, interactive: false,
}).addTo(mapa);
const AJUSTE_VISTA = { paddingTopLeft: [360, 84], paddingBottomRight: [40, 96] };
mapa.fitBounds([[DOMINIO.sur, DOMINIO.oeste], [DOMINIO.norte, DOMINIO.este]], AJUSTE_VISTA);

const rend = L.svg({ pane: 'trayectoria' });
const lineaFutura = L.polyline([], { renderer: rend, weight: 1.6, opacity: 0.35, dashArray: '2 5', interactive: false });
const lineaPasada = L.polyline([], { renderer: rend, weight: 2.4, opacity: 0.95, interactive: false });
const marcaCentroide = L.circleMarker([0, 0], { renderer: rend, radius: 4.5, weight: 2, fillColor: '#fbf6ea', fillOpacity: 1, interactive: false });
const grupoTrayectoria = L.layerGroup([lineaFutura, lineaPasada, marcaCentroide]);

const marcador = L.marker([est.punto.lat, est.punto.lon], {
  draggable: true, title: 'Punto de liberación (arrastrable)', zIndexOffset: 1000,
  icon: L.divIcon({
    className: 'marcador-liberacion', iconSize: [24, 32], iconAnchor: [12, 32],
    html: '<svg width="24" height="32" viewBox="0 0 24 32"><path d="M12 31s10-10.6 10-18.5A10 10 0 0 0 2 12.5C2 20.4 12 31 12 31z" fill="#1d3557" stroke="#fbf6ea" stroke-width="1.5"/><circle cx="12" cy="12.5" r="3.6" fill="#b07d10"/></svg>',
  }),
}).addTo(mapa);
// El radio inicial es un círculo en metros: está a escala del mapa en cualquier zoom.
const circuloRadio = L.circle([est.punto.lat, est.punto.lon], {
  radius: 5000, weight: 1.2, dashArray: '4 4', fillOpacity: 0.05, interactive: false,
}).addTo(mapa);

function ponerBase(nombre) {
  if (!bases[nombre]) nombre = 'carta';
  est.base = nombre;
  document.body.dataset.base = nombre;
  for (const [k, capa] of Object.entries(bases)) {
    if (!capa) continue;
    if (k === nombre) capa.addTo(mapa); else mapa.removeLayer(capa);
  }
  const p = paleta(est);
  for (const v of [recuadro, lineaFutura, lineaPasada, marcaCentroide, circuloRadio]) v.setStyle({ color: p.tinta });
  circuloRadio.setStyle({ fillColor: p.tinta });
  const radio = document.querySelector(`input[name="base"][value="${nombre}"]`);
  if (radio) radio.checked = true;
  pintarLeyenda();
  redibujar();
  capaReticula.redibujar();
}

const atribucionTexto = () => `${ATRIBUCION[est.base]} · costa y localidades © colaboradores de OpenStreetMap`;

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
  $('btn-simular').disabled = !est.campos || !est.costa || nombre === 'calculando' || nombre === 'validando';
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
// Datos: costa del modelo, validación y carga del oleaje
// ---------------------------------------------------------------------------
async function cargarCosta() {
  const info = await api.costa();
  const [tierra, contexto] = await Promise.all([
    api.binario(`${info.mascara_url}?v=${info.sha256.slice(0, 12)}`), api.binario(info.contexto_url),
  ]);
  est.costa = new Costa(info, tierra, contexto);
  bases.carta = new CapaCarta({ costa: est.costa, minZoom: 5, maxZoom: 11, attribution: 'tierra fuera del dominio: Natural Earth' });
  ponerBase(est.base);
  fijarPunto(est.punto.lat, est.punto.lon);
  const f = info.fuentes;
  $('fuentes').textContent = `Fuentes. Costa: ${f.costa.fuente}, ${f.costa.licencia}, datos al ${f.costa.datos_al.slice(0, 10)}. `
    + `Localidades y puertos: OpenStreetMap, ${f.localidades.licencia}. Tierra fuera del dominio: ${f.contexto.fuente} (${f.contexto.licencia}). `
    + 'Satélite: Sentinel-2 cloudless 2016 de EOX IT Services GmbH, CC BY 4.0.';
  try {
    est.localidades = (await api.localidades()).localidades;
    capaRotulos.redibujar();
  } catch { est.localidades = []; }
}

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
  const costaLista = cargarCosta().catch((e) => {
    ponerEstado('error', 'No se pudo cargar la costa del modelo', cajaError(e.detalle || { causa: e.message, accion: 'Recarga la página.' }));
    throw e;
  });
  if (!salud.datos_disponibles) { costaLista.catch(() => {}); sinDatos(); return; }
  try { await costaLista; } catch { return; }
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
  ajustarOleaje();
  redibujar();
  if (!recorridoVisto()) recorrido.iniciar();
}

// ---------------------------------------------------------------------------
// Punto de liberación y ajustes
// ---------------------------------------------------------------------------
function problemaPunto(lat, lon) {
  if (!(lat >= DOMINIO.sur && lat <= DOMINIO.norte && lon >= DOMINIO.oeste && lon <= DOMINIO.este)) {
    return 'Fuera del recuadro punteado de la malla (lat 16.92…23.00, lon −92.08…−84.08).';
  }
  if (est.costa && est.costa.enTierra(lon, lat)) return 'El punto está en tierra. Elige un punto en el mar.';
  return null;
}

function fijarPunto(lat, lon, { mover = true } = {}) {
  est.punto = { lat, lon };
  $('p-lat').value = lat.toFixed(3);
  $('p-lon').value = lon.toFixed(3);
  $('p-gm').textContent = fmtCoordGM(lat, lon);
  if (mover) marcador.setLatLng([lat, lon]);
  circuloRadio.setLatLng([lat, lon]);
  const problema = problemaPunto(lat, lon);
  $('aviso-punto').hidden = !problema;
  $('aviso-punto').textContent = problema || '';
  if (!problema && est.costa) est.puntoValidoEn = performance.now();
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
  if (!est.campos || !est.costa) return;
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
      const t = await esperarTrabajo(trabajo_id, (tr) => { $('estado-texto').textContent = `Calculando · hora ${tr.avance} de ${tr.total}`; });
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
  est.arriboElegido = null;
  escribirParametros(reg.parametros);
  configurarLineaTiempo();
  lineaFutura.setLatLngs(reg.resultados.series.centroide.filter(Boolean).map((c) => [c[1], c[0]]));
  grupoTrayectoria.addTo(mapa);
  renderResultado($('resultado'), est.sim, { alElegir: irAlArribo, alExportarImagen: exportarImagen, alImprimir: imprimirResumen });
  $('pasos').querySelector('[data-paso="3"]').disabled = false;
  $('ley-sim').hidden = false;
  $('lt-rapidez').hidden = false;
  irPaso(3);
  estadoResultado();
  mapa.fitBounds(limitesSimulacion().pad(0.3), { paddingTopLeft: [370, 90], paddingBottomRight: [60, 110], maxZoom: 10 });
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

// Clic en una fila de la tabla de arribos: el mapa va a ese tramo y a ese momento.
function irAlArribo(a) {
  pausar();
  est.arriboElegido = a.zona;
  document.querySelectorAll('#resultado .arribo').forEach((f) => f.setAttribute('aria-selected', String(f.dataset.zona === a.zona)));
  const [o, s, e, n] = a.limites;
  const m = 0.04;
  mapa.fitBounds([[s - m, o - m], [n + m, e + m]], { paddingTopLeft: [370, 100], paddingBottomRight: [60, 120], maxZoom: 10.5 });
  ponerHora(a.primer_arribo_h);
}

// ---------------------------------------------------------------------------
// Línea de tiempo: fechas reales (UTC y Quintana Roo), marcas por día, saltos y velocidad
// ---------------------------------------------------------------------------
const horaMaxima = () => (est.sim ? est.sim.H : HORIZONTE_MAX);
const inicioTiempo = () => (est.sim ? est.sim.inicio : (est.campos ? est.campos.inicio : null));

function configurarLineaTiempo() {
  const H = horaMaxima(), t0 = inicioTiempo();
  $('lt-slider').max = String(H);
  const marcas = [];
  if (t0) {
    for (let h = 0; h <= H; h++) {
      const f = sumarHoras(t0, h);
      if (h !== 0 && f.getUTCHours() !== 0) continue;
      marcas.push(el('i', { style: `left:${(100 * h) / H}%`, 'data-hora': h }, el('span', {}, fmtDiaMes(f))));
    }
  }
  $('lt-dias').replaceChildren(...marcas);
  ponerHora(Math.min(est.hora, H));
}

let horaDensidad = -1, horaOleaje = -1;
function ponerHora(h) {
  est.hora = acotar(h, 0, horaMaxima());
  const entera = Math.floor(est.hora + 1e-6);
  $('lt-slider').value = String(Math.round(est.hora));
  $('lt-h').textContent = `Hora ${entera} de ${horaMaxima()}`;
  const t0 = inicioTiempo();
  if (t0) {
    const f = sumarHoras(t0, entera);
    $('lt-utc').textContent = fmtFechaUTC(f);
    $('lt-local').textContent = `${fmtFechaQRoo(f)} · Quintana Roo (UTC−5)`;
  }
  if (est.sim) {
    const r = est.sim.rapidezConglomerado(est.hora);
    $('lt-kn').textContent = r ? fmtRapidez(r.ms) : 'sin sargazo a flote';
    $('lt-rumbo').textContent = r ? `rumbo ${fmtRumbo(r.rumbo)}` : '';
  }
  actualizarTrayectoria();
  if (Math.round(est.hora) !== horaDensidad) { horaDensidad = Math.round(est.hora); capaDensidad.redibujar(); }
  if (!animando() && est.hora !== horaOleaje) { horaOleaje = est.hora; capaOleaje.redibujar(); }
  notaOleaje();
  capaParticulas.redibujar();
  if (ultimoHover) mostrarHover(ultimoHover);
}

function actualizarTrayectoria() {
  if (!est.sim) { mapa.removeLayer(grupoTrayectoria); return; }
  const c = est.sim.series.centroide;
  const pasadas = [];
  const h0 = Math.floor(est.hora);
  let actual = null;
  for (let h = 0; h <= h0; h++) if (c[h]) { pasadas.push([c[h][1], c[h][0]]); actual = c[h]; }
  // Entre horas el centroide avanza en línea recta hacia el de la hora siguiente.
  const sig = c[h0 + 1];
  if (actual && c[h0] && sig && est.hora > h0) {
    const f = est.hora - h0;
    actual = [c[h0][0] + f * (sig[0] - c[h0][0]), c[h0][1] + f * (sig[1] - c[h0][1])];
    pasadas.push([actual[1], actual[0]]);
  }
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
  let ultimo = performance.now();
  const paso = (t) => {
    if (!est.reproduciendo) return;
    const dt = Math.min(250, t - ultimo) / 1000;
    ultimo = t;
    const h = est.hora + dt * est.velocidad;
    if (h >= horaMaxima()) { ponerHora(horaMaxima()); pausar(); return; }
    ponerHora(h);
    animacion = requestAnimationFrame(paso);
  };
  animacion = requestAnimationFrame(paso);
}

// Al pausar se conserva el instante exacto (aunque caiga entre dos horas).
function pausar() {
  est.reproduciendo = false;
  if (animacion) cancelAnimationFrame(animacion);
  animacion = null;
  $('linea-tiempo').classList.remove('reproduciendo');
  $('btn-play').setAttribute('aria-label', 'Reproducir');
}

function saltar(horas) {
  pausar();
  const base = horas > 0 ? Math.floor(est.hora + 1e-6) : Math.ceil(est.hora - 1e-6);
  ponerHora(base + horas);
}

// ---------------------------------------------------------------------------
// Oleaje: animado o fijo, y qué dice el archivo
// ---------------------------------------------------------------------------
function ajustarOleaje() {
  if (animando()) oleaje.iniciar();
  else { oleaje.detener(); capaOleaje.redibujar(); }
  $('ver-animar').disabled = !est.ver.oleaje;
  $('nota-animar').textContent = movimientoReducido.matches && !est.ver.animar ? 'apagado: el sistema pide reducir el movimiento' : '';
  $('ref-ola').hidden = !est.ver.oleaje;
  notaOleaje();
}

function notaOleaje() {
  const n = $('nota-ola');
  if (!est.campos || !est.ver.oleaje) { n.hidden = true; return; }
  n.hidden = false;
  const texto = est.campos.identicos
    ? `Oleaje constante: los ${est.campos.horas.length} bloques del archivo son idénticos.`
    : `Oleaje del pronóstico: bloque +${est.campos.horas[est.campos.bloque(est.hora)]} h, interpolado cada hora.`;
  if (n.textContent !== texto) n.textContent = texto;
}

// ---------------------------------------------------------------------------
// Escalas y leyenda
// ---------------------------------------------------------------------------
function actualizarEscala() {
  const e = medirEscala(mapa);
  est.escala = e;
  $('esc-km').style.width = `${e.pxKm}px`;
  $('esc-mn').style.width = `${e.pxMn}px`;
  $('esc-km-t').textContent = `${fmtNum(e.km, e.km < 1 ? 1 : 0)} km`;
  $('esc-mn-t').textContent = `${fmtNum(e.mn, e.mn < 1 ? 1 : 0)} MN`;
}

function pintarLeyenda() {
  // Las muestras usan los colores del mapa base activo sobre su fondo de mar, para que la
  // leyenda se lea igual que el mapa.
  const p = paleta(est);
  const [r, g, b] = p.densidad;
  const capa = (k) => `rgba(${r}, ${g}, ${b}, ${ALFA_DENSIDAD[k]})`;
  $('ley-densidad').replaceChildren(...CLASES_DENSIDAD.map((v, k) => el('span', { class: 'clase' },
    el('i', { style: `background: linear-gradient(${capa(k)}, ${capa(k)}), ${p.fondo}` }),
    CLASES_DENSIDAD[k + 1] ? `${v}–${CLASES_DENSIDAD[k + 1]}` : `≥ ${v}`)));
  $('ley-estelas').replaceChildren(...p.rapidez.map((color, k) => el('i', { style: `background:${color}; width:${7 + 4 * k}px` })));
  const ley = $('leyenda').style;
  ley.setProperty('--ley-fondo', p.fondo);
  ley.setProperty('--ley-tinta', p.tinta);
  ley.setProperty('--ley-varada', p.varada);
  const svg = $('ref-ola-svg');
  svg.setAttribute('width', String(PX_POR_METRO + 4));
  svg.dataset.px = String(PX_POR_METRO);
  svg.innerHTML = `<path d="M2 6h${PX_POR_METRO}" stroke="#1f5c7a" stroke-width="1.3" fill="none"/><path d="M${PX_POR_METRO - 3} 2.8l5 3.2-5 3.2" stroke="#1f5c7a" stroke-width="1.3" fill="none"/>`;
}

// ---------------------------------------------------------------------------
// Hover: coordenadas, ola interpolada como en el modelo y, en pausa, la partícula más cercana
// ---------------------------------------------------------------------------
let ultimoHover = null;
let pendienteHover = false;

function mostrarHover(e) {
  const tt = $('tooltip');
  const { lat, lng: lon } = e.latlng;
  const lineas = [
    el('div', { 'data-prueba': 'tt-coord' }, el('b', {}, `${fmtLat(lat)} · ${fmtLon(lon)}`)),
    el('div', { class: 'tt-gm' }, fmtCoordGM(lat, lon)),
  ];
  if (est.campos) {
    const enTierra = est.costa && est.costa.enTierra(lon, lat);
    const ola = enTierra ? null : est.campos.olaEn(lon, lat, est.hora);
    lineas.push(el('div', { 'data-prueba': 'tt-ola' }, enTierra ? 'Tierra (costa del modelo)'
      : ola ? `Ola ${fmtNum(ola.altura, 2)} m · desde ${fmtNum(ola.desde)}° (${rumbo16(ola.desde)})${ola.extendida ? ' · extendida a la costa' : ''}`
        : 'Sin dato de ola en esta zona'));
  }
  if (est.sim && !est.reproduciendo && e.containerPoint) {
    const c = capaParticulas;
    const n = est.sim.masCercana(est.hora, (x) => c.x(x), (y) => c.y(y), e.containerPoint.x + c.mg, e.containerPoint.y + c.mg, RADIO_HOVER_PX, est.costa);
    if (n >= 0 && est.hora < est.sim.H) {
      const v = est.sim.velocidad(n, est.hora, [0, 0]);
      const rumbo = ((Math.atan2(v[0], v[1]) * 180) / Math.PI + 360) % 360;
      lineas.push(el('div', { class: 'tt-particula', 'data-prueba': 'tt-particula' },
        el('b', {}, `Partícula ${n + 1}`), ` · ${fmtRapidez(Math.hypot(v[0], v[1]))} · rumbo ${fmtRumbo(rumbo)}`));
    }
  }
  tt.replaceChildren(...lineas);
  tt.hidden = false;
  const p = e.originalEvent ? { x: e.originalEvent.clientX, y: e.originalEvent.clientY } : mapa.latLngToContainerPoint(e.latlng);
  const w = tt.offsetWidth, h = tt.offsetHeight;
  tt.style.left = `${p.x + 16 + w > window.innerWidth - 10 ? p.x - w - 14 : p.x + 16}px`;
  tt.style.top = `${p.y + 16 + h > window.innerHeight - 80 ? p.y - h - 12 : p.y + 16}px`;
}

mapa.on('mousemove', (e) => {
  ultimoHover = e;
  if (pendienteHover) return;
  pendienteHover = true;
  requestAnimationFrame(() => { pendienteHover = false; if (ultimoHover) mostrarHover(ultimoHover); });
});
mapa.getContainer().addEventListener('mouseleave', () => { ultimoHover = null; $('tooltip').hidden = true; });

// ---------------------------------------------------------------------------
// Exportar: imagen del mapa y resumen de una página
// ---------------------------------------------------------------------------
async function exportarImagen() {
  pausar();
  const { lienzo, sustituido } = await componerImagen(mapa, est, atribucionTexto());
  const nombre = nombreArchivo(est, 'png');
  const bytes = await descargarLienzo(lienzo, nombre);
  est.ultimaExportacion = { tipo: 'imagen', nombre, ancho: lienzo.width, alto: lienzo.height, bytes, sustituido };
  return est.ultimaExportacion;
}

async function imprimirResumen() {
  if (!est.sim) return null;
  pausar();
  const { lienzo, sustituido } = await componerImagen(mapa, est, atribucionTexto());
  const f = est.costa.info.fuentes;
  armarInforme($('informe'), mapa, est, lienzo, {
    atribucion: atribucionTexto(),
    fuentes: [
      `Oleaje: ${est.sim.reg.datos.archivo} de ${est.sim.reg.datos.fuente}.`,
      `Costa del modelo: ${f.costa.fuente}; ${f.costa.atribucion}, ${f.costa.licencia}.`,
      'Validación contra sargazo observado por satélite: página /validacion.',
    ],
  });
  const img = $('informe').querySelector('img');
  if (img && img.decode) { try { await img.decode(); } catch { /* se imprime igual */ } }
  est.ultimaExportacion = { tipo: 'informe', sustituido };
  window.print();
  return est.ultimaExportacion;
}

// ---------------------------------------------------------------------------
// Historial y panel de capas
// ---------------------------------------------------------------------------
async function cargarHistorial() {
  try { est.historial = await api.simulaciones(); } catch { est.historial = []; }
  marcarHistorial();
}

function marcarHistorial() {
  renderHistorial($('lista-hist'), $('hist-n'), est.historial, est.sim && est.sim.id, abrirDesdeHistorial);
}

function mostrarPanel(id, boton, abierto) {
  for (const [otro, b] of [['historial', 'btn-historial'], ['capas', 'btn-capas']]) {
    const ver = otro === id ? abierto : false;
    $(otro).hidden = !ver;
    $(b).setAttribute('aria-expanded', String(ver));
  }
}
const mostrarHistorial = (abierto) => mostrarPanel('historial', 'btn-historial', abierto);
const mostrarCapas = (abierto) => mostrarPanel('capas', 'btn-capas', abierto);

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
      'PMS estima hacia dónde podría derivar un conglomerado de sargazo frente a la Península de Yucatán durante los próximos 5 días y a qué tramos de costa llegaría primero.',
      'Este recorrido le muestra cada función con una simulación real frente a Cancún. Toma unos tres minutos; puede saltarlo y volver a abrirlo con «Recorrido guiado».',
    ],
    alEntrar: () => { pausar(); mostrarHistorial(false); mostrarCapas(false); $('estado-detalle').hidden = true; },
  },
  {
    titulo: 'Los datos: el oleaje de SEMAR',
    texto: [
      'PMS usa un solo archivo de SEMAR, dirmarea.txt: altura y dirección de la ola de viento en una malla de 0.16° (unos 17 km), cada 3 horas hasta 120 h.',
      'Los trazos del mapa fluyen hacia donde viaja la ola: son más largos y corren más donde la ola es más alta. La flecha «1 m» de este recuadro mide lo mismo en cualquier zoom. El archivo actual es una muestra: sus 41 bloques son idénticos y por eso el oleaje no cambia con la hora.',
    ],
    objetivo: () => $('escalas'),
  },
  {
    titulo: 'La carta: costa, localidades y mapa base',
    texto: [
      'La línea de costa de la carta es la misma que usa el modelo para decidir qué vara (OpenStreetMap, celdas de unos 100 m). Las ciudades y los puertos aparecen al acercar; el rombo marca los que tienen puerto o terminal marítima.',
      'En «Mapa y capas» puede cambiar a la vista de satélite o a la de calles, y encender o apagar el oleaje, su animación, las estelas, la densidad y las localidades.',
    ],
    alEntrar: () => mostrarCapas(true),
    alSalir: () => mostrarCapas(false),
    objetivo: () => $('capas'),
  },
  {
    titulo: 'Paso 1 · Fije el punto de liberación',
    texto: [
      'Haga clic en el mar, dentro del recuadro iluminado frente a Cancún, para soltar el conglomerado. El círculo punteado es su radio inicial, a escala del mapa.',
      'Fuera del recorrido también puede escribir la latitud y la longitud o arrastrar el marcador. Debajo se muestran en grados y minutos.',
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
      hecho: () => `Simulación lista: ${fmtNum(est.sim.reg.resumen.varadas_pct, 1)} % varado en ${est.sim.H} h.`,
    },
  },
  {
    titulo: 'Cómo leer el mapa',
    texto: [
      'Cada punto es una partícula a flote y deja una estela de sus últimas 6 horas: más larga y más oscura cuanto más rápido va, así se nota que el movimiento no es uniforme. Cada anillo rojo es una partícula varada, justo sobre la línea de costa.',
      'El sombreado es la densidad y el contorno punteado encierra el 90 % del sargazo. La línea gruesa es la trayectoria central.',
    ],
    alEntrar: () => {
      pausar();
      mapa.fitBounds(limitesSimulacion().pad(0.3), { paddingTopLeft: [420, 120], paddingBottomRight: [420, 120], maxZoom: 10, animate: false });
      ponerHora(Math.min(12, horaMaxima()));
    },
    objetivo: () => (est.sim ? rectMapa(limitesSimulacion().pad(0.15)) : null),
  },
  {
    titulo: 'Escalas y leyenda',
    texto: [
      'La barra doble mide kilómetros y millas náuticas y se ajusta al hacer zoom. La densidad se lee en porcentaje del sargazo liberado por celda de unos 4.4 km.',
      '«Ver detalle» explica cada símbolo y lista las fuentes. El aviso de límites y el enlace a la validación contra satélite están siempre al pie.',
    ],
    objetivo: () => $('leyenda'),
  },
  {
    titulo: 'La línea de tiempo',
    texto: [
      'Muestra la hora del pronóstico («hora 12 de 120») con su fecha en UTC y en hora de Quintana Roo; las marcas son los días. Reproduzca, salte 3, 6 o 12 horas y cambie la velocidad. «Conglomerado» es la rapidez del sargazo en ese momento, en nudos y km/h.',
      'En pausa, pase el cursor sobre una partícula para ver su rapidez y su rumbo. Atajos: espacio reproduce o pausa; ← y → mueven una hora; con Mayús, un salto.',
    ],
    objetivo: () => $('linea-tiempo'),
  },
  {
    titulo: 'Paso 3 · La tabla de arribos',
    texto: [
      'Es el resultado principal: para cada tramo de costa, cuándo llega la primera partícula (fecha y hora de Quintana Roo), qué porcentaje del sargazo llega y cuánto recorre, en kilómetros y millas náuticas.',
      'Toque una fila y el mapa irá a ese tramo y a ese momento. Son fracciones de partículas simuladas, no certezas; «Ver detalle» tiene los parámetros, las horas en UTC y las advertencias.',
    ],
    alEntrar: () => irPaso(3),
    objetivo: () => $('hoja'),
  },
  {
    titulo: 'Exportar el resultado',
    texto: [
      '«Guardar imagen del mapa» descarga el mapa como está, con fecha, escalas y fuentes. «Resumen de una página» arma una hoja para imprimir o guardar como PDF con los parámetros, la tabla de arribos, las escalas y los límites del modelo.',
    ],
    alEntrar: () => { irPaso(3); const d = document.querySelector('#resultado .exportar'); if (d) d.scrollIntoView({ block: 'nearest' }); },
    objetivo: () => document.querySelector('#resultado .exportar'),
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
      'Ya conoce el flujo completo: punto de liberación, ajustes, resultado y exportación. Puede repetir este recorrido cuando quiera con el botón «Recorrido guiado».',
      'Recuerde que PMS es un pronóstico probabilístico de muestra, solo con oleaje: úselo para explorar escenarios, no como una predicción de arribo exacta.',
    ],
  },
]);
window.pmsRecorrido = recorrido;
$('btn-recorrido').addEventListener('click', () => recorrido.iniciar());

// ---------------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------------
function redibujar() {
  capaDensidad.redibujar();
  capaOleaje.redibujar();
  capaParticulas.redibujar();
  capaRotulos.redibujar();
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

$('btn-historial').addEventListener('click', () => mostrarHistorial($('historial').hidden));
$('btn-capas').addEventListener('click', () => mostrarCapas($('capas').hidden));
document.querySelectorAll('input[name="base"]').forEach((r) => r.addEventListener('change', () => { if (r.checked) ponerBase(r.value); }));
for (const [id, clave] of [['ver-oleaje', 'oleaje'], ['ver-animar', 'animar'], ['ver-estelas', 'estelas'], ['ver-densidad', 'densidad'], ['ver-localidades', 'localidades']]) {
  $(id).checked = est.ver[clave];
  $(id).addEventListener('change', (e) => {
    est.ver[clave] = e.target.checked;
    if (clave === 'oleaje' || clave === 'animar') ajustarOleaje();
    redibujar();
  });
}
movimientoReducido.addEventListener('change', (e) => {
  est.ver.animar = !e.matches;
  $('ver-animar').checked = est.ver.animar;
  ajustarOleaje();
});

$('btn-play').addEventListener('click', () => (est.reproduciendo ? pausar() : reproducir_()));
$('lt-slider').addEventListener('input', (e) => { pausar(); ponerHora(Number(e.target.value)); });
$('btn-atras').addEventListener('click', () => saltar(-est.salto));
$('btn-adelante').addEventListener('click', () => saltar(est.salto));
$('lt-salto').addEventListener('change', (e) => {
  est.salto = Number(e.target.value);
  document.querySelectorAll('.salto-n').forEach((n) => { n.textContent = String(est.salto); });
});
$('lt-velocidad').addEventListener('change', (e) => { est.velocidad = Number(e.target.value); });
mapa.on('moveend zoomend resize', actualizarEscala);

document.addEventListener('keydown', (e) => {
  if (window.pmsRecorridoActivo) return;
  // Escape cierra los paneles aunque el foco esté en una de sus casillas.
  if (e.code === 'Escape') { mostrarHistorial(false); mostrarCapas(false); $('estado-detalle').hidden = true; return; }
  const activo = document.activeElement;
  if (activo && ['INPUT', 'SELECT', 'TEXTAREA'].includes(activo.tagName) && activo.type !== 'range') return;
  if (e.code === 'Space') { e.preventDefault(); if (est.reproduciendo) pausar(); else reproducir_(); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); saltar(e.shiftKey ? -est.salto : -1); }
  else if (e.code === 'ArrowRight') { e.preventDefault(); saltar(e.shiftKey ? est.salto : 1); }
});

// Ganchos para las pruebas de interfaz y para inspeccionar desde la consola.
window.pmsDepurar = {
  capas: { reticula: capaReticula, densidad: capaDensidad, oleaje: capaOleaje, particulas: capaParticulas, rotulos: capaRotulos },
  oleaje,
  animando,
  ponerHora,
  ponerBase,
  exportarImagen,
  imprimirResumen,
  olaEn: (lon, lat, hora) => est.campos && est.campos.olaEn(lon, lat, hora),
  enTierra: (lon, lat) => !!est.costa && est.costa.enTierra(lon, lat),
  constantes: { PX_POR_METRO },
};

ponerBase('carta');
pintarLeyenda();
actualizarEscala();
fijarPunto(est.punto.lat, est.punto.lon);
irPaso(1);
configurarLineaTiempo();
iniciar().then(cargarHistorial);
