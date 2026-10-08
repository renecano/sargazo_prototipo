// Cliente de la API de PMS. Todos los errores llegan como {causa, accion, archivo}.
import { esperar } from './util.js';

function detalleDeError(datos, status) {
  const d = datos && datos.detail;
  if (d && typeof d === 'object' && !Array.isArray(d)) return d;
  if (Array.isArray(d)) {
    // Errores de validación de FastAPI/Pydantic
    const causa = d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join('; ');
    return { causa: `Parámetros fuera de rango — ${causa}`, accion: 'Ajusta los valores marcados e intenta de nuevo.' };
  }
  return { causa: typeof d === 'string' ? d : `El servidor respondió ${status}.`, accion: 'Verifica que el servidor siga en ejecución (python main.py).' };
}

async function pedir(url, opciones = {}) {
  let r;
  try {
    r = await fetch(url, opciones);
  } catch (e) {
    const err = new Error('Sin conexión con el servidor');
    err.detalle = { causa: 'No hay conexión con el servidor de PMS.', accion: 'Levanta la aplicación con  python main.py  y recarga la página.' };
    throw err;
  }
  let datos = null;
  try { datos = await r.json(); } catch { /* respuesta sin cuerpo JSON */ }
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status}`);
    err.status = r.status;
    err.detalle = detalleDeError(datos, r.status);
    throw err;
  }
  return datos;
}

const json = (cuerpo) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });

export const api = {
  salud: () => pedir('/api/salud'),
  conjuntos: () => pedir('/api/conjuntos'),
  validar: (id, forzar = false) => pedir(`/api/conjuntos/${encodeURIComponent(id)}/validar?forzar=${forzar}`, { method: 'POST' }),
  campos: (id) => pedir(`/api/conjuntos/${encodeURIComponent(id)}/campos`),
  costa: () => pedir('/api/costa'),
  simular: (parametros) => pedir('/api/trabajos/simulacion', json(parametros)),
  trabajo: (id) => pedir(`/api/trabajos/${encodeURIComponent(id)}`),
  simulaciones: () => pedir('/api/simulaciones'),
  simulacion: (id) => pedir(`/api/simulaciones/${encodeURIComponent(id)}`),
};

// Consulta un trabajo en segundo plano hasta que termina, informando el progreso.
export async function esperarTrabajo(id, alAvanzar) {
  for (;;) {
    const t = await api.trabajo(id);
    if (alAvanzar) alAvanzar(t);
    if (t.estado !== 'en_curso') return t;
    await esperar(90);
  }
}
