"""«Mercado hoy»: indicadores básicos del mercado para el menú principal.

Escribe data/_mercado_hoy.json (automático, nunca a mano). Los valores que no tienen
fuente gratuita (NAAIM, miedo y codicia de CNN, MOVE) se apuntan en manual/_mercado.json
y la web los marca como «manual».

Fuentes (todas oficiales o del propio emisor del dato, sin scraping de terceros):
- FRED (Reserva Federal de St. Louis): S&P 500, Nasdaq, VIX, WTI y diferenciales de crédito
  de ICE BofA. Con FRED_API_KEY usa la API oficial; sin clave, la descarga CSV oficial de FRED.
- Departamento del Tesoro de EE. UU.: bono a 5 y 10 años (curva diaria).
- Finnhub (FINNHUB_API_KEY): ETF HYG, LQD, KRE, URTH (MSCI World) y EWY (Corea).
- Twelve Data (TWELVEDATA_API_KEY): EUR/USD, oro (XAU/USD) y bitcoin (BTC/USD).
- OFR (Oficina de Investigación Financiera del Tesoro): índice de estrés financiero.
- AAII: encuesta semanal de sentimiento, leída de aaii.com (emisor del dato).
- Cboe: ratio put/call diario, del propio Cboe.

Índice propio de miedo y codicia: misma receta que el de CNN con los componentes que
tienen fuente oficial. Cada componente se puntúa de 0 a 100 según dónde está hoy frente a
sus dos últimos años (percentil) y el índice es la media.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = "data/_mercado_hoy.json"

FRED_API = "https://api.stlouisfed.org/fred/series/observations"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_PAGE = "https://fred.stlouisfed.org/series/{}"
TREASURY_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
TREASURY_PAGE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"
OFR_CSV = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
OFR_PAGE = "https://www.financialresearch.gov/financial-stress-index/"
AAII_PAGE = "https://www.aaii.com/sentimentsurvey"
CBOE_JSON = "https://cdn.cboe.com/data/us/options/market_statistics/daily/{d}_daily_options"
CBOE_PAGE = "https://www.cboe.com/us/options/market_statistics/daily/"

# id, nombre, grupo, origen, símbolo, unidad, fuente, precio en vivo (ticker, modo)
INDICADORES = [
    ("sp500", "S&P 500", "bolsa", "fred", "SP500", "pts", "FRED (S&P Dow Jones Indices)", ("SPY", "ref")),
    ("nasdaq", "Nasdaq Composite", "bolsa", "fred", "NASDAQCOM", "pts", "FRED (Nasdaq)", ("QQQ", "ref")),
    ("msci_world", "MSCI World (ETF URTH)", "bolsa", "finnhub", "URTH", "$", "Finnhub", ("URTH", "directo")),
    ("corea", "Corea del Sur (ETF EWY)", "bolsa", "finnhub", "EWY", "$", "Finnhub", ("EWY", "directo")),
    ("vix", "VIX", "riesgo", "fred", "VIXCLS", "pts", "FRED (Cboe)", None),
    ("move", "MOVE (volatilidad de bonos)", "riesgo", "manual", "move", "pts", "ICE BofA · introducido a mano", None),
    ("hyg", "Bonos high yield (HYG)", "riesgo", "finnhub", "HYG", "$", "Finnhub", ("HYG", "directo")),
    ("lqd", "Bonos grado de inversión (LQD)", "riesgo", "finnhub", "LQD", "$", "Finnhub", ("LQD", "directo")),
    ("dif_hy", "Diferencial high yield", "riesgo", "fred", "BAMLH0A0HYM2", "%", "FRED (ICE BofA)", None),
    ("kre", "Bancos regionales (KRE)", "riesgo", "finnhub", "KRE", "$", "Finnhub", ("KRE", "directo")),
    ("us5y", "Bono EE. UU. 5 años", "tipos", "tesoro", "5 Yr", "%", "Tesoro de EE. UU.", None),
    ("us10y", "Bono EE. UU. 10 años", "tipos", "tesoro", "10 Yr", "%", "Tesoro de EE. UU.", None),
    ("eurusd", "EUR/USD", "tipos", "twelvedata", "EUR/USD", "", "Twelve Data", None),
    ("oro", "Oro (onza)", "materias", "twelvedata", "XAU/USD", "$", "Twelve Data", None),
    ("wti", "Petróleo WTI (barril)", "materias", "fred", "DCOILWTICO", "$", "FRED (EIA)", None),
    ("bitcoin", "Bitcoin", "materias", "twelvedata", "BTC/USD", "$", "Twelve Data", None),
]
GRUPOS = {"bolsa": "Bolsa", "riesgo": "Volatilidad y crédito", "tipos": "Tipos y divisas",
          "materias": "Materias primas y cripto"}

ETIQUETAS = [(25, "Miedo extremo"), (45, "Miedo"), (55, "Neutral"), (75, "Codicia"), (101, "Codicia extrema")]
VENTANA = 504          # dos años de sesiones para los percentiles
DURACION_10A = 8.5     # duración aproximada del bono a 10 años (para su rentabilidad a 20 días)


# ---------------------------------------------------------------- HTTP
def _get(url, headers=None, opener=urllib.request.urlopen, sleep=time.sleep, tries=3, timeout=40):
    h = {"User-Agent": "Mozilla/5.0 (valorador; datos de mercado)", "Accept": "*/*"}
    h.update(headers or {})
    last = None
    for attempt in range(tries):
        try:
            with opener(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (400, 401, 403, 404):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = str(e)
        sleep(2 * (attempt + 1))
    raise RuntimeError(f"{urllib.parse.urlsplit(url).netloc}: {last or 'sin respuesta'}")


def _num(s):
    try:
        v = float(str(s).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ---------------------------------------------------------------- parsers (puros, con tests)
def parse_fred_json(text):
    obs = json.loads(text).get("observations") or []
    return [(o["date"], v) for o in obs if (v := _num(o.get("value"))) is not None]


def parse_fred_csv(text):
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    out = []
    for r in rows[1:]:
        if len(r) >= 2 and re.match(r"^\d{4}-\d{2}-\d{2}$", r[0]) and (v := _num(r[1])) is not None:
            out.append((r[0], v))
    return out


def parse_treasury(text, col):
    out = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        v, dt = _num(r.get(col)), (r.get("Date") or "").strip()
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", dt)
        if v is not None and m:
            out.append((date(int(m[3]), int(m[1]), int(m[2])).isoformat(), v))
    return sorted(out)


def parse_ofr(text):
    """CSV del OFR: primera columna fecha, la del índice se llama «OFR FSI» (o es la segunda)."""
    rd = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rd:
        return []
    head = [h.strip().lower() for h in rd[0]]
    col = next((i for i, h in enumerate(head) if h in ("ofr fsi", "ofr_fsi", "fsi")), 1)
    out = []
    for r in rd[1:]:
        if len(r) <= col:
            continue
        d = r[0].strip()
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", d)
        if m:
            d = date(int(m[3]), int(m[1]), int(m[2])).isoformat()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d) and (v := _num(r[col])) is not None:
            out.append((d, v))
    return sorted(out)


MESES_EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                         "august", "september", "october", "november", "december"], 1)}


def parse_aaii(html):
    """Encuesta AAII: porcentajes de alcistas, neutrales y bajistas de la semana y su fecha."""
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"&nbsp;|&#160;", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    vals = {}
    for k, lab in (("alcistas", "Bullish"), ("neutrales", "Neutral"), ("bajistas", "Bearish")):
        m = re.search(lab + r"\s*:?\s*(\d{1,2}(?:\.\d+)?)\s*%", txt)
        if not m:
            return None
        vals[k] = float(m[1])
    if not 97 <= sum(vals.values()) <= 103:      # los tres deben sumar ~100
        return None
    fecha = None
    m = re.search(r"[Ww]eek [Ee]nding\s+([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})", txt)
    if m and m[1].lower() in MESES_EN:
        fecha = date(int(m[3]), MESES_EN[m[1].lower()], int(m[2])).isoformat()
    else:
        m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", txt)
        if m:
            fecha = date(int(m[3]), int(m[1]), int(m[2])).isoformat()
    medias = {}
    for k, lab in (("alcistas", "Bullish"), ("neutrales", "Neutral"), ("bajistas", "Bearish")):
        m = re.search(lab + r"\s*:?\s*\d{1,2}(?:\.\d+)?\s*%\s*\(?\s*Avg\.?\s*(\d{1,2}(?:\.\d+)?)\s*%", txt)
        if m:
            medias[k] = float(m[1])
    out = dict(vals, fecha=fecha, diferencial=round(vals["alcistas"] - vals["bajistas"], 1))
    if len(medias) == 3:
        out["medias"] = medias
    return out


def parse_cboe(text):
    """Ratio put/call total del día en el JSON de estadísticas diarias del Cboe."""
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        return None
    found = {}

    def walk(o):
        if isinstance(o, dict):
            n = str(o.get("name") or o.get("label") or "").upper()
            if "PUT/CALL" in n and (v := _num(o.get("value"))) is not None:
                found[n] = v
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(j)
    for k, v in found.items():
        if "TOTAL" in k and 0.2 < v < 3:
            return v
    return None


# ---------------------------------------------------------------- índice propio de miedo y codicia
class Serie:
    """Serie (fecha, valor) ordenada con búsqueda del último dato hasta una fecha."""

    def __init__(self, pts):
        pts = sorted(pts)
        self.d = [p[0] for p in pts]
        self.v = [p[1] for p in pts]

    def __len__(self):
        return len(self.d)

    def en(self, d, max_dias=7):
        i = bisect.bisect_right(self.d, d) - 1
        if i < 0:
            return None
        if (date.fromisoformat(d) - date.fromisoformat(self.d[i])).days > max_dias:
            return None
        return self.v[i]


def _media_movil(vals, n):
    out, s = [], 0.0
    for i, x in enumerate(vals):
        s += x
        if i >= n:
            s -= vals[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def _percentil(ventana, x):
    if len(ventana) < 60:
        return None
    return 100.0 * sum(1 for w in ventana if w <= x) / len(ventana)


def etiqueta(v):
    return next(t for lim, t in ETIQUETAS if v < lim)


def puntuar_putcall(pc5):
    """0 (miedo) con put/call medio de 5 días ≥ 1,15; 100 (codicia) con ≤ 0,75."""
    return max(0.0, min(100.0, (1.15 - pc5) / (1.15 - 0.75) * 100))


COMPONENTES = {
    "impulso": ("Impulso del mercado", "S&P 500 frente a su media de 125 sesiones. Por encima, codicia."),
    "volatilidad": ("Volatilidad", "VIX frente a su media de 50 sesiones. Si sube por encima, miedo."),
    "bonos_basura": ("Demanda de bonos basura", "Diferencial high yield menos el de grado de inversión. Si se abre, miedo."),
    "refugio": ("Demanda de refugio", "Rentabilidad a 20 sesiones de la bolsa menos la del bono a 10 años. Si ganan los bonos, miedo."),
    "put_call": ("Ratio put/call", "Media de 5 sesiones del ratio put/call total del Cboe. Muchas puts, miedo."),
}


def miedo_codicia(sp, vix, hy, ig, y10, pc=None, n_hist=70):
    """Devuelve {fechas: [...], series: {componente: [puntuación…]}, brutos: {...}} de las últimas n_hist sesiones."""
    sp, vix, hy, ig, y10 = (Serie(s) for s in (sp, vix, hy, ig, y10))
    pc = Serie(pc or [])
    if len(sp) < 200:
        return None
    # métricas diarias en las fechas del S&P 500
    ma125 = _media_movil(sp.v, 125)
    vma = _media_movil(vix.v, 50)
    vix_ratio = Serie([(vix.d[i], vix.v[i] / vma[i] - 1) for i in range(len(vix)) if vma[i]])
    pc5 = _media_movil(pc.v, 5)
    pc5s = Serie([(pc.d[i], pc5[i]) for i in range(len(pc)) if pc5[i]])
    met = {k: [] for k in COMPONENTES}     # listas paralelas a sp.d (None si no hay dato)
    for i, d in enumerate(sp.d):
        met["impulso"].append(sp.v[i] / ma125[i] - 1 if ma125[i] else None)
        met["volatilidad"].append(vix_ratio.en(d))
        h, g = hy.en(d), ig.en(d)
        met["bonos_basura"].append(h - g if h is not None and g is not None else None)
        r = None
        if i >= 20:
            y, y0 = y10.en(d), y10.en(sp.d[i - 20])
            if y is not None and y0 is not None:
                bono = -DURACION_10A * (y - y0) + y0 * 20 / 252
                r = (sp.v[i] / sp.v[i - 20] - 1) * 100 - bono
        met["refugio"].append(r)
        met["put_call"].append(pc5s.en(d, max_dias=4))
    invertir = {"volatilidad", "bonos_basura"}
    ini = max(0, len(sp.d) - n_hist)
    fechas, punt = [], {k: [] for k in COMPONENTES}
    for i in range(ini, len(sp.d)):
        fechas.append(sp.d[i])
        for k, xs in met.items():
            x = xs[i]
            if x is None:
                punt[k].append(None)
                continue
            if k == "put_call":
                punt[k].append(round(puntuar_putcall(x), 1))
                continue
            win = [w for w in xs[max(0, i - VENTANA + 1): i + 1] if w is not None]
            p = _percentil(win, x)
            punt[k].append(None if p is None else round(100 - p if k in invertir else p, 1))
    total = []
    for j in range(len(fechas)):
        vs = [punt[k][j] for k in COMPONENTES if punt[k][j] is not None]
        total.append(round(sum(vs) / len(vs), 1) if len(vs) >= 3 else None)
    brutos = {k: met[k][-1] for k in COMPONENTES}
    return {"fechas": fechas, "puntuaciones": punt, "total": total, "brutos": brutos}


def resumen_miedo_codicia(r, fuentes):
    if not r:
        return None
    idx = [i for i, v in enumerate(r["total"]) if v is not None]
    if not idx:
        return None
    i = idx[-1]

    def hace(n):
        j = i - n
        return {"valor": r["total"][j], "fecha": r["fechas"][j]} if j >= 0 and r["total"][j] is not None else None
    comps = []
    for k, (nom, desc) in COMPONENTES.items():
        p = r["puntuaciones"][k][i]
        bruto = r["brutos"][k]
        comps.append({"id": k, "nombre": nom, "descripcion": desc,
                      "puntuacion": p, "etiqueta": etiqueta(p) if p is not None else None,
                      "bruto": round(bruto, 4) if bruto is not None else None,
                      "fuente": fuentes[k][0], "url": fuentes[k][1]})
    v = r["total"][i]
    return {"valor": v, "etiqueta": etiqueta(v), "fecha": r["fechas"][i],
            "n_componentes": sum(1 for c in comps if c["puntuacion"] is not None),
            "anterior": hace(1), "hace_1s": hace(5), "hace_1m": hace(21),
            "componentes": comps,
            "serie": [[r["fechas"][j], r["total"][j]] for j in idx[-60:]],
            "metodo": "Media de los componentes disponibles, cada uno puntuado de 0 a 100 según su percentil frente a los dos últimos años de sesiones (el put/call, por tramos fijos). Misma receta que el índice de CNN, sin los dos componentes de amplitud de la NYSE, que no tienen fuente gratuita."}


# ---------------------------------------------------------------- fuentes
class Fuentes:
    def __init__(self, env=os.environ, http=_get, hoy=None, sleep=time.sleep):
        self.env, self.http, self.sleep = env, http, sleep
        self.hoy = hoy or date.today()
        self.fred_key = (env.get("FRED_API_KEY") or "").strip()
        self.fh_key = (env.get("FINNHUB_API_KEY") or "").strip()
        self.td_key = (env.get("TWELVEDATA_API_KEY") or "").strip()
        self.fred_caido = None

    def fred(self, sid, desde):
        if self.fred_caido:            # si FRED no responde, no se insiste con cada serie
            raise RuntimeError(self.fred_caido)
        try:
            if self.fred_key:
                q = urllib.parse.urlencode({"series_id": sid, "api_key": self.fred_key, "file_type": "json",
                                            "observation_start": desde})
                return parse_fred_json(self.http(f"{FRED_API}?{q}"))
            # sin clave: la descarga CSV de FRED suele no responder a servidores, así que un solo intento
            return parse_fred_csv(self.http(f"{FRED_CSV}?{urllib.parse.urlencode({'id': sid, 'cosd': desde})}",
                                            tries=1, timeout=20))
        except RuntimeError as e:
            self.fred_caido = (f"{e}" if self.fred_key else
                               f"{e}; falta el secret FRED_API_KEY: sin clave, FRED no responde desde GitHub (ver README)")
            raise RuntimeError(self.fred_caido) from None

    def tesoro(self, col):
        pts = []
        for y in (self.hoy.year - 1, self.hoy.year):
            try:
                pts += parse_treasury(self.http(TREASURY_CSV.format(y=y)), col)
            except RuntimeError:
                if y == self.hoy.year and not pts:
                    raise
        return sorted(set(pts))

    def finnhub(self, sym):
        if not self.fh_key:
            raise RuntimeError("falta FINNHUB_API_KEY")
        q = json.loads(self.http(f"https://finnhub.io/api/v1/quote?{urllib.parse.urlencode({'symbol': sym, 'token': self.fh_key})}"))
        self.sleep(1.1)
        if not q.get("c") or not q.get("t"):
            raise RuntimeError(f"Finnhub sin cotización de {sym}")
        return {"valor": q["c"], "anterior": q.get("pc"),
                "fecha": datetime.fromtimestamp(q["t"], tz=timezone.utc).date().isoformat()}

    def twelvedata(self, sym):
        if not self.td_key:
            raise RuntimeError("falta TWELVEDATA_API_KEY")
        j = json.loads(self.http(f"https://api.twelvedata.com/quote?{urllib.parse.urlencode({'symbol': sym, 'apikey': self.td_key})}"))
        self.sleep(8)
        if j.get("status") == "error" or _num(j.get("close")) is None:
            raise RuntimeError(f"Twelve Data: {j.get('message') or 'sin cotización de ' + sym}")
        return {"valor": _num(j["close"]), "anterior": _num(j.get("previous_close")),
                "fecha": str(j.get("datetime") or "")[:10]}

    def ofr(self):
        return parse_ofr(self.http(OFR_CSV))

    def aaii(self):
        return parse_aaii(self.http(AAII_PAGE, headers={"Accept": "text/html", "Accept-Language": "en-US,en"}, tries=2))

    def putcall(self, ya=None):
        """Últimas sesiones del ratio put/call; solo pide al Cboe los días que no tenemos."""
        ya = dict(ya or [])
        d, sesiones = self.hoy, 0
        while sesiones < 8:
            if d.weekday() < 5:
                sesiones += 1
                k = d.isoformat()
                if k not in ya:
                    try:
                        v = parse_cboe(self.http(CBOE_JSON.format(d=k), tries=1))
                        if v:
                            ya[k] = v
                    except RuntimeError:
                        pass
            d -= timedelta(days=1)
        corte = (self.hoy - timedelta(days=60)).isoformat()
        return sorted((k, v) for k, v in ya.items() if k >= corte)


# ---------------------------------------------------------------- construcción
def _indicador(spec, q, fuente_url):
    iid, nombre, grupo, origen, sym, unidad, fuente, vivo = spec
    v, a = q["valor"], q.get("anterior")
    o = {"id": iid, "nombre": nombre, "grupo": grupo, "simbolo": sym, "unidad": unidad,
         "valor": round(v, 4), "anterior": round(a, 4) if a is not None else None, "fecha": q["fecha"],
         "fuente": fuente, "url": fuente_url}
    if a:
        o["var"] = round(v - a, 4)
        if unidad != "%":                 # en tipos y diferenciales, la variación va en puntos básicos
            o["var_pct"] = round((v / a - 1) * 100, 2)
    if vivo:
        o["vivo"] = {"ticker": vivo[0], "modo": vivo[1]}
    if origen == "finnhub" and sym in ("URTH", "EWY"):
        o["nota"] = "ETF que replica el índice: el índice no tiene fuente gratuita."
    return o


def build(f: Fuentes, old=None):
    old = old or {}
    avisos = []
    old_ind = {i["id"]: i for i in old.get("indicadores") or []}
    desde = (f.hoy - timedelta(days=4 * 366)).isoformat()
    series = {}

    def fred(sid):
        if sid not in series:
            try:
                series[sid] = f.fred(sid, desde)
            except RuntimeError as e:
                series[sid] = e
        if isinstance(series[sid], Exception):
            raise series[sid]
        return series[sid]

    ind = []
    for spec in INDICADORES:
        iid, nombre, _, origen, sym, *_ = spec
        if origen == "manual":
            continue
        try:
            if origen == "fred":
                s = fred(sym)
                q = {"valor": s[-1][1], "anterior": s[-2][1], "fecha": s[-1][0]}
                url = FRED_PAGE.format(sym)
            elif origen == "tesoro":
                s = f.tesoro(sym)
                series["tesoro:" + sym] = s
                q = {"valor": s[-1][1], "anterior": s[-2][1], "fecha": s[-1][0]}
                url = TREASURY_PAGE
            elif origen == "finnhub":
                q, url = f.finnhub(sym), "https://finnhub.io/"
            else:
                q, url = f.twelvedata(sym), "https://twelvedata.com/"
            ind.append(_indicador(spec, q, url))
        except (RuntimeError, IndexError, KeyError, ValueError, json.JSONDecodeError) as e:
            avisos.append(f"{nombre}: no disponible ({e}).")
            if iid in old_ind:
                ind.append(dict(old_ind[iid], desactualizado=True))

    sent = dict(old.get("sentimiento") or {})
    # índice de estrés del OFR
    try:
        s = f.ofr()
        if len(s) < 2:
            raise RuntimeError("CSV vacío")
        ant = next((v for d, v in reversed(s) if date.fromisoformat(d) <= date.fromisoformat(s[-1][0]) - timedelta(days=7)), None)
        sent["estres_ofr"] = {"valor": s[-1][1], "anterior": s[-2][1], "hace_1s": ant, "fecha": s[-1][0],
                              "maximo_1a": max(v for d, v in s if d >= (f.hoy - timedelta(days=365)).isoformat()),
                              "fuente": "OFR · Oficina de Investigación Financiera del Tesoro de EE. UU.", "url": OFR_PAGE}
    except (RuntimeError, ValueError) as e:
        avisos.append(f"Estrés financiero OFR: no disponible ({e}).")
    # encuesta AAII
    try:
        a = f.aaii()
        if not a:
            raise RuntimeError("no se reconocen los porcentajes en la página")
        sent["aaii"] = dict(a, fuente="AAII · encuesta semanal de sentimiento", url=AAII_PAGE)
    except RuntimeError as e:
        avisos.append(f"Encuesta AAII: no se ha podido leer ({e}). Puedes apuntarla en manual/_mercado.json.")
    # ratio put/call (opcional)
    pc_old = (old.get("_series") or {}).get("put_call") or []
    try:
        pc = f.putcall(pc_old)
    except RuntimeError:
        pc = pc_old
    if not pc:
        avisos.append("Ratio put/call del Cboe: no disponible; el índice de miedo y codicia se calcula sin él.")
    # índice propio de miedo y codicia
    try:
        r = miedo_codicia(fred("SP500"), fred("VIXCLS"), fred("BAMLH0A0HYM2"), fred("BAMLC0A0CM"),
                          fred("DGS10"), pc)
        fu = {"impulso": ("S&P 500 vía FRED", FRED_PAGE.format("SP500")),
              "volatilidad": ("VIX (Cboe) vía FRED", FRED_PAGE.format("VIXCLS")),
              "bonos_basura": ("FRED (ICE BofA)", FRED_PAGE.format("BAMLH0A0HYM2")),
              "refugio": ("S&P 500 y bono a 10 años vía FRED", FRED_PAGE.format("DGS10")),
              "put_call": ("Cboe · estadísticas diarias", CBOE_PAGE)}
        mc = resumen_miedo_codicia(r, fu)
        if mc:
            sent["miedo_codicia"] = mc
        else:
            avisos.append("Miedo y codicia: faltan datos para calcularlo.")
    except (RuntimeError, ValueError) as e:
        avisos.append(f"Miedo y codicia: no se ha podido calcular ({e}).")

    return {"esquema": 1,
            "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "grupos": GRUPOS,
            "indicadores": ind,
            "sentimiento": sent,
            "avisos": avisos,
            "_series": {"put_call": pc}}


def run(root=ROOT, fuentes=None):
    from .main import write_if_changed
    path = Path(root) / OUT
    old = {}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    out = build(fuentes or Fuentes(), old)
    if not out["indicadores"] and not out["sentimiento"]:
        print("✗ Ninguna fuente de mercado ha respondido.", file=sys.stderr)
        for a in out["avisos"]:
            print("  · " + a, file=sys.stderr)
        return 2
    cambiado = write_if_changed(path, out)
    print(f"Mercado hoy: {len(out['indicadores'])} indicadores; {'actualizado' if cambiado else 'sin cambios'}.")
    for a in out["avisos"]:
        print(f"::warning title=Mercado hoy::{a}")
    return 0


def main(argv=None):
    argparse.ArgumentParser(description="Indicadores de mercado para el menú principal.").parse_args(argv)
    return run()


if __name__ == "__main__":
    sys.exit(main())
