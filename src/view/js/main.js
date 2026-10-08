// Orquestador de la interfaz de PMS: estados de la app, mapa, línea de tiempo, hover e historial.
/* global L */
import { api, esperarTrabajo } from './api.js';
import { Campos, Simulacion } from './datos.js';
import { CapaCanvas, Flujo, dibujarDensidad, dibujarMalla, dibujarParticulas } from './capas.js';
import { actualizarResultado, bitacora, cajaError, listaVerificaciones, renderHistorial, renderLeyenda, renderResultado } from './paneles.js';
import {
  MS_A_NUDOS, dirDesde, dirHacia, el, fmtCoord, fmtFechaUTC, fmtHoraCancun, fmtLat, fmtLon, fmtNum, fmtPct,
  rumbo16, sumarHoras,
} from './util.js';

const $ = (id) => document.getElementById(id);
const DOMINIO = { oeste: -92, este: -84, sur: 16.92, norte: 23 };

const est = {
  estado: 'validando',
  conjunto: null,
  conjuntos: [],
  campos: null,
  sim: null,
  capa: 'deriva',
  hora: 0,
  alpha: 1,
  ver: { particulas: true, zona: true, densidad: true, trayectoria: true, malla: false, costa: false },
  punto: { lat: 21.12, lon: -86.66 },
  reproduciendo: false,
  historial: [],
  poligonosCosta: [],
  estadoPrevio: null,
  sinServidor: false, // despliegue sin servidor (Vercel): endpoints síncronos
};
window.pms = est; // facilita la inspección desde la consola y las pruebas de interfaz

// ---------------------------------------------------------------------------
// Mapa base y capas
// ---------------------------------------------------------------------------
const mapa = L.map('mapa', { minZoom: 5, maxZoom: 11, zoomSnap: 0.5, maxBounds: [[11, -100], [29, -76]] })
  .setView([20.55, -87.6], 7);
mapa.getContainer().classList.add('mapa-oscuro', 'seleccionando');
window.pmsMapa = mapa;
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
}).addTo(mapa);
mapa.attributionControl.setPrefix('<a href="https://leafletjs.com" title="Biblioteca de mapas">Leaflet</a>');
L.control.scale({ imperial: false, position: 'bottomright' }).addTo(mapa);

for (const [nombre, z] of [['densidad', 380], ['flujo', 390], ['malla', 395], ['particulas', 460], ['trayectoria', 470]]) {
  mapa.createPane(nombre).style.zIndex = z;
}
mapa.getPane('flujo').style.pointerEvents = 'none';

const capaDensidad = new CapaCanvas({ pane: 'densidad', nombre: 'densidad', dibujar: (ctx, c) => dibujarDensidad(ctx, c, est) }).addTo(mapa);
const capaMalla = new CapaCanvas({ pane: 'malla', nombre: 'malla', dibujar: (ctx, c) => dibujarMalla(ctx, c, est) }).addTo(mapa);
const capaParticulas = new CapaCanvas({ pane: 'particulas', nombre: 'particulas', dibujar: (ctx, c) => dibujarParticulas(ctx, c, est) }).addTo(mapa);
const flujo = new Flujo(mapa, est);

L.rectangle([[DOMINIO.sur, DOMINIO.oeste], [DOMINIO.norte, DOMINIO.este]], {
  color: '#5f86a3', weight: 1, dashArray: '2 5', fill: false, interactive: false,
}).bindTooltip('Dominio de la malla (0.16°)', { sticky: true }).addTo(mapa);

const rend = L.svg({ pane: 'trayectoria' });
const lineaFutura = L.polyline([], { renderer: rend, color: '#ffffff', weight: 2, opacity: 0.35, dashArray: '3 6', interactive: false });
const lineaPasada = L.polyline([], { renderer: rend, color: '#ffffff', weight: 2.6, opacity: 0.95, interactive: false });
const marcaCentroide = L.circleMarker([0, 0], { renderer: rend, radius: 6, color: '#061420', weight: 2.5, fillColor: '#ffffff', fillOpacity: 1, interactive: false });
const etiquetasHora = L.layerGroup();
const grupoTrayectoria = L.layerGroup([lineaFutura, lineaPasada, etiquetasHora, marcaCentroide]);
const grupoArribos = L.layerGroup().addTo(mapa);
const celdaHover = L.rectangle([[0, 0], [0, 0]], { renderer: rend, color: '#8fe8f0', weight: 1.4, dashArray: '3 3', fillOpacity: 0.05, interactive: false });
let capaCosta = null;

