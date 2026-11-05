/**
 * Precio en vivo del Valorador — Cloudflare Worker.
 *
 * La web (GitHub Pages) le pide:  GET <url-del-worker>/?s=APP,GOOGL,AMZN
 * y recibe:
 *   {
 *     "mercado": {"abierto": true, "sesion": "regular", "festivo": null},
 *     "cotizaciones": {"APP": {"precio": 512.3, "cierre_anterior": 500.1, "var": 12.2, "var_pct": 2.44,
 *                              "maximo": 515, "minimo": 498, "apertura": 501, "hora": "2026-11-05T15:42:10Z"}},
 *     "fuente": "Finnhub", "generado": "2026-11-05T15:42:31Z"
 *   }
 *
 * La clave de Finnhub vive como secreto del Worker (FINNHUB_API_KEY) y nunca llega al navegador.
 * Variables opcionales:
 *   ORIGENES  orígenes web permitidos, separados por comas (por defecto https://infomercadosgbx.github.io)
 *
 * Cada cotización se guarda en memoria 30 s y el estado del mercado 60 s, así que
 * varias pestañas o dispositivos abiertos a la vez no multiplican las llamadas a Finnhub.
 */

const FINNHUB = "https://finnhub.io/api/v1";
const TTL_COTIZACION = 30_000;
const TTL_MERCADO = 60_000;
const MAX_TICKERS = 40;
const cache = new Map(); // clave → {t, v}

export default {
  async fetch(req, env) {
    const permitidos = (env.ORIGENES || "https://infomercadosgbx.github.io")
      .split(",").map((s) => s.trim().replace(/\/$/, "")).filter(Boolean);
    const origen = req.headers.get("Origin") || "";
    const ok = permitidos.includes(origen);
    const cors = {
      "Access-Control-Allow-Origin": ok ? origen : permitidos[0],
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Vary": "Origin",
    };
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (req.method !== "GET") return json({ error: "Solo GET" }, 405, cors);
    if (!ok) return json({ error: "Origen no permitido. Añádelo a la variable ORIGENES del Worker." }, 403, cors);
    if (!env.FINNHUB_API_KEY) return json({ error: "Falta el secreto FINNHUB_API_KEY en el Worker." }, 500, cors);

    const url = new URL(req.url);
    const tickers = [...new Set((url.searchParams.get("s") || "").toUpperCase().split(","))]
      .map((s) => s.trim())
      .filter((s) => /^[A-Z][A-Z0-9.\-]{0,9}$/.test(s))
      .slice(0, MAX_TICKERS);

    const fh = (path, params) => conCache(`${path}?${new URLSearchParams(params)}`,
      path === "/stock/market-status" ? TTL_MERCADO : TTL_COTIZACION,
      () => finnhub(path, params, env.FINNHUB_API_KEY));

    const [estado, ...quotes] = await Promise.all([
      fh("/stock/market-status", { exchange: "US" }).catch(() => null),
      ...tickers.map((t) => fh("/quote", { symbol: t }).catch(() => null)),
    ]);

    const cotizaciones = {};
    tickers.forEach((t, i) => {
      const q = quotes[i];
      if (q && q.c && q.t) {
        cotizaciones[t] = {
          precio: q.c, cierre_anterior: q.pc ?? null, var: q.d ?? null, var_pct: q.dp ?? null,
          maximo: q.h ?? null, minimo: q.l ?? null, apertura: q.o ?? null,
          hora: new Date(q.t * 1000).toISOString(),
        };
      }
    });

    const body = {
      mercado: estado ? { abierto: !!estado.isOpen, sesion: estado.session || null, festivo: estado.holiday || null } : null,
      cotizaciones,
      fuente: "Finnhub",
      generado: new Date().toISOString(),
    };
    return json(body, 200, { ...cors, "Cache-Control": "no-store" });
  },
};

async function conCache(clave, ttl, cargar) {
  const hit = cache.get(clave);
  if (hit && Date.now() - hit.t < ttl) return hit.v;
  const v = await cargar();
  cache.set(clave, { t: Date.now(), v });
  if (cache.size > 200) cache.delete(cache.keys().next().value);
  return v;
}

async function finnhub(path, params, key) {
  const r = await fetch(`${FINNHUB}${path}?${new URLSearchParams({ ...params, token: key })}`, {
    headers: { "User-Agent": "valorador-precio-vivo" },
  });
  if (!r.ok) throw new Error(`Finnhub ${r.status}`);
  return r.json();
}

function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}
