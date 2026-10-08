// Render de paneles: validación, resultado, historial y leyenda.
import { el, fmtCoord, fmtFechaCorta, fmtNum, fmtPct } from './util.js';
import { CORTES_DENSIDAD, COLOR_SARGAZO, COLOR_VARADA, ESCALAS_FLUJO, RAMPA_DENSIDAD, RAMPA_FLUJO } from './capas.js';

const ICONO = { ok: '✓', advertencia: '!', error: '✕' };

export function listaVerificaciones(reporte) {
  return el('ul', { class: 'checks', 'data-prueba': 'verificaciones' },
    reporte.verificaciones.map((v, i) => el('li', { class: v.estado, style: `animation-delay:${i * 45}ms` },
      el('span', { class: 'ico', 'aria-label': v.estado }, ICONO[v.estado]),
      el('span', {},
        el('span', { class: 'nombre' }, v.nombre),
        v.resumen ? el('span', { class: 'resumen' }, v.resumen) : null,
        v.hallazgos.slice(0, 4).map((h) => el('span', { class: 'hallazgo' },
          h.archivo ? el('span', { class: 'archivo' }, `${h.archivo}: `) : null,
          h.detalle,
          h.accion ? ` → ${h.accion}` : '')),
        v.omitidos ? el('span', { class: 'hallazgo' }, `… y ${v.omitidos} hallazgos más.`) : null,
      ))));
}

export function cajaError(detalle) {
  return el('dl', { class: 'caja-error', 'data-prueba': 'caja-error' },
    el('dt', {}, 'Causa'), el('dd', {}, detalle.causa || 'Error desconocido'),
    detalle.archivo ? [el('dt', {}, 'Archivo afectado'), el('dd', {}, el('code', {}, detalle.archivo))] : null,
    el('dt', {}, 'Acción'), el('dd', {}, detalle.accion || 'Intenta de nuevo.'));
}

export function bitacora(lineas, abierta = false) {
  if (!lineas || !lineas.length) return null;
  return el('details', { class: 'bitacora', open: abierta },
    el('summary', {}, `Bitácora (${lineas.length})`),
    el('ol', {}, lineas.map((l) => el('li', {}, l))));
}