const iconoPin = L.divIcon({
  className: 'marcador-liberacion',
  html: '<svg class="pin" viewBox="0 0 26 34"><path d="M13 33s11-11.6 11-20A11 11 0 0 0 2 13c0 8.4 11 20 11 20z" fill="#2bb3c0" stroke="#04202a" stroke-width="2"/><circle cx="13" cy="13" r="4.2" fill="#04202a"/></svg>',
  iconSize: [26, 34], iconAnchor: [13, 34],
});
const marcador = L.marker([est.punto.lat, est.punto.lon], { icon: iconoPin, draggable: true, title: 'Punto de liberación (arrastrable)', zIndexOffset: 1000 }).addTo(mapa);
const circuloRadio = L.circle([est.punto.lat, est.punto.lon], { radius: 5000, color: '#2bb3c0', weight: 1.4, dashArray: '4 4', fillOpacity: 0.07, interactive: false }).addTo(mapa);

// ---------------------------------------------------------------------------
// Estados de la aplicación
// ---------------------------------------------------------------------------
function ponerEstado(nombre, { titulo, texto, progreso = null, detalle = [], acciones = [], paso = '' } = {}) {
  if (!['error', 'calculando', 'validando'].includes(nombre)) est.estadoPrevio = nombre;
  est.estado = nombre;
  $('estado').dataset.estado = nombre;
  $('estado-titulo').textContent = titulo;
  $('estado-texto').textContent = texto;
  $('estado-paso').textContent = paso;
  $('estado-progreso').hidden = progreso === null;
  if (progreso !== null) $('estado-progreso').firstElementChild.style.width = `${Math.round(progreso * 100)}%`;
  $('estado-detalle').replaceChildren(...[detalle].flat().filter(Boolean));
  $('estado-acciones').replaceChildren(...acciones.map(([t, f]) => el('button', { type: 'button', class: 'secundario', onclick: f }, t)));
  $('btn-simular').disabled = !est.campos || nombre === 'calculando' || nombre === 'validando';
}

function progresoEstado(fraccion, paso, texto) {
  $('estado-progreso').hidden = false;
  $('estado-progreso').firstElementChild.style.width = `${Math.round(fraccion * 100)}%`;
  if (paso !== undefined) $('estado-paso').textContent = paso;
  if (texto !== undefined) $('estado-texto').textContent = texto;
}

function mostrarVelo(contenido) {
  const velo = $('velo');
  if (!contenido) { velo.hidden = true; velo.replaceChildren(); return; }
  velo.replaceChildren(el('div', { class: 'velo-caja' }, contenido));
  velo.hidden = false;
}

function estadoSinDatos(motivo) {
  est.campos = null;
  ponerEstado('sin-datos', {
    titulo: 'Sin datos',
    texto: motivo || 'No hay archivos de entrada en data/. Sin ellos no se puede simular ni mostrar campos.',
    detalle: el('p', { class: 'meta' }, 'Se requieren 120 archivos horarios (.txt) con columnas LON, LAT, U, V, WindsfcSp, WindsfcDir, sfcPrimWaDir, sfcDirWindWa, más el campo de corrientes.'),
    acciones: [['Volver a buscar datos', () => iniciar()]],
  });
  mostrarVelo([
    el('h2', {}, 'Aún no hay datos para simular'),
    el('p', {}, 'PMS necesita el conjunto de 5 días que entrega SEMAR: 120 archivos de texto, uno por hora, en una malla de 0.16° con estas columnas:'),
    el('pre', {}, 'LON LAT U V WindsfcSp WindsfcDir sfcPrimWaDir sfcDirWindWa'),
    el('p', {}, 'y un campo de corrientes superficiales (LON LAT UO VO) en data/<conjunto>/corrientes/. Mientras se confirma el formato oficial, genera el conjunto sintético de demostración:'),
    el('pre', {}, 'python scripts/generar_datos_demo.py'),
    el('p', {}, 'Después presiona «Volver a buscar datos». No se muestra un mapa de resultados vacío para no confundirlo con un pronóstico.'),
  ]);
}

