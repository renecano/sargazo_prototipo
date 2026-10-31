// Contenido de los paneles: detalle de validación, resultado (paso 3) e historial.
import { el, fmtCoord, fmtFechaCorta, fmtNum, fmtPct } from './util.js';

const ICONO = { ok: '✓', advertencia: '!', error: '✕' };

// Verificaciones con algo que decir (errores y, si se pide, advertencias), cada una con su acción.
export function detalleValidacion(reporte, { soloErrores = false } = {}) {
  const relevantes = reporte.verificaciones.filter((v) => (soloErrores ? v.estado === 'error' : v.estado !== 'ok'));
  return el('ul', { class: 'checks', 'data-prueba': 'verificaciones' },
    relevantes.map((v) => el('li', { class: v.estado },
      el('span', { class: 'ico', 'aria-label': v.estado }, ICONO[v.estado]),
      el('span', {},
        el('span', { class: 'nombre' }, v.nombre),
        v.hallazgos.slice(0, 4).map((h) => el('span', { class: 'hallazgo' }, h.detalle,
          h.accion ? el('span', { class: 'accion' }, `→ ${h.accion}`) : null)),
        v.omitidos ? el('span', { class: 'hallazgo' }, `… y ${v.omitidos} más.`) : null))),
    soloErrores ? null : el('li', { class: 'ok' }, el('span', { class: 'ico' }, ICONO.ok),
      el('span', { class: 'hallazgo' },
        `${reporte.verificaciones.length - relevantes.length} verificaciones sin observaciones · ${reporte.duracion_s.toFixed(2)} s`)));
}

export function cajaError(detalle) {
  return el('dl', { class: 'caja-error', 'data-prueba': 'caja-error' },
    el('dt', {}, 'Causa'), el('dd', {}, detalle.causa || 'Error desconocido'),
    detalle.archivo ? [el('dt', {}, 'Archivo'), el('dd', {}, el('code', {}, detalle.archivo))] : null,
    el('dt', {}, 'Acción'), el('dd', {}, detalle.accion || 'Intenta de nuevo.'));
}

// Paso 3: % varado al final, 3 tramos con mayor probabilidad y radio P90 final; el resto, plegado.
export function renderResultado(contenedor, sim) {
  const r = sim.reg, s = r.resumen, p = r.parametros;
  const radio = s.radio_p90_km[String(sim.H)] ?? sim.series.radio_p90_km[sim.H];
  contenedor.replaceChildren(
    el('div', { class: 'cifra', 'data-prueba': 'varadas' }, el('span', {}, `Varado al final (+${sim.H} h)`),
      el('b', {}, `${fmtNum(s.varadas_pct, 1)} %`)),
    el('h3', {}, 'Arribo más probable por tramo de costa'),
    s.arribos.length
      ? el('ol', { class: 'arribos', 'data-prueba': 'arribos' }, s.arribos.slice(0, 3).map((a) => el('li', {},
        el('span', {}, a.nombre),
        el('span', { class: 'pct' }, fmtPct(a.probabilidad, 0)),
        el('span', { class: `etq etq-${a.etiqueta.toLowerCase().replace(' ', '-')}` }, a.etiqueta))))
      : el('p', { class: 'guia' }, 'Ninguna partícula varó en el horizonte simulado.'),
    el('div', { class: 'cifra' }, el('span', {}, `Radio P90 a +${sim.H} h`),
      radio === null || radio === undefined
        ? el('small', { class: 'nota' }, 'sin partículas a flote')
        : el('b', {}, `${fmtNum(radio, 1)} km`)),
    el('details', { class: 'detalles' },
      el('summary', {}, 'Detalles'),
      el('dl', {},
        el('dt', {}, 'Liberación'), el('dd', {}, fmtCoord(p.lat, p.lon)),
        el('dt', {}, 'Partículas'), el('dd', {}, `${fmtNum(p.particulas)} en ${fmtNum(p.radio_km, 1)} km`),
        el('dt', {}, 'γ · K_h'), el('dd', {}, `${fmtNum(p.gamma, 1)} · ${fmtNum(p.kh_m2s, 1)} m²/s`),
        el('dt', {}, 'Semilla'), el('dd', {}, String(p.semilla)),
        el('dt', {}, 'A flote · fuera'), el('dd', {}, `${fmtNum(s.a_flote_pct, 1)} % · ${fmtNum(s.fuera_pct, 1)} %`),
        el('dt', {}, 'Modelo'), el('dd', {}, r.version_modelo),
        el('dt', {}, 'Simulación'), el('dd', {}, `${r.id}`),
        el('dt', {}, r.datos.archivo), el('dd', {}, `SHA-256 ${r.datos.huella_sha256.slice(0, 16)}…`)),
      el('ul', {}, s.advertencias.map((a) => el('li', {}, a)))),
  );
}

export function renderHistorial(lista, contador, filas, activa, alAbrir) {
  contador.textContent = filas.length ? `(${filas.length})` : '';
  if (!filas.length) {
    lista.replaceChildren(el('li', { class: 'vacio' }, 'Aún no hay simulaciones guardadas.'));
    return;
  }
  lista.replaceChildren(...filas.map((f) => el('li', { class: f.id === activa ? 'activa' : '', 'data-id': f.id },
    el('button', { type: 'button', onclick: () => alAbrir(f.id), title: `Reabrir ${f.id}` },
      el('span', {}, fmtFechaCorta(f.creada_utc)),
      el('span', { class: 'h-punto' }, fmtCoord(f.parametros.lat, f.parametros.lon)),
      el('span', {}, `${fmtNum(f.varadas_pct, 0)} %`)))));
}
