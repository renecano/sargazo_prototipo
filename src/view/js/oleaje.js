// Oleaje animado: trazos cortos que fluyen HACIA donde viaja la ola.
//
// - Largo del trazo = altura × PX_POR_METRO (la misma escala que la flecha de referencia «1 m»)
//   y rapidez en pantalla proporcional a la altura: donde la ola es más alta, el trazo es más
//   largo y corre más.
// - El campo se toma en la hora de la línea de tiempo, interpolado entre bloques como en el
//   modelo: si el archivo cambia entre bloques, el flujo cambia; si los bloques son idénticos,
//   sigue fluyendo igual (la interfaz lo dice en la leyenda).
// - Ligero: un trazo por cada ~46 × 46 px de mar, a 30 cuadros por segundo como máximo; se
//   detiene con la pestaña oculta, con el interruptor o con «prefers-reduced-motion».
import { paleta, PX_POR_METRO, trazarFlecha } from './capas.js';

const SEPARACION_PX = 46;
const MAX_TRAZOS = 900;
const VIDA_S = 2.6;
const PX_POR_S_POR_METRO = 20;       // rapidez en pantalla por metro de altura de ola
const INTERVALO_MS = 1000 / 30;

export class OleajeAnimado {
  constructor(capa, est) {
    this.capa = capa;
    this.est = est;
    this.trazos = [];
    this._ultimo = 0;
    this._raf = null;
    this._o = new Float64Array(3);
    this._tic = (t) => this._cuadro(t);
    this.cuadros = 0;
  }

  get activo() { return this._raf !== null; }

  // Reparte los trazos en una rejilla con desorden, para que cubran la vista de forma pareja.
  sembrar() {
    const c = this.capa;
    const paso = Math.max(SEPARACION_PX, Math.sqrt((c.ancho * c.alto) / MAX_TRAZOS));
    this.trazos = [];
    for (let y = paso / 2; y < c.alto; y += paso) {
      for (let x = paso / 2; x < c.ancho; x += paso) {
        this.trazos.push({ cx: x, cy: y, x: 0, y: 0, edad: Math.random() * VIDA_S, paso, vivo: false });
      }
    }
    for (const t of this.trazos) this._renacer(t, false);
  }

  _renacer(t, reiniciarEdad = true) {
    t.x = t.cx + (Math.random() - 0.5) * t.paso;
    t.y = t.cy + (Math.random() - 0.5) * t.paso;
    if (reiniciarEdad) t.edad = 0;
    t.vivo = true;
  }

  iniciar() {
    if (this._raf !== null) return;
    this.sembrar();
    this._ultimo = 0;
    this._raf = requestAnimationFrame(this._tic);
  }

  detener() {
    if (this._raf !== null) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  _cuadro(ahora) {
    this._raf = requestAnimationFrame(this._tic);
    if (document.hidden) { this._ultimo = 0; return; }
    if (!this._ultimo) { this._ultimo = ahora; return; }
    const dt = ahora - this._ultimo;
    if (dt < INTERVALO_MS) return;
    this._ultimo = ahora;
    this.avanzar(Math.min(dt, 100) / 1000);
  }

  // Avanza `dt` segundos y redibuja. Se puede llamar a mano (pruebas y exportación).
  avanzar(dt) {
    const { capa: c, est } = this;
    const { campos, costa, hora } = est;
    const ctx = c.ctx;
    ctx.clearRect(0, 0, c.ancho, c.alto);
    est.flechas = [];
    if (!campos || !est.ver.oleaje) return;
    const o = this._o;
    const tinta = paleta(est).ola;
    ctx.strokeStyle = tinta;
    ctx.lineWidth = 1.25;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    // Tres niveles de opacidad por cuadro (aparecer, pleno, desvanecer) para dibujar por lotes.
    const lotes = [[], [], []];
    for (const t of this.trazos) {
      t.edad += dt;
      if (t.edad >= VIDA_S || !t.vivo) this._renacer(t);
      const lon = c.lon(t.x), lat = c.lat(t.y);
      // Solo dentro de la malla del archivo y sobre el mar: fuera no hay dato que mostrar.
      if (lon < campos.lon0 || lon > campos.lonMax || lat < campos.lat0 || lat > campos.latMax
        || !campos.muestrear(lon, lat, hora, o) || o[0] < 0.02 || (costa && costa.enTierra(lon, lat))) { t.vivo = false; continue; }
      const ux = o[1], uy = -o[2];                       // en pantalla el norte es −y
      t.x += ux * o[0] * PX_POR_S_POR_METRO * dt;
      t.y += uy * o[0] * PX_POR_S_POR_METRO * dt;
      const fase = Math.sin((Math.PI * t.edad) / VIDA_S);
      lotes[fase > 0.75 ? 2 : fase > 0.35 ? 1 : 0].push(t.x, t.y, ux, uy, o[0] * PX_POR_METRO);
      if (est.flechas.length < 60) est.flechas.push({ lon, lat, altura: o[0], largo: o[0] * PX_POR_METRO });
    }
    const alfas = [0.28, 0.62, 0.95];
    for (let k = 0; k < 3; k++) {
      const l = lotes[k];
      if (!l.length) continue;
      ctx.globalAlpha = alfas[k];
      ctx.beginPath();
      for (let i = 0; i < l.length; i += 5) trazarFlecha(ctx, l[i], l[i + 1], l[i + 2], l[i + 3], l[i + 4]);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    this.cuadros++;
  }
}