// ---------------------------------------------------------------------------
// Conjuntos de datos y validación
// ---------------------------------------------------------------------------
async function iniciar() {
  try {
    const salud = await api.salud();
    $('version').textContent = `App v${salud.version_app} · modelo ${salud.version_modelo}`;
    est.sinServidor = salud.trabajos_en_segundo_plano === false;
    $('aviso-historial').hidden = !salud.almacenamiento_efimero;
    est.conjuntos = await api.conjuntos();
  } catch (e) {
    ponerEstado('error', { titulo: 'Error', texto: 'No se pudo contactar al servidor.', detalle: cajaError(e.detalle || { causa: e.message }), acciones: [['Reintentar', () => iniciar()]] });
    return;
  }
  const sel = $('conjunto');
  sel.replaceChildren(...est.conjuntos.map((c) => el('option', { value: c.id }, `${c.nombre} — ${c.archivos} archivos`)));
  const conDatos = est.conjuntos.filter((c) => c.archivos > 0);
  if (!conDatos.length) { estadoSinDatos(); return; }
  const elegido = conDatos.find((c) => c.id === 'demo') || conDatos[0];
  sel.value = elegido.id;
  await cargarConjunto(elegido.id);
}

async function cargarConjunto(id, forzar = false) {
  pausar();
  const info = est.conjuntos.find((c) => c.id === id);
  if (est.conjunto !== id) limpiarSimulacion();
  est.conjunto = id;
  est.campos = null;
  mostrarVelo(null);
  if (!info || info.archivos === 0) { estadoSinDatos(`La carpeta data/${id}/ no contiene archivos horarios.`); return; }
  ponerEstado('validando', { titulo: 'Validando datos', texto: `Revisando ${info.archivos} archivos de data/${id}/…`, progreso: 0, paso: `0/${info.archivos + 1}` });
  let t;
  try {
    if (est.sinServidor) {
      $('estado-progreso').classList.add('indeterminado');
      t = { estado: 'terminado', resultado: await api.validacion(id) };
      $('estado-progreso').classList.remove('indeterminado');
    } else {
      const { trabajo_id } = await api.validar(id, forzar);
      t = await esperarTrabajo(trabajo_id, (tr) => progresoEstado(tr.avance / tr.total, `${tr.avance}/${tr.total}`, tr.mensaje));
    }
  } catch (e) {
    ponerEstado('error', { titulo: 'Error', texto: 'No se pudo validar el conjunto.', detalle: cajaError(e.detalle || { causa: e.message }), acciones: [['Reintentar', () => cargarConjunto(id, true)]] });
    return;
  }
  if (t.estado === 'error') {
    ponerEstado('error', { titulo: 'Error', texto: 'La validación falló.', detalle: cajaError(t.error), acciones: [['Reintentar', () => cargarConjunto(id, true)]] });
    return;
  }
  const rep = t.resultado;
  if (!rep.valido) {
    const errores = rep.verificaciones.flatMap((v) => v.hallazgos.filter((h) => h.nivel === 'error'));
    const primero = errores.find((h) => h.archivo) || errores[0] || { detalle: 'Error de validación.' };
    ponerEstado('error', {
      titulo: 'Error en los datos',
      texto: `El conjunto no pasó la validación (${errores.length} error${errores.length === 1 ? '' : 'es'}). No se puede simular hasta corregirlo.`,
      detalle: [cajaError({ causa: primero.detalle, archivo: primero.archivo, accion: primero.accion }), listaVerificaciones(rep)],
      acciones: [['Validar de nuevo', () => cargarConjunto(id, true)], ...(id !== 'demo' && est.conjuntos.some((c) => c.id === 'demo') ? [['Usar el demo válido', () => { $('conjunto').value = 'demo'; cargarConjunto('demo'); }]] : [])],
    });
    $('conjunto-meta').textContent = `${rep.archivos_encontrados} de ${rep.archivos_esperados} archivos · no válido`;
    mostrarVelo([
      el('h2', {}, 'Los datos no pasaron la validación'),
      el('p', {}, 'Para no mostrar campos incompletos como si fueran un pronóstico, el mapa queda deshabilitado. Revisa en el panel izquierdo la causa, el archivo afectado y la acción sugerida.'),
    ]);
    redibujarTodo();
    return;
  }
  try {
    est.campos = new Campos(await api.campos(id));
  } catch (e) {
    ponerEstado('error', { titulo: 'Error', texto: 'No se pudieron cargar los campos.', detalle: cajaError(e.detalle || { causa: e.message }), acciones: [['Reintentar', () => cargarConjunto(id, true)]] });
    return;
  }
  const r = rep.resumen_conjunto;
  $('conjunto-meta').textContent = `${r.archivos} archivos · ${r.inicio_utc.replace('T', ' ').replace('Z', '')} → ${r.fin_utc.replace('T', ' ').replace('Z', '')} UTC · ${fmtNum(r.puntos_malla)} nodos (${fmtNum(r.puntos_mar)} de mar)${r.sintetico ? ' · SINTÉTICO' : ''}`;
  configurarLineaTiempo();
  const detalleValidacion = resumenValidacion(rep);
  if (est.sim) {
    estadoResultado(detalleValidacion);
  } else {
    ponerEstado('listo', {
      titulo: 'Datos validados · listo para simular',
      texto: `${r.archivos}/120 archivos horarios, columnas, rangos, unidades y continuidad temporal correctos. Fija el punto de liberación y presiona «Simular».`,
      detalle: [resumenValidacion(rep)],
    });
  }
  redibujarTodo();
}

