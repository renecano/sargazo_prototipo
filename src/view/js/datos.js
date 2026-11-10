// Datos de la interfaz: oleaje de SEMAR, costa del modelo y resultados de simulación.
//
// Aquí viven las mismas reglas que usa el modelo en Python, para que lo que se ve sea lo que
// se calculó:
//   - Campos.muestrear  ↔ src/model/campos.py   (bilineal con seno/coseno, lineal entre bloques)
//   - Costa.enTierra    ↔ src/model/costa.py    (la misma máscara de 0.001°, bit a bit)
//   - Simulacion.pos    interpola en línea recta entre horas guardadas: es el segmento que
//                       el integrador revisó contra la costa.
import { b64a, parseUTC, sumarHoras } from './util.js';

export const A_FLOTE = 0, VARADA = 1, FUERA = 2;
const SIN_DATO = 65535;
const R_MINIMA = 1e-6;
const RAD = Math.PI / 180;
const M_POR_GRADO = (Math.PI * 6371000) / 180;

export class Campos {
  constructor(j) {
    const m = j.malla;
    Object.assign(this, { lon0: m.lon0, dlon: m.dlon, nx: m.nx, lat0: m.lat0, dlat: m.dlat, ny: m.ny });
    this.resolucion = m.resolucion_grados;
    this.datos = j.datos;
    this.identicos = !!j.datos.bloques_identicos;
    this.horas = j.horas;                                  // +0, +3, …, +120
    this.horasRel = j.horas.map((h) => h - j.horas[0]);    // el modelo mide t desde el primer bloque
    this.inicio = parseUTC(j.datos.inicio_utc);
    this.coefStokes = j.modelo.coef_stokes;                // |u_s| = γ · coef · √H
    const dir = b64a(j.ola_dir, Uint16Array), alt = b64a(j.ola_altura, Uint16Array);
    this.extrapolado = b64a(j.extrapolado, Uint8Array);
    const n = dir.length;
    this.alt = new Float32Array(n);
    this.sen = new Float32Array(n);
    this.cos = new Float32Array(n);
    for (let k = 0; k < n; k++) {
      if (alt[k] === SIN_DATO) { this.alt[k] = NaN; continue; }
      this.alt[k] = alt[k] / 100;
      this.sen[k] = Math.sin((dir[k] / 10) * RAD);
      this.cos[k] = Math.cos((dir[k] / 10) * RAD);
    }
    this.lonMax = this.lon0 + this.dlon * (this.nx - 1);
    this.latMax = this.lat0 + this.dlat * (this.ny - 1);
    this._a = new Float64Array(3);
    this._b = new Float64Array(3);
  }

  get n() { return this.nx * this.ny; }

  // Bloque de oleaje vigente en la hora h (el último que no la rebasa).
  bloque(h) {
    let k = 0;
    while (k + 1 < this.horasRel.length && this.horasRel[k + 1] <= h) k++;
    return k;
  }

  // Interpolación bilineal de (altura, seno, coseno) del bloque k en índices fraccionarios.
  // Los nodos sin dato se descartan y los pesos se renormalizan. Devuelve false sin datos.
  _bilineal(k, fi, fj, out) {
    const { nx, ny } = this;
    const i0 = Math.max(0, Math.min(ny - 2, Math.floor(fi)));
    const j0 = Math.max(0, Math.min(nx - 2, Math.floor(fj)));
    const wi = Math.max(0, Math.min(1, fi - i0));
    const wj = Math.max(0, Math.min(1, fj - j0));
    const base = k * nx * ny + i0 * nx + j0;
    let h = 0, s = 0, c = 0, p = 0;
    for (let e = 0; e < 4; e++) {
      const t = base + (e & 1) + (e & 2 ? nx : 0);
      const a = this.alt[t];
      if (a !== a) continue;                     // NaN: nodo sin dato
      const w = (e & 1 ? wj : 1 - wj) * (e & 2 ? wi : 1 - wi);
      p += w; h += w * a; s += w * this.sen[t]; c += w * this.cos[t];
    }
    if (p <= 1e-12) return false;
    out[0] = h / p; out[1] = s / p; out[2] = c / p;
    return true;
  }

