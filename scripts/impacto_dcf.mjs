// Impacto en el valor por acción de los cambios de una propuesta.
// Usa el mismo motor del DCF que la web (bloque «ENGINE» de valorador.html),
// con acciones, caja y deuda de la SEC (más los ajustes por hechos posteriores)
// cuando el análisis no las fija.
//
//   node scripts/impacto_dcf.mjs VST                 → propuestas/VST.json
//   node scripts/impacto_dcf.mjs VST otra/ruta.json  → otra propuesta
//
// Imprime un JSON: {antes, despues, cambio_pct, precio, campos}. La regla del 5%
// de propuestas/INSTRUCCIONES.md (apartado 8) se aplica sobre «cambio_pct».
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const T = (process.argv[2] || "").toUpperCase();
if (!T) { console.error("Uso: node scripts/impacto_dcf.mjs <TICKER> [propuesta.json]"); process.exit(2); }
const propPath = process.argv[3] || path.join(root, "propuestas", `${T}.json`);

const html = fs.readFileSync(path.join(root, "valorador.html"), "utf8");
const m = /\/\/ ENGINE START([\s\S]*?)\/\/ ENGINE END/.exec(html);
if (!m) { console.error("No encuentro el motor del DCF en valorador.html"); process.exit(1); }
const ctx = { Math, Number, Object, Array, isFinite, NaN };
vm.createContext(ctx);
vm.runInContext(m[1] + "\n;this.dcf=dcf;this.scenarios=scenarios;", ctx);

const rd = p => { const t = fs.readFileSync(p, "utf8").trim(); return t ? JSON.parse(t) : {}; };
const an = rd(path.join(root, "analysis", `${T}.json`));
const d = rd(path.join(root, "data", `${T}.json`));
const prop = fs.existsSync(propPath) ? rd(propPath) : { cambios: [] };

const fin = x => typeof x === "number" && Number.isFinite(x);
const val = p => (p && fin(p.valor) ? p.valor / 1e6 : null);
const B = d.balance || {};
const sec = { shares: val(d.acciones_en_circulacion), cash: val(B.caja && B.caja.ultimo), debt: val(B.deuda && B.deuda.ultimo) };

function modelo(a) {
  const v = JSON.parse(JSON.stringify(a.v || {}));
  const accn = d.ultimo_informe && d.ultimo_informe.accn;
  for (const k of ["shares", "cash", "debt"]) {
    if (fin(v[k]) || !fin(sec[k])) continue;
    v[k] = sec[k];
    for (const aj of a.ajustes_posteriores || [])
      if (aj && aj.k === k && fin(aj.delta) && (!aj.base_accn || aj.base_accn === accn)) v[k] += aj.delta;
  }
  v.price = d.precio && fin(d.precio.valor) ? d.precio.valor : NaN;
  return v;
}
function setPath(o, p, x) {
  const ks = p.split("."); let y = o;
  for (let i = 0; i < ks.length - 1; i++) { if (y[ks[i]] == null) y[ks[i]] = /^\d+$/.test(ks[i + 1]) ? [] : {}; y = y[ks[i]]; }
  y[ks.at(-1)] = x;
}
function valor(a) {
  const s = modelo(a);
  if (!(s.shares > 0) || !(s.method === "exit" || s.wacc > s.tg) || !Array.isArray(s.scn)) return NaN;
  return ctx.scenarios(s).w;
}

const despuesA = JSON.parse(JSON.stringify(an));
const campos = [];
for (const c of prop.cambios || []) {
  if (!/^(v\.|ajustes_posteriores$)/.test(c.campo)) continue;
  setPath(despuesA, c.campo, c.valor); campos.push(c.campo);
}
const antes = valor(an), despues = valor(despuesA);
const r = x => (fin(x) ? Math.round(x * 100) / 100 : null);
console.log(JSON.stringify({
  ticker: T, precio: r(modelo(an).price), antes: r(antes), despues: r(despues),
  cambio_pct: fin(antes) && fin(despues) && antes !== 0 ? r((despues / antes - 1) * 100) : null,
  campos,
}, null, 1));
