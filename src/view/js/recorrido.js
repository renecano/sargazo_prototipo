// Recorrido guiado: oscurece la pantalla, ilumina el elemento del que habla y muestra una
// tarjeta con el texto. Algunos pasos esperan una acción real (clic en el mar, simular).
import { el } from './util.js';

const CLAVE_VISTO = 'pms.recorrido.visto.v3';
const CLAVE_VOZ = 'pms.recorrido.voz';
const MARGEN = 8;          // aire alrededor del elemento iluminado
const SEPARACION = 14;     // distancia entre el foco y la tarjeta

function leer(clave) { try { return localStorage.getItem(clave); } catch { return null; } }
function guardar(clave, valor) { try { localStorage.setItem(clave, valor); } catch { /* sin almacenamiento */ } }

export function recorridoVisto() { return leer(CLAVE_VISTO) === '1'; }

export class Recorrido {
  constructor(raiz, pasos) {
    this.raiz = raiz;
    this.pasos = pasos;
    this.k = -1;
    this.activo = false;
    this.voz = leer(CLAVE_VOZ) === '1';
    this._sondeo = null;
    this._alRedimensionar = () => this._posicionar();
  }

  iniciar() {
    if (this.activo) return;
    this.activo = true;
    window.pmsRecorridoActivo = true;
    this.bloqueos = ['arriba', 'abajo', 'izquierda', 'derecha'].map((lado) => el('div', { class: 'rec-bloqueo', 'data-lado': lado }));
    this.foco = el('div', { class: 'rec-foco' });
    this.tarjeta = el('section', { class: 'rec-tarjeta', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Recorrido guiado', 'data-prueba': 'recorrido' });
    this.raiz.replaceChildren(...this.bloqueos, this.foco, this.tarjeta);
    window.addEventListener('resize', this._alRedimensionar);
    this._teclas = (e) => this._teclado(e);
    document.addEventListener('keydown', this._teclas, true);
    this.ir(0);
  }

  async ir(k) {
    if (k < 0 || k >= this.pasos.length) return;
    const anterior = this.pasos[this.k];
    if (anterior && anterior.alSalir) anterior.alSalir();
    this.k = k;
    const paso = this.pasos[k];
    this._inicioPaso = performance.now();
    if (paso.alEntrar) await paso.alEntrar();
    this._render();
    this._posicionar();
    this._hablar();
    clearInterval(this._sondeo);
    // Sigue al elemento si el diseño cambia y revisa si ya se cumplió la acción esperada.
    this._sondeo = setInterval(() => {
      this._posicionar();
      if (paso.esperar) this._actualizarEspera();
    }, 200);
  }

  siguiente() {
    const paso = this.pasos[this.k];
    if (paso.esperar && !paso.esperar.listo(this._inicioPaso)) return;
    if (this.k === this.pasos.length - 1) this.cerrar('fin');
    else this.ir(this.k + 1);
  }

  atras() { if (this.k > 0) this.ir(this.k - 1); }

  cerrar(motivo = 'saltar') {
    if (!this.activo) return;
    const paso = this.pasos[this.k];
    if (paso && paso.alSalir) paso.alSalir();
    this.activo = false;
    window.pmsRecorridoActivo = false;
    clearInterval(this._sondeo);
    window.removeEventListener('resize', this._alRedimensionar);
    document.removeEventListener('keydown', this._teclas, true);
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    this.raiz.replaceChildren();
    guardar(CLAVE_VISTO, '1');
    this.motivoCierre = motivo;
  }

  _teclado(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.cerrar('saltar'); return; }
    const enCampo = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName);
    if (enCampo) return;
    if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); this.siguiente(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); this.atras(); }
    else if (e.code === 'Space') { e.preventDefault(); e.stopPropagation(); }
  }

  _render() {
    const paso = this.pasos[this.k];
    const n = this.pasos.length;
    const ultimo = this.k === n - 1;
    this.tarjeta.dataset.paso = String(this.k + 1);
    this.tarjeta.replaceChildren(...[
      el('div', { class: 'rec-cab' },
        el('span', { 'data-prueba': 'rec-contador' }, `Paso ${this.k + 1} de ${n}`),
        el('button', {
          type: 'button', class: 'rec-voz', id: 'rec-voz', 'aria-pressed': String(this.voz),
          title: 'Narración en voz (español de México)', onclick: () => this._alternarVoz(),
          hidden: !window.speechSynthesis,
        }, this.voz ? 'Voz: sí' : 'Voz: no')),
      el('h2', {}, paso.titulo),
      ...paso.texto.map((t) => el('p', {}, t)),
      paso.esperar ? el('div', { class: 'rec-espera', id: 'rec-espera' }, paso.esperar.texto) : null,
      el('div', { class: 'rec-botones' },
        el('button', { type: 'button', class: 'enlace', id: 'rec-saltar', onclick: () => this.cerrar('saltar'), hidden: ultimo }, 'Saltar recorrido'),
        el('span', { class: 'espacio' }),
        el('button', { type: 'button', class: 'boton-linea', id: 'rec-atras', onclick: () => this.atras(), disabled: this.k === 0 }, 'Atrás'),
        el('button', { type: 'button', class: 'boton-tinta', id: 'rec-siguiente', onclick: () => this.siguiente() }, ultimo ? 'Terminar' : 'Siguiente')),
      el('div', { class: 'rec-barra' }, el('i', { style: `width:${((this.k + 1) / n) * 100}%` })),
    ].filter(Boolean));
    if (paso.esperar) this._actualizarEspera();
    this.tarjeta.querySelector('#rec-siguiente').focus({ preventScroll: true });
  }

  _actualizarEspera() {
    const paso = this.pasos[this.k];
    const listo = paso.esperar.listo(this._inicioPaso);
    const caja = this.tarjeta.querySelector('#rec-espera');
    const boton = this.tarjeta.querySelector('#rec-siguiente');
    if (caja) {
      caja.classList.toggle('hecho', listo);
      caja.textContent = listo ? (paso.esperar.hecho ? paso.esperar.hecho() : 'Listo.') : paso.esperar.texto;
    }
    if (boton) boton.disabled = !listo;
  }

  _rectObjetivo() {
    const paso = this.pasos[this.k];
    const objetivo = paso.objetivo ? paso.objetivo() : null;
    if (!objetivo) return null;
    const r = objetivo instanceof Element ? objetivo.getBoundingClientRect() : objetivo;
    if (!r || r.width === 0 || r.height === 0) return null;
    return { x: r.left - MARGEN, y: r.top - MARGEN, w: r.width + 2 * MARGEN, h: r.height + 2 * MARGEN };
  }

  _posicionar() {
    if (!this.activo) return;
    const W = window.innerWidth, H = window.innerHeight;
    const r = this._rectObjetivo();
    const [arriba, abajo, izq, der] = this.bloqueos;
    const fijar = (n, x, y, w, h) => Object.assign(n.style, { left: `${x}px`, top: `${y}px`, width: `${Math.max(0, w)}px`, height: `${Math.max(0, h)}px` });
    if (!r) {
      fijar(arriba, 0, 0, W, H);
      [abajo, izq, der].forEach((n) => fijar(n, 0, 0, 0, 0));
      this.foco.style.display = 'none';
    } else {
      fijar(arriba, 0, 0, W, r.y);
      fijar(abajo, 0, r.y + r.h, W, H - r.y - r.h);
      fijar(izq, 0, r.y, r.x, r.h);
      fijar(der, r.x + r.w, r.y, W - r.x - r.w, r.h);
      this.foco.style.display = 'block';
      fijar(this.foco, r.x, r.y, r.w, r.h);
    }
    // Tarjeta: a la derecha, izquierda, abajo o arriba del foco; si no cabe, centrada.
    const t = this.tarjeta.getBoundingClientRect();
    const tw = t.width || 380, th = t.height || 220;
    let x = (W - tw) / 2, y = (H - th) / 2;
    if (r) {
      // A los lados basta con que quepa en horizontal (luego se acota en vertical);
      // arriba o abajo, con que quepa en vertical.
      const opciones = [
        { x: r.x + r.w + SEPARACION, y: r.y, ok: (cx) => cx + tw <= W - 12 },
        { x: r.x - SEPARACION - tw, y: r.y, ok: (cx) => cx >= 12 },
        { x: r.x, y: r.y + r.h + SEPARACION, ok: (_cx, cy) => cy + th <= H - 12 },
        { x: r.x, y: r.y - SEPARACION - th, ok: (_cx, cy) => cy >= 12 },
      ];
      const elegida = opciones.find((o) => o.ok(o.x, o.y));
      if (elegida) { ({ x, y } = elegida); } else { x = W - tw - 24; y = H - th - 80; }
    }
    x = Math.min(Math.max(12, x), W - tw - 12);
    y = Math.min(Math.max(12, y), H - th - 12);
    Object.assign(this.tarjeta.style, { left: `${x}px`, top: `${y}px` });
  }

  _alternarVoz() {
    this.voz = !this.voz;
    guardar(CLAVE_VOZ, this.voz ? '1' : '0');
    const b = this.tarjeta.querySelector('#rec-voz');
    b.setAttribute('aria-pressed', String(this.voz));
    b.textContent = this.voz ? 'Voz: sí' : 'Voz: no';
    if (this.voz) this._hablar(); else if (window.speechSynthesis) window.speechSynthesis.cancel();
  }

  _hablar() {
    const s = window.speechSynthesis;
    if (!s) return;
    s.cancel();
    if (!this.voz) return;
    const paso = this.pasos[this.k];
    const u = new SpeechSynthesisUtterance(`${paso.titulo}. ${paso.texto.join(' ')}`.replace(/[«»]/g, ''));
    const voces = s.getVoices();
    u.voice = voces.find((v) => v.lang === 'es-MX') || voces.find((v) => v.lang && v.lang.startsWith('es')) || null;
    u.lang = 'es-MX';
    u.rate = 1;
    s.speak(u);
  }
}