  // Ola interpolada en (lon, lat) y la hora h (fraccionaria), como en el modelo. Escribe en
  // `out` [altura m, u, v] donde (u, v) es el vector unitario HACIA donde viaja la ola
  // (este, norte). Devuelve false si no hay ola o si las direcciones se cancelan.
  muestrear(lon, lat, h, out) {
    const fi = (lat - this.lat0) / this.dlat, fj = (lon - this.lon0) / this.dlon;
    const hr = this.horasRel, nb = hr.length;
    let k0 = 0, k1 = 0, w = 0;
    if (nb > 1 && h > hr[0]) {
      if (h >= hr[nb - 1]) { k0 = k1 = nb - 1; } else {
        k1 = 1;
        while (hr[k1] < h) k1++;
        k0 = k1 - 1;
        w = (h - hr[k0]) / (hr[k1] - hr[k0]);
      }
    }
    const a = this._a, b = this._b;
    const hayA = this._bilineal(k0, fi, fj, a);
    let H, s, c;
    if (w > 0) {
      const hayB = this._bilineal(k1, fi, fj, b);
      if (hayA && hayB) { H = (1 - w) * a[0] + w * b[0]; s = (1 - w) * a[1] + w * b[1]; c = (1 - w) * a[2] + w * b[2]; }
      else if (hayA) { [H, s, c] = a; } else if (hayB) { [H, s, c] = b; } else return false;
    } else {
      if (!hayA) return false;
      H = a[0]; s = a[1]; c = a[2];
    }
    const r = Math.hypot(s, c);
    if (!(r > R_MINIMA)) return false;
    out[0] = H; out[1] = -s / r; out[2] = -c / r;
    return true;
  }

  // Ola en un punto, lista para mostrarse: altura, dirección «desde», rapidez de deriva (γ = 1).
  olaEn(lon, lat, h) {
    const o = new Float64Array(3);
    if (!this.muestrear(lon, lat, h, o)) return null;
    const desde = ((Math.atan2(-o[1], -o[2]) / RAD) + 360) % 360;
    const i = Math.round((lat - this.lat0) / this.dlat), j = Math.round((lon - this.lon0) / this.dlon);
    const dentro = i >= 0 && i < this.ny && j >= 0 && j < this.nx;
    return {
      altura: o[0], desde, hacia: (desde + 180) % 360, deriva: this.coefStokes * Math.sqrt(Math.max(o[0], 0)),
      extendida: dentro && this.extrapolado[this.bloque(h) * this.n + i * this.nx + j] === 1,
    };
  }

  // ¿El nodo (i, j) trae dato en el archivo (no extendido) en el bloque vigente?
  nodoConDato(i, j, h) {
    const t = this.bloque(h) * this.n + i * this.nx + j;
    return this.alt[t] === this.alt[t] && this.extrapolado[t] === 0;
  }
}

// Máscara de tierra del modelo: 1 bit por celda de 0.001°, filas de sur a norte.
export class Costa {
  constructor(info, tierra, contexto) {
    this.info = info;
    this.zonas = info.zonas;
    this.t = Costa._malla(info.malla, tierra);
    this.c = contexto ? Costa._malla(info.contexto, contexto) : null;
  }

  static _malla(m, bits) {
    return { lon0: m.lon0, lat0: m.lat0, paso: m.paso, nx: m.nx, ny: m.ny, ancho: m.nx >> 3, bits };
  }

