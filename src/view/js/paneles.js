// Render de paneles: detalle de validación, resultado, historial.
import { el, fmtCoord, fmtFechaCorta, fmtNum, fmtPct } from './util.js';

const ICONO = { ok: '✓', advertencia: '!', error: '✕' };

// Solo las verificaciones con algo que decir (errores o advertencias), con su acción.
export function detalleValidacion(reporte) {
  const relevantes = reporte.verificaciones.filter((v) => v.estado !== 'ok');
  return el('ul', { class: 'checks', 'data-prueba': 'verificaciones' },
    relevantes.map((v) => el('li', { class: v.estado },
      el('span', { class: 'ico', 'aria-label': v.estado }, ICONO[v.estado]),
      el('span', {},
        el('span', { class: 'nombre' }, v.nombre),
        v.hallazgos.slice(0, 4).map((h) => el('span', { class: 'hallazgo' },
          h.archivo ? el('code', {}, h.archivo) : null, h.archivo ? ' ' : null, h.detalle,
          h.accion ? el('span', { class: 'accion' }, `→ ${h.accion}`) : null)),
        v.omitidos ? el('span', { class: 'hallazgo' }, `… y ${v.omitidos} más.`) : null))),
    el('li', { class: 'ok resumen-ok' }, el('span', { class: 'ico' }, ICONO.ok),
      el('span', {}, `${reporte.verificaciones.length - relevantes.length} verificaciones sin observaciones · ${reporte.duracion_s.toFixed(2)} s`)));
}

export function cajaError(detalle) {
  return el('dl', { class: 'caja-error', 'data-prueba': 'caja-error' },
    el('dt', {}, 'Causa'), el('dd', {}, detalle.causa || 'Error desconocido'),
    detalle.archivo ? [el('dt', {}, 'Archivo'), el('dd', {}, el('code', {}, detalle.archivo))] : null,
    el('dt', {}, 'Acción'), el('dd', {}, detalle.accion || 'Intenta de nuevo.'));
}

// Resultado: % varadas al final, 3 tramos con mayor probabilidad y radio P90 final.
export function renderResultado(contenedor, sim, alCerrar) {
  const r = sim.reg, s = r.resumen, p = r.parametros;
  const radioFinal = s.radio_p90_km[String(sim.H)] ?? sim.series.radio_p90_km[sim.H];
  contenedor.replaceChildren(
    el('div', { class: 'res-cab' },
      el('h2', {}, `Resultado a +${sim.H} h`),
      el('button', { type: 'button', class: 'cerrar', title: 'Ocultar', 'aria-label': 'Ocultar resultado', onclick: alCerrar }, '✕')),
    el('div', { class: 'res-cifra', 'data-prueba': 'varadas' },
      el('span', {}, 'Varadas al final'), el('b', {}, `${fmtNum(s.varadas_pct, 1)} %`)),
    el('h3', {}, 'Arribo más probable'),
    s.arribos.length
      ? el('ol', { class: 'arribos', 'data-prueba': 'arribos' }, s.arribos.slice(0, 3).map((a) => el('li', {},
        el('span', { class: 'nombre' }, a.nombre),
        el('span', { class: 'pct' }, fmtPct(a.probabilidad, 0)),
        el('span', { class: `etq etq-${a.etiqueta.toLowerCase().replace(' ', '-')}` }, a.etiqueta))))
      : el('p', { class: 'vacio' }, 'Ninguna partícula varó en el horizonte simulado.'),
    el('div', { class: 'res-cifra' },
      el('span', {}, `Radio P90 a +${sim.H} h`),
      el('b', {}, radioFinal === null || radioFinal === undefined ? '—' : `${fmtNum(radioFinal, 1)} km`)),
    el('details', { class: 'res-detalles' },
      el('summary', {}, 'Detalles'),
      el('dl', {},
        el('dt', {}, 'Liberación'), el('dd', {}, fmtCoord(p.lat, p.lon)),
        el('dt', {}, 'Partículas · radio'), el('dd', {}, `${fmtNum(p.particulas)} · ${fmtNum(p.radio_km, 1)} km`),
        el('dt', {}, 'α · K_h'), el('dd', {}, `${fmtNum(p.alpha_pct, 1)} % · ${fmtNum(p.kh_m2s, 1)} m²/s`),
        el('dt', {}, 'Semilla'), el('dd', {}, String(p.semilla)),
        el('dt', {}, 'Fuera del dominio'), el('dd', {}, `${fmtNum(s.fuera_pct, 1)} %`),
        el('dt', {}, 'Modelo'), el('dd', {}, r.version_modelo),
        el('dt', {}, 'Simulación'), el('dd', {}, `${r.id} · ${fmtFechaCorta(r.creada_utc)}`),
        r.datos.archivos.map((a) => [el('dt', {}, a.nombre), el('dd', { class: 'huella' }, `SHA-256 ${a.huella_sha256.slice(0, 16)}…`)])),
      el('ul', { class: 'advertencias' }, s.advertencias.map((a) => el('li', {}, a)))),
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
      el('span', { class: 'h-fecha' }, fmtFechaCorta(f.creada_utc)),
      el('span', { class: 'h-punto' }, fmtCoord(f.parametros.lat, f.parametros.lon)),
      el('span', { class: 'h-varadas' }, `${fmtNum(f.varadas_pct, 0)} % var.`)))));
}