// ---------------------------------------------------------------------------
// Panel de resultado
// ---------------------------------------------------------------------------
export function renderResultado(contenedor, sim, alCerrar) {
  const r = sim.reg, s = r.resumen, p = r.parametros;
  contenedor.replaceChildren(
    el('div', { class: 'res-cab' },
      el('div', {},
        el('h2', {}, 'Resultado disponible'),
        el('p', { class: 'meta' }, `${r.id} · ${fmtFechaCorta(r.creada_utc)} (hora de Cancún)`)),
      el('button', { type: 'button', class: 'icono', title: 'Ocultar panel', 'aria-label': 'Ocultar panel de resultado', onclick: alCerrar }, '✕')),
    el('div', { class: 'res-chips' },
      r.conjunto.sintetico ? el('span', { class: 'chip aviso' }, 'Datos sintéticos') : null,
      r.conjunto.corrientes_esquematicas ? el('span', { class: 'chip aviso' }, 'Corrientes esquemáticas') : null,
      el('span', { class: 'chip aviso' }, 'Parámetros preliminares'),
      el('span', { class: 'chip' }, `${p.horizonte_h} h · ${fmtNum(p.particulas)} partículas`)),
    el('div', { 'data-dinamico': 'kpis' }),
    el('div', { class: 'res-seccion' },
      el('h3', {}, 'Trayectoria central (centroide a flote)'),
      el('p', {}, el('span', { class: 'grande' }, `${fmtNum(s.distancia_centroide_km, 0)} km recorridos`),
        ` · desplazamiento neto ${fmtNum(s.desplazamiento_neto_km, 0)} km hacia el ${s.rumbo_neto}`
        + (s.centroide_hasta_h < sim.H ? ` (hasta +${s.centroide_hasta_h} h: después queda < 1 % a flote)` : '') + '.')),

    el('div', { class: 'res-seccion' },
      el('h3', {}, 'Radio de dispersión P90 (km)'),
      el('div', { 'data-dinamico': 'grafica' }),
      el('div', { class: 'radios' },
        ['24', '48', '120'].map((h) => el('div', {}, `a +${h} h`,
          el('b', {}, s.radio_p90_km[h] === undefined ? 'n/d' : (s.radio_p90_km[h] === null ? '—' : `${fmtNum(s.radio_p90_km[h], 1)} km`))))),
      el('p', { class: 'meta' }, '90 % de las partículas a flote están a menos de esta distancia del centroide. Crece con el horizonte: la incertidumbre también.')),

    el('div', { class: 'res-seccion' },
      el('h3', {}, `Probabilidad de arribo por tramo de costa (a +${sim.H} h)`),
      s.arribos.length
        ? el('ul', { class: 'arribos', 'data-prueba': 'arribos' }, s.arribos.slice(0, 6).map((a) => el('li', {},
          el('span', { class: 'nombre' }, a.nombre, el('span', { class: 'etq-prob' }, a.etiqueta)),
          el('span', { class: 'pct' }, fmtPct(a.probabilidad)),
          el('span', { class: 'barra' }, el('i', { style: `width:${Math.max(2, (a.probabilidad / s.arribos[0].probabilidad) * 100)}%` })),
          el('span', { class: 'det' }, `${fmtNum(a.particulas)} partículas · primeras a +${a.primer_arribo_h} h · mediana +${a.arribo_mediano_h} h`))))
        : el('p', { class: 'vacio' }, 'Ninguna partícula varó en el horizonte simulado.'),
      el('p', { class: 'meta' }, 'Fracción de partículas simuladas que varan en cada tramo. Es una probabilidad del modelo, no una certeza de arribo a una playa específica.')),

    el('div', { class: 'res-seccion' },
      el('h3', {}, 'Advertencias'),
      el('ul', { class: 'advertencias' }, s.advertencias.map((a) => el('li', {}, a)))),

    el('details', { class: 'res-detalles' },
      el('summary', {}, 'Parámetros y trazabilidad'),
      el('dl', {},
        el('dt', {}, 'Liberación'), el('dd', {}, fmtCoord(p.lat, p.lon)),
        el('dt', {}, 'Radio inicial'), el('dd', {}, `${fmtNum(p.radio_km, 1)} km`),
        el('dt', {}, 'α (viento)'), el('dd', {}, `${fmtNum(p.alpha_pct, 1)} %`),
        el('dt', {}, 'K_h'), el('dd', {}, `${fmtNum(p.kh_m2s, 1)} m²/s`),
        el('dt', {}, 'Semilla'), el('dd', {}, String(p.semilla)),
        el('dt', {}, 'Modelo'), el('dd', {}, r.version_modelo),
        el('dt', {}, 'Conjunto'), el('dd', {}, `${r.conjunto.id} · ${r.conjunto.archivos} archivos (${r.conjunto.primero} … ${r.conjunto.ultimo})`),
        el('dt', {}, 'Huella SHA-256'), el('dd', {}, r.conjunto.huella_sha256.slice(0, 16) + '…'),
        el('dt', {}, 'Cálculo'), el('dd', {}, `${fmtNum(r.duracion_s, 2)} s`))),
    bitacora(r.bitacora),
  );
}

// Partes que cambian con la hora mostrada: KPIs y marcador de la gráfica.
export function actualizarResultado(contenedor, sim, hora) {
  const s = sim.reg.resumen;
  const conteo = sim.conteoEstados(hora);
  const kpis = contenedor.querySelector('[data-dinamico="kpis"]');
  if (kpis) {
    kpis.replaceChildren(
      el('div', { class: 'kpis', 'data-prueba': 'kpis' },
        kpi('Varadas', COLOR_VARADA, fmtPct(conteo.varadas / sim.N), `final +${sim.H} h: ${fmtNum(s.varadas_pct, 1)} %`),
        kpi('A flote', COLOR_SARGAZO, fmtPct(conteo.flote / sim.N), `final: ${fmtNum(s.a_flote_pct, 1)} %`),
        kpi('Fuera del dominio', '#8aa0b2', fmtPct(conteo.fuera / sim.N), `final: ${fmtNum(s.fuera_pct, 1)} %`)),
      el('p', { class: 'meta' }, `Valores en +${hora} h; el subtítulo muestra el final del horizonte.`));
  }
  const graf = contenedor.querySelector('[data-dinamico="grafica"]');
  if (graf) graf.replaceChildren(graficaRadio(sim, hora));
}