  static _bit(m, lon, lat) {
    // Se divide entre el paso, como en Python: multiplicar por 1/paso cambia el resultado
    // justo en los bordes de celda, que es donde quedan las partículas varadas.
    const j = Math.floor((lon - m.lon0) / m.paso), i = Math.floor((lat - m.lat0) / m.paso);
    if (i < 0 || j < 0 || i >= m.ny || j >= m.nx) return -1;
    return (m.bits[i * m.ancho + (j >> 3)] >> (7 - (j & 7))) & 1;
  }

  // Tierra según el modelo (fuera de la máscara todo es mar, igual que en Python).
  enTierra(lon, lat) { return Costa._bit(this.t, lon, lat) === 1; }

  // Para dibujar la carta: 0 mar, 1 tierra del modelo, 2 tierra de contexto (fuera de la máscara).
  clase(lon, lat) {
    const b = Costa._bit(this.t, lon, lat);
    if (b >= 0) return b;
    return this.c && Costa._bit(this.c, lon, lat) === 1 ? 2 : 0;
  }
}

export const CELDA_DENSIDAD = 0.04;                       // grados: 1/4 de la malla de oleaje (~4.4 × 4.2 km)
export const CLASES_DENSIDAD = [0.2, 1, 5, 20];           // % del sargazo liberado por celda (límite inferior)
export const HORAS_ESTELA = 6;
export const CLASES_RAPIDEZ_KN = [0.2, 0.4];              // lenta < 0.2 kn ≤ media < 0.4 kn ≤ rápida

export class Simulacion {
  constructor(reg) {
    this.reg = reg;
    this.id = reg.id;
    this.H = reg.resultados.horas;
    this.N = reg.resumen.particulas;
    const p = reg.resultados.particulas;
    const c = p.codificacion;
    const qlon = b64a(p.lon, Uint16Array), qlat = b64a(p.lat, Uint16Array);
    // Doble precisión y la misma cuenta que el servidor (lon0 + valor / escala): una partícula
    // varada queda justo en el borde de una celda de costa y medio metro de redondeo de un
    // Float32 la pasaría a tierra.
    this.lon = new Float64Array(qlon.length);
    this.lat = new Float64Array(qlat.length);
    for (let k = 0; k < qlon.length; k++) {
      this.lon[k] = c.lon0 + qlon[k] / c.escala;
      this.lat[k] = c.lat0 + qlat[k] / c.escala;
    }
    this.horaVarada = b64a(reg.resultados.hora_varada, Int16Array);
    this.horaFuera = b64a(reg.resultados.hora_fuera, Int16Array);
    this.series = reg.resultados.series;
    this.inicio = parseUTC(reg.datos.inicio_utc);
    this.lon0 = c.lon0;
    this.lat0 = c.lat0;
    this._densidad = new Map();
  }

  fecha(h) { return sumarHoras(this.inicio, h); }

  // Estado en la hora t (puede ser fraccionaria): una partícula vara o sale al llegar a su hora.
  estado(n, t) {
    const hf = this.horaFuera[n];
    if (hf >= 0 && hf <= t) return FUERA;
    const hv = this.horaVarada[n];
    if (hv >= 0 && hv <= t) return VARADA;
    return A_FLOTE;
  }

  // Posición en la hora t, en línea recta entre las dos horas guardadas que la rodean.
  pos(n, t, out) {
    const h = Math.max(0, Math.min(this.H, t));
    const h0 = Math.min(this.H - 1, Math.floor(h)), f = h - h0;
    const a = h0 * this.N + n, b = a + this.N;
    out[0] = this.lon[a] + f * (this.lon[b] - this.lon[a]);
    out[1] = this.lat[a] + f * (this.lat[b] - this.lat[a]);
    return out;
  }

