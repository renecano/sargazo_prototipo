// Contenido de los paneles: detalle de validación, resultado (paso 3) e historial.
import {
  el, fmtCoord, fmtCoordGM, fmtDistancia, fmtFechaCorta, fmtFechaQRoo, fmtFechaUTC, fmtNum, fmtPct, fmtRapidez, fmtRumbo,
} from './util.js';

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

// Arribos en orden cronológico: lo que llega primero, arriba.
export function arribosEnOrden(sim) {
  return [...sim.reg.resumen.arribos].sort((a, b) => a.primer_arribo_h - b.primer_arribo_h || b.probabilidad - a.probabilidad);
}

// Paso 3. Resultado principal: la tabla de arribos por tramo de costa. Lo demás, en «Ver detalle».
export function renderResultado(contenedor, sim, { alElegir, alExportarImagen, alImprimir }) {
  const r = sim.reg, s = r.resumen, p = r.parametros;
  const arribos = arribosEnOrden(sim);
  const radio = s.radio_p90_km[String(sim.H)] ?? sim.series.radio_p90_km[sim.H];
  const rapideces = sim.series.rapidez_centroide_ms.filter((v) => v !== null);
  const media = rapideces.length ? rapideces.reduce((a, b) => a + b, 0) / rapideces.length : null;
  const zonas = new Map((r.resultados.zonas || []).map((z) => [z.id, z]));

  const titular = arribos.length
    ? el('p', { class: 'titular', 'data-prueba': 'titular' },
      'Primer arribo: ', el('b', {}, arribos[0].nombre), ', ',
      el('b', {}, fmtFechaQRoo(sim.fecha(arribos[0].primer_arribo_h))), ` (hora ${arribos[0].primer_arribo_h} de ${sim.H}).`)
    : el('p', { class: 'titular', 'data-prueba': 'titular' },
      `Ninguna partícula llegó a la costa en ${sim.H} h: `, el('b', {}, `${fmtNum(s.a_flote_pct, 1)} %`), ' sigue a flote',
      s.fuera_pct ? ` y ${fmtNum(s.fuera_pct, 1)} % salió del dominio.` : '.');

  const tabla = arribos.length ? el('div', { class: 'arribos', role: 'table', 'aria-label': 'Arribos por tramo de costa', 'data-prueba': 'arribos' },
    el('div', { class: 'arribos-cab', role: 'row' },
      el('span', { role: 'columnheader' }, 'Tramo de costa'), el('span', { role: 'columnheader' }, 'Primer arribo'),
      el('span', { role: 'columnheader' }, 'Llega'), el('span', { role: 'columnheader' }, 'Recorre')),
    arribos.map((a) => el('button', {
      type: 'button', class: 'arribo', role: 'row', 'data-zona': a.zona, 'data-hora': a.primer_arribo_h,
      title: `Ir a ${a.nombre} en la hora ${a.primer_arribo_h} · ${fmtFechaUTC(sim.fecha(a.primer_arribo_h))}`,
      onclick: () => alElegir(a),
    },
    el('span', { role: 'cell', class: 'a-nombre' }, a.nombre),
    el('span', { role: 'cell', class: 'a-fecha mono' }, fmtFechaQRoo(sim.fecha(a.primer_arribo_h)), el('small', {}, `hora ${a.primer_arribo_h}`)),
    el('span', { role: 'cell', class: 'a-pct mono' }, fmtPct(a.probabilidad, a.probabilidad < 0.1 ? 1 : 0),
      el('i', { class: 'a-barra', style: `width:${Math.max(3, Math.round(a.probabilidad * 100))}%` })),
    el('span', { role: 'cell', class: 'a-dist mono' }, `${fmtNum(a.distancia_km, 0)} km`, el('small', {}, `${fmtNum(a.distancia_mn, 0)} MN`))))) : null;

  contenedor.replaceChildren(...[
    titular,
    tabla,
    tabla ? el('p', { class: 'nota' }, 'Hora de Quintana Roo (UTC−5). Toque un tramo: el mapa va a ese lugar y a esa hora.') : null,
    el('details', { class: 'detalles', id: 'detalle-resultado' },
      el('summary', {}, 'Ver detalle'),
      el('dl', {},
        el('dt', {}, 'Varado al final'), el('dd', { 'data-prueba': 'varadas' }, `${fmtNum(s.varadas_pct, 1)} % · a flote ${fmtNum(s.a_flote_pct, 1)} % · fuera ${fmtNum(s.fuera_pct, 1)} %`),
        el('dt', {}, 'Radio P90'), el('dd', {}, radio === null || radio === undefined ? 'sin partículas a flote' : `${fmtDistancia(radio)} a la hora ${sim.H}`),
        el('dt', {}, 'Trayectoria central'), el('dd', {}, `${fmtDistancia(s.distancia_centroide_km)} · rumbo neto ${fmtRumbo(s.rumbo_neto_grados)}`),
        el('dt', {}, 'Rapidez media'), el('dd', {}, media === null ? '—' : fmtRapidez(media)),
        el('dt', {}, 'Liberación'), el('dd', {}, fmtCoord(p.lat, p.lon), el('br'), fmtCoordGM(p.lat, p.lon)),
        el('dt', {}, 'Partículas'), el('dd', {}, `${fmtNum(p.particulas)} en un radio de ${fmtDistancia(p.radio_km)}`),
        el('dt', {}, 'γ · K_h'), el('dd', {}, `${fmtNum(p.gamma, 1)} · ${fmtNum(p.kh_m2s, 1)} m²/s · semilla ${p.semilla}`),
        el('dt', {}, 'Modelo'), el('dd', {}, r.version_modelo),
        el('dt', {}, 'Simulación'), el('dd', {}, r.id),
        el('dt', {}, r.datos.archivo), el('dd', {}, `SHA-256 ${r.datos.huella_sha256.slice(0, 16)}…`)),
      arribos.length ? el('table', { class: 'tabla-detalle' },
        el('thead', {}, el('tr', {}, el('th', {}, 'Tramo'), el('th', {}, 'Primer arribo (UTC)'), el('th', {}, 'Mediano'), el('th', {}, 'Partículas'))),
        el('tbody', {}, arribos.map((a) => el('tr', { title: zonas.get(a.zona)?.limites ? `Límites del tramo: ${zonas.get(a.zona).limites}` : '' },
          el('td', {}, a.nombre), el('td', {}, fmtFechaUTC(sim.fecha(a.primer_arribo_h))),
          el('td', {}, `hora ${a.arribo_mediano_h}`), el('td', {}, `${fmtNum(a.particulas)} · ${a.etiqueta}`))))) : null,
      el('ul', {}, s.advertencias.map((a) => el('li', {}, a)))),
    el('div', { class: 'exportar' },
      el('button', { type: 'button', class: 'boton-linea', id: 'btn-exportar-imagen', onclick: alExportarImagen }, 'Guardar imagen del mapa'),
      el('button', { type: 'button', class: 'boton-linea', id: 'btn-imprimir', onclick: alImprimir }, 'Resumen de una página')),
  ].filter(Boolean));
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
      el('span', { class: 'h-punto' }, f.arribo_principal || fmtCoord(f.parametros.lat, f.parametros.lon)),
      el('span', {}, `${fmtNum(f.varadas_pct, 0)} %`)))));
}
