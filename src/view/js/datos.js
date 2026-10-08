// Decodificación de los campos ambientales y de los resultados de simulación.
import { b64a, b64aBytes, parseUTC, sumarHoras } from './util.js';

export const A_FLOTE = 0, VARADA = 1, FUERA = 2;

export class Campos {
  constructor(j) {
    const m = j.malla;
    Object.assign(this, { lon0: m.lon0, dlon: m.dlon, nx: m.nx, lat0: m.lat0, dlat: m.dlat, ny: m.ny });
    this.resolucion = m.resolucion_grados;
    this.horas = j.horas;
    this.inicio = parseUTC(j.tiempos_utc[0]);
    this.conjunto = j.conjunto;
    this.vu = b64a(j.viento_u, Int16Array);
    this.vv = b64a(j.viento_v, Int16Array);
    this.cu = b64a(j.corriente_u, Int16Array);
    this.cv = b64a(j.corriente_v, Int16Array);
    this.ola = b64a(j.ola_dir, Uint16Array);
    this.mar = b64aBytes(j.mar);
    this.lonMax = this.lon0 + this.dlon * (this.nx - 1);
    this.latMax = this.lat0 + this.dlat * (this.ny - 1);
  }

  hora(h) { return Math.max(0, Math.min(this.horas - 1, Math.floor(h))); }

  // Nodo de malla más cercano (o null fuera de la malla, con media celda de margen).
  nodoCercano(lon, lat) {
    const j = Math.round((lon - this.lon0) / this.dlon);
    const i = Math.round((lat - this.lat0) / this.dlat);
    if (i < 0 || i >= this.ny || j < 0 || j >= this.nx) return null;
    return { i, j, lon: this.lon0 + j * this.dlon, lat: this.lat0 + i * this.dlat, k: i * this.nx + j };
  }

  valoresNodo(nodo, h) {
    const t = this.hora(h) * this.nx * this.ny + nodo.k;
    const ola = this.ola[t];
    return {
      vu: this.vu[t] / 100, vv: this.vv[t] / 100,
      cu: this.cu[nodo.k] / 1000, cv: this.cv[nodo.k] / 1000,
      ola: ola === 65535 ? null : ola / 10,
      mar: this.mar[nodo.k] === 1,
    };
  }

  // Interpolación bilineal de la capa pedida: 'viento', 'corriente' o 'deriva' (u_c + α·u_w).
  muestra(capa, lon, lat, h, alpha) {
    const fj = (lon - this.lon0) / this.dlon;
    const fi = (lat - this.lat0) / this.dlat;
    if (fi < 0 || fj < 0 || fi > this.ny - 1 || fj > this.nx - 1) return null;
    const i0 = Math.min(Math.floor(fi), this.ny - 2), j0 = Math.min(Math.floor(fj), this.nx - 2);
    const wi = fi - i0, wj = fj - j0;
    const k00 = i0 * this.nx + j0, k01 = k00 + 1, k10 = k00 + this.nx, k11 = k10 + 1;
    const w00 = (1 - wi) * (1 - wj), w01 = (1 - wi) * wj, w10 = wi * (1 - wj), w11 = wi * wj;
    let u = 0, v = 0;
    if (capa !== 'corriente') {
      const o = this.hora(h) * this.nx * this.ny;
      const f = capa === 'viento' ? 0.01 : 0.01 * alpha;
      u += f * (w00 * this.vu[o + k00] + w01 * this.vu[o + k01] + w10 * this.vu[o + k10] + w11 * this.vu[o + k11]);
      v += f * (w00 * this.vv[o + k00] + w01 * this.vv[o + k01] + w10 * this.vv[o + k10] + w11 * this.vv[o + k11]);
    }
    if (capa !== 'viento') {
      u += 0.001 * (w00 * this.cu[k00] + w01 * this.cu[k01] + w10 * this.cu[k10] + w11 * this.cu[k11]);
      v += 0.001 * (w00 * this.cv[k00] + w01 * this.cv[k01] + w10 * this.cv[k10] + w11 * this.cv[k11]);
    }
    return [u, v];
  }
}

export class Simulacion {
  constructor(reg) {
    this.reg = reg;
    this.id = reg.id;
    this.H = reg.resultados.horas;
    this.N = reg.resumen.particulas;
    const p = reg.resultados.particulas;
    const c = p.codificacion;
    const qlon = b64a(p.lon, Uint16Array), qlat = b64a(p.lat, Uint16Array);
    this.lon = new Float32Array(qlon.length);
    this.lat = new Float32Array(qlat.length);
    for (let k = 0; k < qlon.length; k++) {
      this.lon[k] = c.lon0 + qlon[k] / c.escala;
      this.lat[k] = c.lat0 + qlat[k] / c.escala;
    }
    this.horaVarada = b64a(reg.resultados.hora_varada, Int16Array);
    this.horaFuera = b64a(reg.resultados.hora_fuera, Int16Array);
    this.zonaVarada = reg.resultados.zona_varada ? b64aBytes(reg.resultados.zona_varada) : null;
    this.zonas = reg.resultados.zonas || [];
    this.series = reg.resultados.series;
    this.inicio = parseUTC(reg.conjunto.inicio_utc);
    this._densidad = new Map();
  }

  fecha(h) { return sumarHoras(this.inicio, h); }

  estado(n, h) {
    const hf = this.horaFuera[n];
    if (hf >= 0 && hf <= h) return FUERA;
    const hv = this.horaVarada[n];
    if (hv >= 0 && hv <= h) return VARADA;
    return A_FLOTE;
  }

  // Conteo por celda de 0.16° (centrada en los nodos de la malla) y zona probable P90.
  densidad(h, campos) {
    const clave = h;
    if (this._densidad.has(clave)) return this._densidad.get(clave);
    const conteo = new Map();
    let dentro = 0;
    const o = h * this.N;
    for (let n = 0; n < this.N; n++) {
      if (this.estado(n, h) === FUERA) continue;
      const nodo = campos.nodoCercano(this.lon[o + n], this.lat[o + n]);
      if (!nodo) continue;
      conteo.set(nodo.k, (conteo.get(nodo.k) || 0) + 1);
      dentro++;
    }
    const orden = [...conteo.entries()].sort((a, b) => b[1] - a[1]);
    const zona = new Set();
    let acumulado = 0;
    for (const [k, c] of orden) {
      if (acumulado >= 0.9 * dentro) break;
      zona.add(k);
      acumulado += c;
    }
    const r = { conteo, zona, dentro, max: orden.length ? orden[0][1] : 0 };
    if (this._densidad.size > 160) this._densidad.clear();
    this._densidad.set(clave, r);
    return r;
  }

  // Partículas varadas por tramo de costa hasta la hora h (acumulado).
  arribosHasta(h) {
    const cuenta = new Map();
    if (!this.zonaVarada) return cuenta;
    for (let n = 0; n < this.N; n++) {
      const hv = this.horaVarada[n];
      if (hv >= 0 && hv <= h && this.zonaVarada[n] !== 255) {
        cuenta.set(this.zonaVarada[n], (cuenta.get(this.zonaVarada[n]) || 0) + 1);
      }
    }
    return cuenta;
  }

  conteoEstados(h) {
    let flote = 0, varadas = 0, fuera = 0;
    for (let n = 0; n < this.N; n++) {
      const e = this.estado(n, h);
      if (e === A_FLOTE) flote++; else if (e === VARADA) varadas++; else fuera++;
    }
    return { flote, varadas, fuera };
  }
}