  // Posición que se dibuja. Las horas guardadas están redondeadas a 0.0002° (~22 m) y la recta
  // entre dos de ellas puede rozar una celda de tierra que el segmento exacto del modelo no
  // tocó. En ese caso la partícula se dibuja en el último punto de esa recta que sigue en el
  // mar (la hora guardada anterior siempre lo está): nada se dibuja sobre tierra.
  posVisible(n, t, out, costa) {
    this.pos(n, t, out);
    if (!costa || !costa.enTierra(out[0], out[1])) return out;
    const h0 = Math.min(this.H - 1, Math.floor(Math.max(0, Math.min(this.H, t))));
    const a = h0 * this.N + n;
    const lon = this.lon[a], lat = this.lat[a], dx = out[0] - lon, dy = out[1] - lat;
    for (const f of [0.75, 0.5, 0.25, 0]) {
      out[0] = lon + f * dx; out[1] = lat + f * dy;
      if (!costa.enTierra(out[0], out[1])) break;
    }
    return out;
  }

  // Velocidad media (m/s) de la partícula en la hora que contiene a t: [u este, v norte].
  velocidad(n, t, out) {
    const h0 = Math.max(0, Math.min(this.H - 1, Math.floor(t)));
    const a = h0 * this.N + n, b = a + this.N;
    const lat = this.lat[a];
    out[0] = ((this.lon[b] - this.lon[a]) * Math.cos(lat * RAD) * M_POR_GRADO) / 3600;
    out[1] = ((this.lat[b] - this.lat[a]) * M_POR_GRADO) / 3600;
    return out;
  }

  // Rapidez (m/s) y rumbo (°) del conglomerado: desplazamiento del centroide en esa hora.
  rapidezConglomerado(t) {
    const h = Math.max(0, Math.min(this.H, Math.floor(t)));
    const ms = this.series.rapidez_centroide_ms[h];
    return ms === null || ms === undefined ? null : { ms, rumbo: this.series.rumbo_centroide_grados[h] };
  }

  // Densidad en la hora entera h: % de las N partículas en cada celda de 0.04° (sin contar las
  // que salieron del dominio) y el conjunto P90 (menor grupo de celdas con el 90 % de ellas).
  densidad(h) {
    h = Math.max(0, Math.min(this.H, Math.round(h)));
    if (this._densidad.has(h)) return this._densidad.get(h);
    const conteo = new Map();
    const o = h * this.N;
    let dentro = 0;
    for (let n = 0; n < this.N; n++) {
      if (this.estado(n, h) === FUERA) continue;
      const i = Math.floor((this.lat[o + n] - this.lat0) / CELDA_DENSIDAD);
      const j = Math.floor((this.lon[o + n] - this.lon0) / CELDA_DENSIDAD);
      const k = i * 4096 + j;
      conteo.set(k, (conteo.get(k) || 0) + 1);
      dentro++;
    }
    const celdas = [...conteo.entries()].sort((a, b) => b[1] - a[1])
      .map(([k, c]) => ({ i: Math.floor(k / 4096), j: k % 4096, pct: (100 * c) / this.N, p90: false }));
    let acumulado = 0;
    for (const c of celdas) {
      if (acumulado >= 0.9 * dentro) break;
      c.p90 = true;
      acumulado += (c.pct * this.N) / 100;
    }
    const r = { celdas, dentro, maximo: celdas.length ? celdas[0].pct : 0 };
    if (this._densidad.size > 160) this._densidad.clear();
    this._densidad.set(h, r);
    return r;
  }

  // Partícula a flote más cercana a un punto de pantalla (para el hover en pausa).
  masCercana(t, proyectarX, proyectarY, x, y, radioPx, costa) {
    const p = [0, 0];
    let mejor = -1, d2 = radioPx * radioPx;
    for (let n = 0; n < this.N; n++) {
      if (this.estado(n, t) !== A_FLOTE) continue;
      this.posVisible(n, t, p, costa);
      const dx = proyectarX(p[0]) - x, dy = proyectarY(p[1]) - y;
      const d = dx * dx + dy * dy;
      if (d < d2) { d2 = d; mejor = n; }
    }
    return mejor;
  }
}