function resumenValidacion(rep) {
  const n = (e) => rep.verificaciones.filter((v) => v.estado === e).length;
  const adv = rep.verificaciones.filter((v) => v.estado === 'advertencia').map((v) => v.nombre.toLowerCase());
  return el('details', { class: 'bitacora', 'data-prueba': 'resumen-validacion' },
    el('summary', {}, `✓ ${n('ok')} verificaciones correctas${adv.length ? ` · ${adv.length} advertencia (${adv.join(', ')})` : ''} · ${rep.duracion_s.toFixed(2)} s`),
    listaVerificaciones(rep));
}

// ---------------------------------------------------------------------------
// Punto de liberación y formulario
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
    return 'El punto está fuera del dominio de la malla (lat 16.92…23.00, lon −92.00…−84.00).';
  }
  if (est.poligonosCosta.some((a) => dentroDePoligono(lon, lat, a))) {
    return 'El punto está en tierra según la costa aproximada del modelo. Elige un punto en el mar.';
  }
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
}

function leerParametros() {
  return {
    conjunto: est.conjunto,
    lat: Number($('p-lat').value),
    lon: Number($('p-lon').value),
    radio_km: Number($('p-radio').value),
    particulas: Number($('p-n').value),
    alpha_pct: Number($('p-alpha').value),
    kh_m2s: Number($('p-kh').value),
    horizonte_h: Number($('p-horizonte').value),
    semilla: Number($('p-semilla').value),
  };
}

function escribirParametros(p) {
  $('p-radio').value = p.radio_km;
  $('p-n').value = p.particulas;
  $('p-alpha').value = p.alpha_pct;
  $('p-kh').value = p.kh_m2s;
  $('p-horizonte').value = p.horizonte_h;
  $('p-semilla').value = p.semilla;
  actualizarEtiquetasForm();
  fijarPunto(p.lat, p.lon);
}

function actualizarEtiquetasForm() {
  const a = Number($('p-alpha').value);
  $('v-alpha').textContent = `${a.toFixed(1)} %`;
  est.alpha = a;
  const h = Number($('p-horizonte').value);
  $('v-horizonte').textContent = `${h} h${h % 24 === 0 ? ` (${h / 24} día${h === 24 ? '' : 's'})` : ''}`;
  circuloRadio.setRadius(Math.max(0, Number($('p-radio').value)) * 1000);
}

// ---------------------------------------------------------------------------
// Simulación
// ---------------------------------------------------------------------------
async function simular() {
  if (!est.campos) return;
  const formulario = $('parametros');
  const invalido = [...formulario.querySelectorAll('input')].find((i) => !i.checkValidity());
  if (invalido) {
    invalido.reportValidity();
    return;
  }
  const p = leerParametros();
  const problema = problemaPunto(p.lat, p.lon);
  if (problema) {
    mostrarError({ causa: problema, accion: 'Haz clic en un punto del mar dentro del recuadro punteado.' });
    return;
  }
  pausar();
  document.querySelector('.panel').scrollTo({ top: 0, behavior: 'smooth' }); // el progreso se ve en la tarjeta de estado
  ponerEstado('calculando', {
    titulo: 'Calculando trayectorias',
    texto: `${fmtNum(p.particulas)} partículas × ${p.horizonte_h} pasos horarios desde ${fmtCoord(p.lat, p.lon)}.`,
    progreso: 0, paso: `0/${p.horizonte_h} h`,
  });
  let t;
  try {
    if (est.sinServidor) {
      $('estado-progreso').classList.add('indeterminado');
      try {
        t = { estado: 'terminado', resultado: await api.simularSincrono(p) };
      } finally {
        $('estado-progreso').classList.remove('indeterminado');
      }
    } else {
      const { trabajo_id } = await api.simular(p);
      t = await esperarTrabajo(trabajo_id, (tr) => progresoEstado(tr.avance / tr.total, `${tr.avance}/${tr.total} h`));
    }
  } catch (e) {
    mostrarError(e.detalle || { causa: e.message });
    return;
  }
  if (t.estado === 'error') { mostrarError(t.error); return; }
  progresoEstado(1, `${p.horizonte_h}/${p.horizonte_h} h`, 'Guardando y preparando la animación…');
  await cargarHistorial();
  await abrirSimulacion(t.resultado, { reproducir: true });
}

