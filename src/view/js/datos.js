// Decodificación del oleaje de SEMAR y de los resultados de simulación.
import { b64a, parseUTC, sumarHoras } from './util.js';

export const A_FLOTE = 0, VARADA = 1, FUERA = 2;
const SIN_DATO = 65535;

export class Campos {
  constructor(j) {
    const m = j.malla;
    Object.assign(this, { lon0: m.lon0, dlon: m.dlon, nx: m.nx, lat0: m.lat0, dlat: m.dlat, ny: m.ny });
    this.resolucion = m.resolucion_grados;
    this.datos = j.datos;
    this.horas = j.horas;                         // +0, +3, …, +120
    this.inicio = parseUTC(j.datos.inicio_utc);
    this.coefStokes = j.modelo.coef_stokes;       // |u_s| = γ · coef · √H
    this.dir = b64a(j.ola_dir, Uint16Array);
    this.alt = b64a(j.ola_altura, Uint16Array);
    this.lonMax = this.lon0 + this.dlon * (this.nx - 1);
    this.latMax = this.lat0 + this.dlat * (this.ny - 1);
  }

  get n() { return this.nx * this.ny; }

  // Bloque de oleaje vigente en la hora h (el último que no la rebasa).
  bloque(h) {
    let k = 0;
    while (k + 1 < this.horas.length && this.horas[k + 1] <= h) k++;
    return k;
  }

  nodoCercano(lon, lat) {
    const j = Math.round((lon - this.lon0) / this.dlon);
    const i = Math.round((lat - this.lat0) / this.dlat);
    if (i < 0 || i >= this.ny || j < 0 || j >= this.nx) return null;
    return { i, j, lon: this.lon0 + j * this.dlon, lat: this.lat0 + i * this.dlat, k: i * this.nx + j };
  }

  // Ola del nodo k en la hora h: altura (m) y dirección DESDE donde viene (°); null sin dato (tierra).
  ola(k, h) {
    const t = this.bloque(h) * this.n + k;
    if (this.alt[t] === SIN_DATO) return null;
    return { altura: this.alt[t] / 100, desde: this.dir[t] / 10 };
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
    this.series = reg.resultados.series;
    this.inicio = parseUTC(reg.datos.inicio_utc);
    this._zona = new Map();
  }

  fecha(h) { return sumarHoras(this.inicio, h); }

  estado(n, h) {
    const hf = this.horaFuera[n];
    if (hf >= 0 && hf <= h) return FUERA;
    const hv = this.horaVarada[n];
    if (hv >= 0 && hv <= h) return VARADA;
    return A_FLOTE;
  }

  // Zona probable P90: el menor conjunto de celdas de 0.16° con el 90 % de las partículas en el dominio.
  zonaP90(h, campos) {
    if (this._zona.has(h)) return this._zona.get(h);
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
    const zona = new Set();
    let acumulado = 0;
    for (const [k, c] of [...conteo.entries()].sort((a, b) => b[1] - a[1])) {
      if (acumulado >= 0.9 * dentro) break;
      zona.add(k);
      acumulado += c;
    }
    if (this._zona.size > 160) this._zona.clear();
    this._zona.set(h, zona);
    return zona;
  }
}