function kpi(titulo, color, valor, sub) {
  return el('div', { class: 'kpi' },
    el('div', { class: 'k-titulo' }, el('span', { class: 'marca-pt', style: `background:${color}` }), titulo),
    el('div', { class: 'k-valor' }, valor),
    el('div', { class: 'k-sub' }, sub));
}

const NS = 'http://www.w3.org/2000/svg';
function svg(etiqueta, attrs = {}, texto) {
  const n = document.createElementNS(NS, etiqueta);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (texto !== undefined) n.textContent = texto;
  return n;
}

// Radio P90 contra la hora: una sola serie, con marcador de la hora actual y hover.
function graficaRadio(sim, hora) {
  const serie = sim.series.radio_p90_km;
  const W = 320, H = 118, m = { l: 30, r: 10, t: 10, b: 20 };
  const maxV = Math.max(5, ...serie.filter((v) => v !== null));
  const techo = Math.ceil(maxV / 10) * 10;
  const x = (h) => m.l + (h / sim.H) * (W - m.l - m.r);
  const y = (v) => H - m.b - (v / techo) * (H - m.t - m.b);
  const g = svg('svg', { class: 'grafica-radio', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Radio de dispersión P90 en km por hora' });
  for (let k = 0; k <= 2; k++) {
    const v = (techo * k) / 2;
    g.append(svg('line', { class: k ? 'rejilla' : 'eje', x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }));
    g.append(svg('text', { x: m.l - 5, y: y(v) + 3, 'text-anchor': 'end' }, fmtNum(v)));
  }
  for (const h of [0, 24, 48, 72, 96, 120].filter((h) => h <= sim.H)) {
    g.append(svg('text', { x: x(h), y: H - 6, 'text-anchor': 'middle' }, `${h}`));
  }
  let d = '', area = '', abierto = false, ultimoX = null;
  serie.forEach((v, h) => {
    if (v === null) { abierto = false; return; }
    d += `${abierto ? 'L' : 'M'}${x(h).toFixed(1)},${y(v).toFixed(1)}`;
    area += `${abierto ? 'L' : `M${x(h).toFixed(1)},${y(0)}L`}${x(h).toFixed(1)},${y(v).toFixed(1)}`;
    abierto = true;
    ultimoX = x(h);
  });
  if (area) g.append(svg('path', { class: 'area', d: `${area}L${ultimoX},${y(0)}Z` }));
  g.append(svg('path', { class: 'linea', d }));
  const hh = Math.min(hora, sim.H);
  g.append(svg('line', { class: 'ahora', x1: x(hh), x2: x(hh), y1: m.t, y2: H - m.b }));
  if (serie[hh] !== null && serie[hh] !== undefined) {
    g.append(svg('circle', { class: 'punto', cx: x(hh), cy: y(serie[hh]), r: 4 }));
    g.append(svg('text', { class: 'etq', x: Math.min(x(hh) + 6, W - 60), y: Math.max(y(serie[hh]) - 6, 12) }, `+${hh} h: ${fmtNum(serie[hh], 1)} km`));
  }
  // Hover: línea guía y valor en la hora bajo el cursor.
  const guia = svg('line', { class: 'ahora', x1: 0, x2: 0, y1: m.t, y2: H - m.b, opacity: 0 });
  const etq = svg('text', { class: 'etq', x: 0, y: m.t + 10, opacity: 0 });
  g.append(guia, etq);
  g.addEventListener('mousemove', (ev) => {
    const caja = g.getBoundingClientRect();
    const px = ((ev.clientX - caja.left) / caja.width) * W;
    const h = Math.round(((px - m.l) / (W - m.l - m.r)) * sim.H);
    if (h < 0 || h > sim.H) return;
    guia.setAttribute('x1', x(h)); guia.setAttribute('x2', x(h)); guia.setAttribute('opacity', 0.6);
    etq.textContent = serie[h] === null ? `+${h} h: sin partículas a flote` : `+${h} h: ${fmtNum(serie[h], 1)} km`;
    etq.setAttribute('x', Math.min(x(h) + 6, W - 110)); etq.setAttribute('opacity', 1);
  });
  g.addEventListener('mouseleave', () => { guia.setAttribute('opacity', 0); etq.setAttribute('opacity', 0); });
  return g;
}

// ---------------------------------------------------------------------------
// Historial
// ---------------------------------------------------------------------------
export function renderHistorial(lista, contador, filas, activa, alAbrir) {
  contador.textContent = filas.length ? String(filas.length) : '';
  if (!filas.length) {
    lista.replaceChildren(el('li', { class: 'vacio' }, 'Aún no hay simulaciones guardadas. Ejecuta la primera con «Simular».'));
    return;
  }
  lista.replaceChildren(...filas.map((f) => {
    const p = f.parametros;
    return el('li', { class: f.id === activa ? 'activa' : '', 'data-id': f.id },
      el('button', { type: 'button', onclick: () => alAbrir(f.id), title: `Reabrir ${f.id}` },
        el('span', { class: 'hist-fila1' }, fmtFechaCorta(f.creada_utc), el('span', { class: 'chip' }, `${p.horizonte_h} h`)),
        el('span', { class: 'hist-fila2' }, `${fmtCoord(p.lat, p.lon)} · α ${fmtNum(p.alpha_pct, 1)} % · K_h ${fmtNum(p.kh_m2s)} · ${fmtNum(p.particulas)} part. · semilla ${p.semilla}`),
        el('span', { class: 'hist-fila3' }, `Varadas ${fmtNum(f.varadas_pct, 1)} %`,
          f.arribo_principal ? [' · principal: ', el('strong', {}, `${f.arribo_principal} (${fmtPct(f.arribo_principal_prob, 0)})`)] : ' · sin arribos')));
  }));
}

// ---------------------------------------------------------------------------
// Leyenda (unidades explícitas)
// ---------------------------------------------------------------------------
export function renderLeyenda(cuerpo, capa, haySim) {
  const filas = [];
  if (capa !== 'ninguna') {
    const esc = ESCALAS_FLUJO[capa];
    filas.push(el('div', { class: 'ley-titulo' }, `${esc.titulo} · ${esc.unidad}`),
      el('div', { class: 'ley-rampa' }, RAMPA_FLUJO.map((c) => el('i', { style: `background:${c}` }))),
      el('div', { class: 'ley-ticks' }, el('span', {}, '0'), esc.cortes.map((c) => el('span', {}, fmtNum(c, c < 1 ? 2 : 0))), el('span', {}, '')));
    if (capa === 'viento') filas.push(el('div', { class: 'ley-titulo' }, 'Trazos en la dirección HACIA la que sopla (el hover muestra la dirección DESDE).'));
  }
  filas.push(
    el('div', { class: 'ley-fila' }, simbolo('punto', COLOR_SARGAZO), 'Partícula de sargazo a flote'),
    el('div', { class: 'ley-fila' }, simbolo('anillo', COLOR_VARADA), 'Partícula varada en la costa'),
    el('div', { class: 'ley-fila' }, simbolo('linea'), 'Trayectoria central (centroide a flote)'),
    el('div', { class: 'ley-fila' }, simbolo('zona'), 'Zona probable P90 (celdas de 0.16° con el 90 % de las partículas)'),
    el('div', { class: 'ley-titulo' }, 'Densidad: % de partículas por celda de 0.16°'),
    el('div', { class: 'ley-rampa' }, RAMPA_DENSIDAD.map((c) => el('i', { style: `background:${c.replace(/[\d.]+\)$/, '0.95)')}` }))),
    el('div', { class: 'ley-ticks' }, CORTES_DENSIDAD.map((c) => el('span', {}, `${fmtNum(c * 100, c < 0.01 ? 1 : 0)} %`)), el('span', {}, '')),
  );
  if (!haySim) filas.push(el('div', { class: 'ley-titulo' }, 'Ejecuta una simulación para ver partículas, trayectoria y zona probable.'));
  cuerpo.replaceChildren(...filas);
}

function simbolo(tipo, color) {
  const s = svg('svg', { width: 22, height: 12, viewBox: '0 0 22 12', 'aria-hidden': 'true' });
  if (tipo === 'punto') s.append(svg('rect', { x: 9, y: 4, width: 4, height: 4, fill: color }));
  if (tipo === 'anillo') s.append(svg('circle', { cx: 11, cy: 6, r: 3.5, fill: 'none', stroke: color, 'stroke-width': 1.6 }));
  if (tipo === 'linea') { s.append(svg('path', { d: 'M1 6h20', stroke: '#fff', 'stroke-width': 2.4 })); }
  if (tipo === 'zona') s.append(svg('rect', { x: 2, y: 1.5, width: 18, height: 9, fill: 'rgba(255,255,255,0.08)', stroke: '#fff', 'stroke-width': 1.4, 'stroke-dasharray': '4 2' }));
  return s;
}