function mostrarError(detalle) {
  const volver = est.estadoPrevio === 'resultado' && est.sim ? () => estadoResultado() : () => ponerEstado('listo', { titulo: 'Datos validados · listo para simular', texto: 'Corrige el problema y vuelve a presionar «Simular».' });
  ponerEstado('error', { titulo: 'Error', texto: 'No se pudo completar la simulación.', detalle: cajaError(detalle), acciones: [['Entendido', volver]] });
}

function estadoResultado(extra) {
  const s = est.sim;
  ponerEstado('resultado', {
    titulo: 'Resultado disponible',
    texto: `${s.id} · ${s.H} h · ${fmtNum(s.N)} partículas · guardado en el historial. Usa la línea de tiempo para explorar.`,
    detalle: [bitacora(s.reg.bitacora), extra],
  });
}

async function abrirSimulacion(reg, { reproducir = false } = {}) {
  if (reg.conjunto.id !== est.conjunto || !est.campos) {
    $('conjunto').value = reg.conjunto.id;
    est.sim = null;
    await cargarConjunto(reg.conjunto.id);
    if (!est.campos) return;
  }
  pausar();
  est.sim = new Simulacion(reg);
  est.alpha = reg.parametros.alpha_pct;
  escribirParametros(reg.parametros);
  configurarLineaTiempo();
  // Trayectoria central
  const pts = reg.resultados.series.centroide.map((c) => (c ? [c[1], c[0]] : null));
  lineaFutura.setLatLngs(pts.filter(Boolean));
  etiquetasHora.clearLayers();
  let previa = null;
  for (let h = 24; h <= est.sim.H; h += 24) {
    if (!pts[h]) continue;
    if (previa && L.latLng(previa).distanceTo(pts[h]) < 9000) continue; // evita etiquetas encimadas
    previa = pts[h];
    etiquetasHora.addLayer(L.marker(pts[h], { pane: 'trayectoria', interactive: false, icon: L.divIcon({ className: '', html: `<span class="etiqueta-hora">+${h} h</span>`, iconSize: [0, 0] }) }));
  }
  grupoTrayectoria.addTo(mapa);
  const panel = $('resultado');
  renderResultado(panel, est.sim, () => { panel.hidden = true; });
  panel.hidden = false;
  panel.scrollTop = 0;
  estadoResultado();
  // Encuadre: liberación + todas las posiciones finales dentro del dominio.
  const b = L.latLngBounds([[reg.parametros.lat, reg.parametros.lon]]);
  pts.forEach((p) => p && b.extend(p));
  const o = est.sim.H * est.sim.N;
  for (let n = 0; n < est.sim.N; n += 7) b.extend([est.sim.lat[o + n], est.sim.lon[o + n]]);
  mapa.fitBounds(b.pad(0.15), { paddingTopLeft: [330, 70], paddingBottomRight: [370, 90], maxZoom: 9 });
  ponerHora(0);
  marcarHistorial();
  if (reproducir) reproducir_();
}

function limpiarSimulacion() {
  est.sim = null;
  $('resultado').hidden = true;
  mapa.removeLayer(grupoTrayectoria);
  grupoArribos.clearLayers();
  marcarHistorial();
  configurarLineaTiempo();
}

// ---------------------------------------------------------------------------
// Línea de tiempo
// ---------------------------------------------------------------------------
function horaMaxima() {
  if (est.sim) return est.sim.H;
  if (est.campos) return est.campos.horas - 1;
  return 120;
}

