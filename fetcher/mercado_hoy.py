"""«Mercado hoy»: indicadores básicos del mercado para el menú principal.

Escribe data/_mercado_hoy.json (automático, nunca a mano). Los valores que no tienen
fuente gratuita (NAAIM, miedo y codicia de CNN, MOVE) se apuntan en manual/_mercado.json
y la web los marca como «manual».

Fuentes (todas oficiales, del propio emisor del dato o API con plan gratuito; sin scraping de terceros):
- Finnhub (FINNHUB_API_KEY): ETF que replican índices de bolsa, bonos, plata, cobre y uranio.
- Twelve Data (TWELVEDATA_API_KEY): divisas, oro y cripto en un solo lote, y la serie diaria del SPY.
- Cboe: VIX, VIX a 3 meses, VXN, OVX y GVZ (históricos diarios oficiales) y el ratio put/call.
- Departamento del Tesoro de EE. UU.: curva diaria (3 meses a 30 años).
- BCE: bono AAA de la zona euro a 10 años.
- FRED (Reserva Federal de St. Louis): índice dólar de la Fed, diferenciales de ICE BofA, hipoteca de
  Freddie Mac y petróleo y gas de la EIA.
- OFR (Oficina de Investigación Financiera del Tesoro): índice de estrés financiero.
- AAII: encuesta semanal de sentimiento, leída de aaii.com (emisor del dato).

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

CBOE_CSV = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{s}_History.csv"
CBOE_IDX_PAGE = "https://www.cboe.com/tradable_products/vix/vix_historical_data/"
ECB_API = "https://data-api.ecb.europa.eu/service/data/{k}?format=csvdata&lastNObservations={n}"
ECB_PAGE = "https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
TD_PAGE = "https://twelvedata.com/"
FH_PAGE = "https://finnhub.io/"

GRUPOS = {"bolsa": "Bolsa", "volatilidad": "Volatilidad y divisas", "bonos": "Bonos y crédito",
          "materias": "Materias primas y cripto"}
# Cabecera de cada tema: fuentes y el indicador que va en grande en la tarjeta (y los 4 de debajo).
TEMAS = {
    "bolsa": {"sub": "Índices vía ETF (Finnhub) · en vivo durante la sesión", "top": "sp500",
              "resto": ["nasdaq", "dow", "russell", "msci_world"]},
    "volatilidad": {"sub": "Cboe, Reserva Federal y Twelve Data", "top": "vix",
                    "resto": ["move", "dolar", "eurusd", "usdjpy"]},
    "bonos": {"sub": "Tesoro de EE. UU., ICE BofA, BCE y Freddie Mac", "top": "us10y",
              "resto": ["us2y", "dif_hy", "dif_ig", "hipoteca"]},
    "materias": {"sub": "Twelve Data, EIA (vía FRED) y ETF", "top": "oro",
                 "resto": ["wti", "cobre", "plata", "bitcoin"]},
}


def _i(iid, nombre, grupo, seccion, origen, sym, unidad, fuente, corto, vivo=None, nota=None):
    return {"id": iid, "nombre": nombre, "grupo": grupo, "seccion": seccion, "origen": origen, "simbolo": sym,
            "unidad": unidad, "fuente": fuente, "corto": corto, "vivo": vivo, "nota": nota}


ETF = "ETF que replica el índice: el índice no tiene fuente gratuita."
INDICADORES = [
    # Bolsa
    _i("sp500", "S&P 500", "bolsa", "Estados Unidos", "finnhub", "SPY", "$", "Finnhub", "ETF SPY", ("SPY", "directo"), ETF),
    _i("nasdaq", "Nasdaq-100", "bolsa", "Estados Unidos", "finnhub", "QQQ", "$", "Finnhub", "ETF QQQ", ("QQQ", "directo"), ETF),
    _i("dow", "Dow Jones", "bolsa", "Estados Unidos", "finnhub", "DIA", "$", "Finnhub", "ETF DIA", ("DIA", "directo"), ETF),
    _i("russell", "Russell 2000", "bolsa", "Estados Unidos", "finnhub", "IWM", "$", "Finnhub", "ETF IWM · pequeñas", ("IWM", "directo"), ETF),
    _i("msci_world", "MSCI World", "bolsa", "Resto del mundo", "finnhub", "URTH", "$", "Finnhub", "ETF URTH", ("URTH", "directo"), ETF),
    _i("europa", "Europa", "bolsa", "Resto del mundo", "finnhub", "VGK", "$", "Finnhub", "ETF VGK", ("VGK", "directo"), "ETF en dólares de las grandes compañías europeas."),
    _i("espana", "España", "bolsa", "Resto del mundo", "finnhub", "EWP", "$", "Finnhub", "ETF EWP", ("EWP", "directo"), "ETF en dólares de la bolsa española: incluye el efecto del euro."),
    _i("japon", "Japón", "bolsa", "Resto del mundo", "finnhub", "EWJ", "$", "Finnhub", "ETF EWJ", ("EWJ", "directo"), "ETF en dólares: incluye el efecto del yen."),
    _i("china", "China", "bolsa", "Resto del mundo", "finnhub", "MCHI", "$", "Finnhub", "ETF MCHI", ("MCHI", "directo"), ETF),
    _i("corea", "Corea del Sur", "bolsa", "Resto del mundo", "finnhub", "EWY", "$", "Finnhub", "ETF EWY", ("EWY", "directo"), "ETF que replica el KOSPI en dólares: el índice no tiene fuente gratuita."),
    _i("emergentes", "Emergentes", "bolsa", "Resto del mundo", "finnhub", "EEM", "$", "Finnhub", "ETF EEM", ("EEM", "directo"), ETF),
    _i("semis", "Semiconductores", "bolsa", "Sectores", "finnhub", "SOXX", "$", "Finnhub", "ETF SOXX", ("SOXX", "directo")),
    _i("kre", "Bancos regionales", "bolsa", "Sectores", "finnhub", "KRE", "$", "Finnhub", "ETF KRE", ("KRE", "directo")),
    # Volatilidad y divisas
    _i("vix", "VIX", "volatilidad", "Volatilidad", "cboe", "VIX", "pts", "Cboe", "Cboe · S&P 500 a 30 días"),
    _i("vix3m", "VIX a 3 meses", "volatilidad", "Volatilidad", "cboe", "VIX3M", "pts", "Cboe", "Cboe VIX3M"),
    _i("vxn", "Volatilidad Nasdaq", "volatilidad", "Volatilidad", "cboe", "VXN", "pts", "Cboe", "Cboe VXN"),
    _i("move", "MOVE", "volatilidad", "Volatilidad", "manual", "move", "pts", "ICE BofA · introducido a mano", "Volatilidad de bonos"),
    _i("ovx", "Volatilidad petróleo", "volatilidad", "Volatilidad", "cboe", "OVX", "pts", "Cboe", "Cboe OVX"),
    _i("gvz", "Volatilidad oro", "volatilidad", "Volatilidad", "cboe", "GVZ", "pts", "Cboe", "Cboe GVZ"),
    _i("dolar", "Índice dólar", "volatilidad", "Divisas", "fred", "DTWEXBGS", "pts", "Reserva Federal (FRED)", "Fed · amplio",
       ("UUP", "ref"), "Índice amplio de la Fed frente a 26 divisas; se publica con una semana de retraso. En sesión se muestra el ETF UUP."),
    _i("eurusd", "EUR/USD", "volatilidad", "Divisas", "twelvedata", "EUR/USD", "", "Twelve Data", "Twelve Data"),
    _i("usdjpy", "USD/JPY", "volatilidad", "Divisas", "twelvedata", "USD/JPY", "", "Twelve Data", "Twelve Data"),
    _i("gbpusd", "GBP/USD", "volatilidad", "Divisas", "twelvedata", "GBP/USD", "", "Twelve Data", "Twelve Data"),
    _i("usdcny", "USD/CNY", "volatilidad", "Divisas", "twelvedata", "USD/CNY", "", "Twelve Data", "Twelve Data"),
    # Bonos y crédito
    _i("us3m", "Letra 3 meses", "bonos", "Deuda pública", "tesoro", "3 Mo", "%", "Tesoro de EE. UU.", "Tesoro"),
    _i("us2y", "Bono 2 años", "bonos", "Deuda pública", "tesoro", "2 Yr", "%", "Tesoro de EE. UU.", "Tesoro"),
    _i("us5y", "Bono 5 años", "bonos", "Deuda pública", "tesoro", "5 Yr", "%", "Tesoro de EE. UU.", "Tesoro"),
    _i("us10y", "Bono 10 años", "bonos", "Deuda pública", "tesoro", "10 Yr", "%", "Tesoro de EE. UU.", "Tesoro"),
    _i("us30y", "Bono 30 años", "bonos", "Deuda pública", "tesoro", "30 Yr", "%", "Tesoro de EE. UU.", "Tesoro"),
    _i("euro10y", "Bono AAA zona euro 10 años", "bonos", "Deuda pública", "ecb", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", "%", "BCE", "BCE · curva AAA",
       None, "Curva de los bonos con calificación AAA de la zona euro (en la práctica, sobre todo Alemania)."),
    _i("dif_hy", "Diferencial high yield", "bonos", "Crédito", "fred", "BAMLH0A0HYM2", "%", "ICE BofA (FRED)", "ICE BofA"),
    _i("dif_ig", "Diferencial grado inversión", "bonos", "Crédito", "fred", "BAMLC0A0CM", "%", "ICE BofA (FRED)", "ICE BofA"),
    _i("hyg", "Bonos high yield", "bonos", "Crédito", "finnhub", "HYG", "$", "Finnhub", "ETF HYG", ("HYG", "directo")),
    _i("lqd", "Bonos grado inversión", "bonos", "Crédito", "finnhub", "LQD", "$", "Finnhub", "ETF LQD", ("LQD", "directo")),
    _i("tlt", "Bonos largo plazo", "bonos", "Crédito", "finnhub", "TLT", "$", "Finnhub", "ETF TLT · 20+ años", ("TLT", "directo")),
    _i("hipoteca", "Hipoteca a 30 años", "bonos", "Crédito", "fred", "MORTGAGE30US", "%", "Freddie Mac (FRED)", "Freddie Mac · semanal"),
    # Materias primas y cripto
    _i("oro", "Oro (onza)", "materias", "Metales", "twelvedata", "XAU/USD", "$", "Twelve Data", "Twelve Data"),
    _i("plata", "Plata", "materias", "Metales", "finnhub", "SLV", "$", "Finnhub", "ETF SLV", ("SLV", "directo"),
       "ETF respaldado por plata física; el precio al contado no está en el plan gratuito."),
    _i("cobre", "Cobre", "materias", "Metales", "finnhub", "CPER", "$", "Finnhub", "ETF CPER", ("CPER", "directo"), "ETF de futuros de cobre."),
    _i("uranio", "Uranio", "materias", "Metales", "finnhub", "URA", "$", "Finnhub", "ETF URA", ("URA", "directo"), "ETF de mineras de uranio."),
    _i("wti", "Petróleo WTI", "materias", "Energía", "fred", "DCOILWTICO", "$", "EIA (FRED)", "EIA · barril", ("USO", "ref"),
       "Precio oficial al contado de la EIA, con unos días de retraso. En sesión se muestra el ETF USO."),
    _i("brent", "Petróleo Brent", "materias", "Energía", "fred", "DCOILBRENTEU", "$", "EIA (FRED)", "EIA · barril", ("USO", "ref"),
       "Precio oficial al contado de la EIA, con unos días de retraso."),
    _i("gas", "Gas natural", "materias", "Energía", "fred", "DHHNGSP", "$", "EIA (FRED)", "EIA · Henry Hub"),
    _i("bitcoin", "Bitcoin", "materias", "Cripto", "twelvedata", "BTC/USD", "$", "Twelve Data", "Twelve Data"),
    _i("ethereum", "Ethereum", "materias", "Cripto", "twelvedata", "ETH/USD", "$", "Twelve Data", "Twelve Data"),
]

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


def parse_cboe_csv(text):
    """Histórico diario de un índice del Cboe (VIX_History.csv…): [(fecha, cierre)]."""
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not re.match(r"\d{1,2}/\d{1,2}/\d{4}$", row[0].strip()):
            continue
        m, d, y = (int(x) for x in row[0].strip().split("/"))
        v = _num(row[-1])
        if v is not None and v > 0:
            out.append((f"{y:04d}-{m:02d}-{d:02d}", v))
    return sorted(set(out))


def parse_ecb_csv(text):
    """Respuesta csvdata de la API del BCE: [(fecha, valor)]."""
    rows = list(csv.DictReader(io.StringIO(text)))
    return sorted((r["TIME_PERIOD"], round(v, 4)) for r in rows
                  if (v := _num(r.get("OBS_VALUE"))) is not None and r.get("TIME_PERIOD"))


def parse_td_quote(j):
    if not isinstance(j, dict) or j.get("status") == "error" or _num(j.get("close")) is None:
        raise RuntimeError(f"Twelve Data: {(j or {}).get('message') or 'sin cotización'}"[:200])
    return {"valor": _num(j["close"]), "anterior": _num(j.get("previous_close")),
            "fecha": str(j.get("datetime") or "")[:10]}


def parse_td_series(text):
    j = json.loads(text)
    if j.get("status") == "error":
        raise RuntimeError(f"Twelve Data: {j.get('message')}"[:200])
    return sorted((v["datetime"][:10], _num(v["close"])) for v in j.get("values") or [] if _num(v.get("close")))


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
        """Una columna de la curva diaria del Tesoro; el CSV de cada año se descarga una sola vez."""
        cache = self.__dict__.setdefault("_tesoro", {})
        pts = []
        for y in (self.hoy.year - 1, self.hoy.year):
            if y not in cache:
                try:
                    cache[y] = self.http(TREASURY_CSV.format(y=y))
                except RuntimeError as e:
                    cache[y] = e
            if isinstance(cache[y], Exception):
                if y == self.hoy.year and not pts:
                    raise cache[y]
                continue
            pts += parse_treasury(cache[y], col)
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

    def twelvedata(self, syms):
        """Cotizaciones de Twelve Data en una sola petición (cada símbolo gasta un crédito; el plan gratuito
        admite 8 por minuto, así que como mucho 7 aquí y 1 para la serie del SPY)."""
        if not self.td_key:
            raise RuntimeError("falta TWELVEDATA_API_KEY")
        self._td_espera()
        j = json.loads(self.http(f"https://api.twelvedata.com/quote?{urllib.parse.urlencode({'symbol': ','.join(syms), 'apikey': self.td_key})}"))
        if len(syms) == 1:
            j = {syms[0]: j}
        if j.get("status") == "error" and "code" in j:
            raise RuntimeError(f"Twelve Data: {j.get('message')}"[:200])
        out = {}
        for k in syms:
            try:
                out[k] = parse_td_quote(j.get(k))
            except RuntimeError as e:
                out[k] = e
        return out

    def td_serie(self, sym, n=800):
        if not self.td_key:
            raise RuntimeError("falta TWELVEDATA_API_KEY")
        self._td_espera()
        q = urllib.parse.urlencode({"symbol": sym, "interval": "1day", "outputsize": n, "apikey": self.td_key})
        return parse_td_series(self.http(f"https://api.twelvedata.com/time_series?{q}"))

    def _td_espera(self):
        # dos peticiones seguidas a Twelve Data (serie del SPY y lote de cotizaciones) superan los 8 créditos
        # por minuto del plan gratuito: la segunda espera un minuto
        if getattr(self, "_td_usado", False):
            self.sleep(62)
        self._td_usado = True

    def cboe(self, sym):
        cache = self.__dict__.setdefault("_cboe", {})
        if sym not in cache:
            try:
                cache[sym] = parse_cboe_csv(self.http(CBOE_CSV.format(s=sym), headers={"User-Agent": "Mozilla/5.0"}))
            except RuntimeError as e:
                cache[sym] = e
        if isinstance(cache[sym], Exception):
            raise cache[sym]
        if len(cache[sym]) < 2:
            raise RuntimeError(f"Cboe sin datos de {sym}")
        return cache[sym]

    def ecb(self, key, n=30):
        return parse_ecb_csv(self.http(ECB_API.format(k=key, n=n), tries=2))

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
def _indicador(spec, q, fuente_url, serie=None):
    v, a, unidad = q["valor"], q.get("anterior"), spec["unidad"]
    o = {k: spec[k] for k in ("id", "nombre", "grupo", "seccion", "simbolo", "unidad", "fuente", "corto")}
    o.update(valor=round(v, 4), anterior=round(a, 4) if a is not None else None, fecha=q["fecha"], url=fuente_url)
    if a:
        o["var"] = round(v - a, 4)
        if unidad != "%":                 # en tipos y diferenciales, la variación va en puntos básicos
            o["var_pct"] = round((v / a - 1) * 100, 2)
    if spec["vivo"]:
        o["vivo"] = {"ticker": spec["vivo"][0], "modo": spec["vivo"][1]}
    if spec["nota"]:
        o["nota"] = spec["nota"]
    if serie:                             # últimos ~3 meses para la minigráfica de la web
        o["serie"] = [[d, round(x, 4)] for d, x in serie[-65:]]
    return o


def _desde_serie(s):
    return {"valor": s[-1][1], "anterior": s[-2][1], "fecha": s[-1][0]}


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

    # Twelve Data: primero la serie diaria del SPY (para el índice de miedo y codicia), luego un lote de cotizaciones
    spy = None
    try:
        spy = f.td_serie("SPY")
        if len(spy) < 200:
            raise RuntimeError("serie del SPY demasiado corta")
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as e:
        avisos.append(f"Serie diaria del SPY (Twelve Data): no disponible ({e}); el miedo y codicia usa el S&P 500 de FRED.")
        spy = None
    td_syms = [x["simbolo"] for x in INDICADORES if x["origen"] == "twelvedata"]
    try:
        td = f.twelvedata(td_syms)
    except (RuntimeError, json.JSONDecodeError) as e:
        td = {k: e for k in td_syms}

    ind = []
    for spec in INDICADORES:
        iid, nombre, origen, sym = spec["id"], spec["nombre"], spec["origen"], spec["simbolo"]
        if origen == "manual":
            continue
        serie = None
        try:
            if origen == "fred":
                serie = fred(sym)
                q, url = _desde_serie(serie), FRED_PAGE.format(sym)
            elif origen == "tesoro":
                serie = f.tesoro(sym)
                series["tesoro:" + sym] = serie
                q, url = _desde_serie(serie), TREASURY_PAGE
            elif origen == "cboe":
                serie = f.cboe(sym)
                q, url = _desde_serie(serie), CBOE_IDX_PAGE
            elif origen == "ecb":
                serie = f.ecb(sym, 70)
                q, url = _desde_serie(serie), ECB_PAGE
            elif origen == "finnhub":
                q, url = f.finnhub(sym), FH_PAGE
            else:
                q, url = td.get(sym, RuntimeError("sin respuesta")), TD_PAGE
                if isinstance(q, Exception):
                    raise q
            ind.append(_indicador(spec, q, url, serie))
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
    # índice propio de miedo y codicia: SPY diario (Twelve Data) y VIX del propio Cboe para que vaya al día;
    # FRED como respaldo. El bono a 10 años: FRED más la curva del Tesoro, que se publica el mismo día.
    try:
        if spy:
            bolsa, f_bolsa = spy, ("ETF SPY · Twelve Data", TD_PAGE)
        else:
            bolsa, f_bolsa = fred("SP500"), ("S&P 500 vía FRED", FRED_PAGE.format("SP500"))
        try:
            vix, f_vix = f.cboe("VIX"), ("VIX · Cboe", CBOE_IDX_PAGE)
        except RuntimeError:
            vix, f_vix = fred("VIXCLS"), ("VIX (Cboe) vía FRED", FRED_PAGE.format("VIXCLS"))
        y10 = dict(fred("DGS10"))
        t10 = series.get("tesoro:10 Yr")
        if isinstance(t10, list):
            y10.update(t10)
        r = miedo_codicia(bolsa, vix, fred("BAMLH0A0HYM2"), fred("BAMLC0A0CM"), sorted(y10.items()), pc)
        fu = {"impulso": f_bolsa, "volatilidad": f_vix,
              "bonos_basura": ("FRED (ICE BofA)", FRED_PAGE.format("BAMLH0A0HYM2")),
              "refugio": ("Bolsa y bono a 10 años (Tesoro y FRED)", TREASURY_PAGE),
              "put_call": ("Cboe · estadísticas diarias", CBOE_PAGE)}
        mc = resumen_miedo_codicia(r, fu)
        if mc:
            sent["miedo_codicia"] = mc
        else:
            avisos.append("Miedo y codicia: faltan datos para calcularlo.")
    except (RuntimeError, ValueError) as e:
        avisos.append(f"Miedo y codicia: no se ha podido calcular ({e}).")

    # tipos de interés: la Reserva Federal
    from . import tipos as T
    try:
        tip = T.build(f, fred, avisos, old.get("tipos"))
    except Exception as e:          # un fallo aquí nunca debe tumbar el resto del mercado
        avisos.append(f"Tipos de interés: error inesperado ({e}).")
        tip = old.get("tipos") or {}

    return {"esquema": 2,
            "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "grupos": GRUPOS,
            "temas": TEMAS,
            "indicadores": ind,
            "sentimiento": sent,
            "tipos": tip,
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