function configurarLineaTiempo() {
  const max = horaMaxima();
  const s = $('lt-slider');
  s.max = String(max);
  $('lt-marcas').replaceChildren(...[0, 24, 48, 72, 96, 120].filter((h) => h <= max)
    .map((h) => el('span', { style: `left:${(h / max) * 100}%` }, `${h} h`)));
  ponerHora(Math.min(est.hora, max));
}

function inicio() {
  return est.sim ? est.sim.inicio : (est.campos ? est.campos.inicio : null);
}

function ponerHora(h) {
  const max = horaMaxima();
  est.hora = Math.max(0, Math.min(max, Math.round(h)));
  $('lt-slider').value = String(est.hora);
  $('lt-h').textContent = `+${est.hora} h`;
  const t0 = inicio();
  if (t0) {
    const f = sumarHoras(t0, est.hora);
    $('lt-utc').textContent = fmtFechaUTC(f);
    $('lt-local').textContent = fmtHoraCancun(f);
  }
  actualizarTrayectoria();
  actualizarArribos();
  if (est.sim && !$('resultado').hidden) actualizarResultado($('resultado'), est.sim, est.hora);
  capaDensidad.redibujar();
  capaParticulas.redibujar();
  if (ultimoHover) mostrarHover(ultimoHover);
}

function actualizarTrayectoria() {
  if (!est.sim || !est.ver.trayectoria) { mapa.removeLayer(grupoTrayectoria); return; }
  if (!mapa.hasLayer(grupoTrayectoria)) grupoTrayectoria.addTo(mapa);
  const c = est.sim.series.centroide;
  const pasadas = [];
  let actual = null;
  for (let h = 0; h <= est.hora; h++) if (c[h]) { pasadas.push([c[h][1], c[h][0]]); actual = c[h]; }
  lineaPasada.setLatLngs(pasadas);
  if (actual) { marcaCentroide.setLatLng([actual[1], actual[0]]); marcaCentroide.setStyle({ opacity: 1, fillOpacity: 1 }); }
  else marcaCentroide.setStyle({ opacity: 0, fillOpacity: 0 });
}

function actualizarArribos() {
  grupoArribos.clearLayers();
  if (!est.sim) return;
  const cuenta = est.sim.arribosHasta(est.hora);
  for (const [k, n] of cuenta) {
    const z = est.sim.zonas[k];
    if (!z || n / est.sim.N < 0.005) continue;
    grupoArribos.addLayer(L.marker([z.ancla[1], z.ancla[0]], {
      interactive: false, pane: 'trayectoria',
      icon: L.divIcon({ className: '', iconSize: [0, 0], html: `<span class="etiqueta-arribo"><b>${fmtPct(n / est.sim.N, n / est.sim.N < 0.1 ? 1 : 0)}</b><span>${z.nombre}</span></span>` }),
    }));
  }
}

let animacion = null;
function reproducir_() {
  if (est.reproduciendo) return;
  if (est.hora >= horaMaxima()) ponerHora(0);
  est.reproduciendo = true;
  $('linea-tiempo').classList.add('reproduciendo');
  $('btn-play').setAttribute('aria-label', 'Pausar');
  let ultimo = performance.now();
  let acumulado = 0;
  const paso = (t) => {
    if (!est.reproduciendo) return;
    acumulado += t - ultimo;
    ultimo = t;
    const intervalo = 1000 / Number($('lt-vel').value);
    if (acumulado >= intervalo) {
      acumulado = acumulado % intervalo;
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
// Hover: coordenadas y valores del nodo de malla más cercano
// ---------------------------------------------------------------------------
let ultimoHover = null;
let pendienteHover = false;

function mostrarHover(e) {
  const tt = $('tooltip');
  const { lat, lng: lon } = e.latlng;
  const filas = [];
  const campos = est.campos;
  let nodoTxt = 'Fuera de la malla de datos';
  let dens = null;
  if (campos) {
    const nodo = campos.nodoCercano(lon, lat);
    if (nodo) {
      const m = campos.resolucion / 2;
      celdaHover.setBounds([[nodo.lat - m, nodo.lon - m], [nodo.lat + m, nodo.lon + m]]);
      if (!mapa.hasLayer(celdaHover)) celdaHover.addTo(mapa);
      const v = campos.valoresNodo(nodo, est.hora);
      nodoTxt = `Nodo de malla más cercano: ${fmtLat(nodo.lat)} · ${fmtLon(nodo.lon)}`;
      const vel = Math.hypot(v.vu, v.vv);
      filas.push(['Viento', `${fmtNum(vel, 1)} m/s (${fmtNum(vel * MS_A_NUDOS, 1)} kn) desde ${fmtNum(dirDesde(v.vu, v.vv))}° ${rumbo16(dirDesde(v.vu, v.vv))}`]);
      if (v.mar) {
        const c = Math.hypot(v.cu, v.cv);
        filas.push(['Corriente', `${fmtNum(c, 2)} m/s hacia ${fmtNum(dirHacia(v.cu, v.cv))}° ${rumbo16(dirHacia(v.cu, v.cv))}`]);
        const du = v.cu + (est.alpha / 100) * v.vu, dv = v.cv + (est.alpha / 100) * v.vv;
        filas.push([`Deriva (α ${fmtNum(est.alpha, 1)} %)`, `${fmtNum(Math.hypot(du, dv), 2)} m/s hacia ${fmtNum(dirHacia(du, dv))}° ${rumbo16(dirHacia(du, dv))}`]);
        if (v.ola !== null) filas.push(['Oleaje', `desde ${fmtNum(v.ola)}° ${rumbo16(v.ola)}`]);
      } else {
        filas.push(['Superficie', 'Tierra: sin corriente ni oleaje']);
      }
      if (est.sim) {
        const d = est.sim.densidad(est.hora, campos);
        const n = d.conteo.get(nodo.k) || 0;
        dens = n
          ? el('div', { class: 'tt-dens' }, 'Partículas en esta celda: ', el('b', {}, fmtPct(n / est.sim.N)), ` (${fmtNum(n)} de ${fmtNum(est.sim.N)})`, d.zona.has(nodo.k) ? ' · dentro de la zona P90' : '')
          : el('div', { class: 'tt-dens' }, 'Sin partículas en esta celda a esta hora.');
      }
    } else if (mapa.hasLayer(celdaHover)) {
      mapa.removeLayer(celdaHover);
    }
  }
  tt.replaceChildren(
    el('div', { class: 'tt-coord', 'data-prueba': 'tt-coord' }, `${fmtLat(lat)} · ${fmtLon(lon)}`),
    el('div', { class: 'tt-nodo' }, `${nodoTxt} · +${est.hora} h`),
    filas.length ? el('dl', {}, filas.map(([k, v]) => [el('dt', {}, k), el('dd', {}, v)])) : null,
    dens,
  );
  tt.hidden = false;
  const zona = mapa.getContainer().getBoundingClientRect();
  const p = e.containerPoint;
  const w = tt.offsetWidth, h = tt.offsetHeight;
  // El tooltip se abre hacia el centro del mapa para no tapar los paneles laterales.
  tt.style.left = `${p.x > zona.width / 2 || p.x + 16 + w > zona.width ? Math.max(4, p.x - w - 16) : p.x + 16}px`;
  tt.style.top = `${p.y + 16 + h > zona.height - 80 ? p.y - h - 12 : p.y + 16}px`;
}

mapa.on('mousemove', (e) => {
  ultimoHover = e;
  if (pendienteHover) return;
  pendienteHover = true;
  requestAnimationFrame(() => { pendienteHover = false; if (ultimoHover) mostrarHover(ultimoHover); });
});
mapa.getContainer().addEventListener('mouseleave', () => {
  ultimoHover = null;
  $('tooltip').hidden = true;
  if (mapa.hasLayer(celdaHover)) mapa.removeLayer(celdaHover);
});

// ---------------------------------------------------------------------------
// Historial
// ---------------------------------------------------------------------------
async function cargarHistorial() {
  try {
    est.historial = await api.simulaciones();
  } catch { est.historial = []; }
  marcarHistorial();
}

function marcarHistorial() {
  renderHistorial($('lista-hist'), $('hist-contador'), est.historial, est.sim && est.sim.id, abrirDesdeHistorial);
}

async function abrirDesdeHistorial(id) {
  if (est.estado === 'calculando' || est.estado === 'validando') return;
  try {
    const reg = await api.simulacion(id);
    await abrirSimulacion(reg, { reproducir: false });
  } catch (e) {
    mostrarError(e.detalle || { causa: e.message });
  }
}

// ---------------------------------------------------------------------------
// Redibujo y eventos de controles
// ---------------------------------------------------------------------------
function redibujarTodo() {
  capaDensidad.redibujar();
  capaMalla.redibujar();
  capaParticulas.redibujar();
  flujo.sembrar();
  actualizarTrayectoria();
  renderLeyenda($('leyenda-cuerpo'), est.capa, Boolean(est.sim));
}

mapa.on('click', (e) => {
  if (est.estado === 'calculando') return;
  fijarPunto(e.latlng.lat, e.latlng.lng);
});
marcador.on('drag', (e) => circuloRadio.setLatLng(e.target.getLatLng()));
marcador.on('dragend', (e) => { const p = e.target.getLatLng(); fijarPunto(p.lat, p.lng, { mover: false }); });

for (const id of ['p-lat', 'p-lon']) {
  $(id).addEventListener('change', () => {
    const lat = Number($('p-lat').value), lon = Number($('p-lon').value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) fijarPunto(lat, lon);
  });
}
$('p-preset').addEventListener('change', (e) => {
  if (!e.target.value) return;
  const [lat, lon] = e.target.value.split(',').map(Number);
  fijarPunto(lat, lon);
  mapa.panTo([lat, lon]);
  e.target.value = '';
});
for (const id of ['p-alpha', 'p-horizonte', 'p-radio']) $(id).addEventListener('input', actualizarEtiquetasForm);
$('btn-semilla').addEventListener('click', () => { $('p-semilla').value = String(Math.floor(Math.random() * 1e6)); });
$('btn-simular').addEventListener('click', simular);
$('conjunto').addEventListener('change', (e) => cargarConjunto(e.target.value));

$('btn-play').addEventListener('click', () => (est.reproduciendo ? pausar() : reproducir_()));
$('btn-atras').addEventListener('click', () => { pausar(); ponerHora(est.hora - 1); });
$('btn-adelante').addEventListener('click', () => { pausar(); ponerHora(est.hora + 1); });
$('lt-slider').addEventListener('input', (e) => { pausar(); ponerHora(Number(e.target.value)); });

document.addEventListener('keydown', (e) => {
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName) && document.activeElement.type !== 'range') return;
  if (e.code === 'Space') { e.preventDefault(); if (est.reproduciendo) pausar(); else reproducir_(); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); pausar(); ponerHora(est.hora - 1); }
  else if (e.code === 'ArrowRight') { e.preventDefault(); pausar(); ponerHora(est.hora + 1); }
  else if (e.code === 'Home') { pausar(); ponerHora(0); }
  else if (e.code === 'End') { pausar(); ponerHora(horaMaxima()); }
});

document.querySelectorAll('.segmentado button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.segmentado button').forEach((o) => o.setAttribute('aria-checked', String(o === b)));
  est.capa = b.dataset.capa;
  flujo.sembrar();
  renderLeyenda($('leyenda-cuerpo'), est.capa, Boolean(est.sim));
}));
document.querySelectorAll('[data-ver]').forEach((c) => c.addEventListener('change', () => {
  est.ver[c.dataset.ver] = c.checked;
  if (c.dataset.ver === 'costa') {
    if (c.checked && capaCosta) capaCosta.addTo(mapa); else if (capaCosta) mapa.removeLayer(capaCosta);
  }
  redibujarTodo();
}));
$('leyenda-toggle').addEventListener('click', () => {
  const l = $('leyenda');
  const cerrada = l.dataset.cerrada === 'true';
  l.dataset.cerrada = String(!cerrada);
  $('leyenda-toggle').setAttribute('aria-expanded', String(cerrada));
});

// Costa del modelo (para validar clics y, opcionalmente, dibujarla).
api.costa().then((gj) => {
  const poligonos = gj.features.filter((f) => f.properties.tipo === 'costa');
  est.poligonosCosta = poligonos.map((f) => f.geometry.coordinates[0]);
  capaCosta = L.geoJSON({ type: 'FeatureCollection', features: poligonos }, {
    style: { color: '#ff9f6b', weight: 1.4, dashArray: '4 3', fillColor: '#ff9f6b', fillOpacity: 0.06 }, interactive: false,
  });
  fijarPunto(est.punto.lat, est.punto.lon);
}).catch(() => {});

fijarPunto(est.punto.lat, est.punto.lon);
actualizarEtiquetasForm();
renderLeyenda($('leyenda-cuerpo'), est.capa, false);
configurarLineaTiempo();
iniciar().then(cargarHistorial);
