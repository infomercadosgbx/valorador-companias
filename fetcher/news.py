"""Noticias de cada compañía a partir de varias fuentes, todas oficiales o publicadas por el propio medio:

  · Finnhub (API, la misma clave que la cotización): prensa financiera general.
  · Marketaux (API con plan gratuito; opcional, clave en GitHub Secrets), con el sentimiento de cada
    noticia sobre la compañía. Alpha Vantage queda preparado, pero sus noticias ya son de pago.
  · Feeds RSS que publica cada medio sectorial (Utility Dive, The Next Platform…) y las agencias
    de notas de prensa (Business Wire, PR Newswire). Se filtran por el nombre
    de la compañía y sus alias. No se lee ninguna web: solo el RSS que el medio ofrece.
  · 8-K de la SEC (sin peticiones extra; ver filings.recent_8k_news).
  · Google News (RSS público de búsqueda): titulares de la prensa financiera de referencia, también
    la de pago (Reuters, Bloomberg, FT, WSJ…), y de la prensa económica española. Solo titular,
    medio y fecha: el texto completo de los medios de pago lo lee otra tarea con la sesión del usuario.
  · Seeking Alpha (RSS público por ticker): titulares de noticias y análisis.
  · StockTwits (API pública): pulso de los inversores particulares (mensajes alcistas/bajistas).
    No son noticias: va a data/<T>.json → redes. Reddit exige una aplicación con OAuth; queda fuera.

Los feeds RSS solo muestran lo último publicado, así que lo encontrado se acumula noche a noche
(se conserva lo anterior durante la ventana de días). El estado de cada fuente se guarda en
data/_noticias_estado.json; un medio caído no genera avisos en las compañías.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "valorador-companias/1.0 (lector RSS; +https://github.com/infomercadosgbx/valorador-companias)"
VENTANA_DIAS = 30
LIMITE = 30

# id: (nombre visible, url del feed, tipo). tipo: "sectorial" o "nota_prensa"
FEEDS = {
    "utilitydive": ("Utility Dive", "https://www.utilitydive.com/feeds/news/", "sectorial"),
    "wnn": ("World Nuclear News", "https://www.world-nuclear-news.org/rss", "sectorial"),
    "nextplatform": ("The Next Platform", "https://www.nextplatform.com/feed/", "sectorial"),
    "dcd": ("Data Center Dynamics", "https://www.datacenterdynamics.com/en/rss/", "sectorial"),
    "servethehome": ("ServeTheHome", "https://www.servethehome.com/feed/", "sectorial"),
    "theregister": ("The Register", "https://www.theregister.com/headlines.atom", "sectorial"),
    "adexchanger": ("AdExchanger", "https://www.adexchanger.com/feed/", "sectorial"),
    "digiday": ("Digiday", "https://digiday.com/feed/", "sectorial"),
    "marketingdive": ("Marketing Dive", "https://www.marketingdive.com/feeds/news/", "sectorial"),
    "techcrunch": ("TechCrunch", "https://techcrunch.com/feed/", "sectorial"),
    "ciodive": ("CIO Dive", "https://www.ciodive.com/feeds/news/", "sectorial"),
    "ogj": ("Oil & Gas Journal", ["https://www.ogj.com/__rss/website-scheduled-content.xml?input=%7B%22sectionAlias%22%3A%22general-interest%22%7D",
                                  "https://feeds.feedburner.com/OilGasJournal-GeneralInterest"], "sectorial"),
    "rigzone": ("Rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx", "sectorial"),
    "fooddive": ("Food Dive", "https://www.fooddive.com/feeds/news/", "sectorial"),
    "retaildive": ("Retail Dive", "https://www.retaildive.com/feeds/news/", "sectorial"),
    "supplychaindive": ("Supply Chain Dive", "https://www.supplychaindive.com/feeds/news/", "sectorial"),
    "biopharmadive": ("BioPharma Dive", "https://www.biopharmadive.com/feeds/news/", "sectorial"),
    "fiercebiotech": ("Fierce Biotech", "https://www.fiercebiotech.com/rss/xml", "sectorial"),
    "businesswire": ("Business Wire", "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFtRWQ==", "nota_prensa"),
    "prnewswire": ("PR Newswire", "https://www.prnewswire.com/rss/news-releases-list.rss", "nota_prensa"),
}
AGENCIAS = ["businesswire", "prnewswire"]   # a todas las compañías (GlobeNewswire bloquea a los robots: 403)

# Medios sectoriales por código SIC de la SEC (para las compañías nuevas; se editan en companies.json)
SIC_MEDIOS = [
    (("4911", "4931", "4991", "4932", "4924"), ["utilitydive", "wnn"]),
    (("1311", "1381", "1382", "2911", "2990", "4922", "4923"), ["ogj", "rigzone"]),
    (("3674", "3672", "3576", "3577", "3572"), ["nextplatform", "dcd", "servethehome", "theregister"]),
    (("7370", "7371", "7372", "7373", "7374", "7379"), ["techcrunch", "ciodive", "theregister"]),
    (("7311", "7319"), ["adexchanger", "digiday", "marketingdive"]),
    (("2000", "2011", "2020", "2030", "2040", "2050", "2060", "2070", "2080", "2086", "2090"), ["fooddive"]),
    (("5311", "5331", "5399", "5411", "5900", "5961", "5990"), ["retaildive", "supplychaindive"]),
    (("4210", "4213", "4512", "4513", "4731"), ["supplychaindive"]),
    (("2833", "2834", "2835", "2836", "8731"), ["biopharmadive", "fiercebiotech"]),
]


def medios_por_sic(sic) -> list:
    s = str(sic or "")
    for codes, medios in SIC_MEDIOS:
        if s in codes:
            return list(medios)
    for codes, medios in SIC_MEDIOS:                      # mismo grupo de tres cifras
        if any(s[:3] == c[:3] for c in codes):
            return list(medios)
    return []


# ---------------------------------------------------------------- utilidades
def _http_get(url, timeout=20, opener=None, reintentos=2, sleep=time.sleep):
    """GET con reintento ante errores temporales del servidor (5xx) o de red."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, */*"})
    for i in range(reintentos + 1):
        try:
            with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
                return r.read(3_000_000)
        except urllib.error.HTTPError as e:
            if e.code < 500 or i == reintentos:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == reintentos:
                raise
        sleep(4 * (i + 1))


def _clean(txt, n=280):
    txt = re.sub(r"<[^>]+>", " ", txt or "")
    txt = re.sub(r"&[a-z#0-9]+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:n]


def _fecha(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def clave_titular(t):
    """Para detectar la misma noticia en dos medios."""
    t = re.sub(r"[^a-z0-9 ]", "", (t or "").lower())
    t = re.sub(r"\b(the|a|an|to|of|in|on|for|and|its|inc|corp)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:70]


def parse_feed(raw: bytes) -> list:
    """RSS 2.0 o Atom → [{titular, url, fecha, resumen}]."""
    root = ET.fromstring(raw)
    out = []
    tag = lambda e: e.tag.rsplit("}", 1)[-1]
    for it in root.iter():
        if tag(it) not in ("item", "entry"):
            continue
        d = {tag(c): c for c in it}
        title = (d.get("title").text if d.get("title") is not None else "") or ""
        link = ""
        for c in it:
            if tag(c) == "link":
                link = (c.get("href") or c.text or "").strip()
                if c.get("rel") in (None, "alternate"):
                    break
        when = next((d[k].text for k in ("pubDate", "published", "updated", "date") if d.get(k) is not None and d[k].text), "")
        desc = next((d[k].text for k in ("description", "summary", "content") if d.get(k) is not None and d[k].text), "")
        if title.strip() and link.startswith("http"):
            out.append({"titular": _clean(title, 300), "url": link, "fecha": _fecha(when), "resumen": _clean(desc)})
    return out


def patron(company, con_ticker=False) -> re.Pattern:
    """Nombre de la compañía y alias, como palabra completa y respetando mayúsculas (evita «path», «amazon rainforest»…).
    Con con_ticker también vale el ticker («$PATH», «(NYSE: VST)»)."""
    nombre = re.sub(r",?\s+(Inc|Corp|Corporation|Holdings|Co|Ltd|plc)\.?$", "", company.get("nombre") or "").strip()
    alias = [a for a in [nombre, *(company.get("alias") or []), *([company.get("ticker")] if con_ticker else [])] if a and len(a) >= 3]
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in alias) + r")(?![\w-])")


# ---------------------------------------------------------------- feeds RSS
class FeedCache:
    """Descarga cada feed una sola vez por ejecución y anota su estado."""

    def __init__(self, opener=None, sleep=time.sleep):
        self._open, self._sleep, self.items, self.estado = opener, sleep, {}, {}

    def get(self, fid):
        if fid in self.items:
            return self.items[fid]
        nombre, urls, tipo = FEEDS[fid]
        urls = [urls] if isinstance(urls, str) else list(urls)
        items, err, url = [], None, urls[0]
        for url in urls:                      # direcciones alternativas: vale la primera que dé un feed
            try:
                items = parse_feed(_http_get(url, opener=self._open, sleep=self._sleep))
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:120]}"
        self.items[fid] = items
        self.estado[fid] = {"medio": nombre, "url": url, "tipo": tipo, "ok": err is None,
                            "titulares": len(items), "error": err}
        return items


def from_feeds(company, cache: FeedCache) -> list:
    pat = patron(company)
    out = []
    medios = [m for m in (company.get("medios") or []) if m in FEEDS]
    for fid in dict.fromkeys(medios + AGENCIAS):
        nombre, _, tipo = FEEDS[fid]
        for n in cache.get(fid):
            # agencias: el nombre en el titular (si no, cualquier nota que lo cite de pasada)
            texto = n["titular"] if tipo == "nota_prensa" else n["titular"] + " " + n["resumen"]
            if pat.search(texto):
                out.append(dict(n, medio=nombre, tipo=tipo, via="RSS del medio"))
    return out


# ---------------------------------------------------------------- APIs
MEDIOS_DOMINIO = {"benzinga.com": "Benzinga", "fool.com": "Motley Fool", "zacks.com": "Zacks", "cnbc.com": "CNBC",
                  "finance.yahoo.com": "Yahoo Finance", "seekingalpha.com": "Seeking Alpha", "marketwatch.com": "MarketWatch",
                  "investing.com": "Investing.com", "barrons.com": "Barron's", "reuters.com": "Reuters", "forbes.com": "Forbes",
                  "businessinsider.com": "Business Insider", "nasdaq.com": "Nasdaq", "investors.com": "Investor's Business Daily",
                  "thestreet.com": "TheStreet", "techcrunch.com": "TechCrunch", "theverge.com": "The Verge",
                  "bloomberg.com": "Bloomberg", "ft.com": "Financial Times", "wsj.com": "WSJ", "economist.com": "The Economist",
                  "nytimes.com": "The New York Times", "theinformation.com": "The Information", "apnews.com": "AP"}


def _medio_dominio(dom):
    dom = (dom or "").lower().removeprefix("www.")
    return MEDIOS_DOMINIO.get(dom) or dom


class Marketaux:
    """https://www.marketaux.com/documentation · plan gratuito: 100 consultas/día y pocos artículos por consulta."""
    nombre = "Marketaux"
    URL = "https://api.marketaux.com/v1/news/all"

    def __init__(self, key, opener=None, por_consulta=3):
        self.key, self._open, self.n = key, opener, por_consulta

    def news(self, ticker, today=None, days=VENTANA_DIAS):
        today = today or date.today()
        q = {"symbols": ticker, "filter_entities": "true", "must_have_entities": "true", "language": "en",
             "published_after": (today - timedelta(days=days)).isoformat(), "limit": self.n, "api_token": self.key}
        j = json.loads(_http_get(f"{self.URL}?{urllib.parse.urlencode(q)}", opener=self._open))
        if j.get("error"):
            raise RuntimeError((j["error"] or {}).get("message") or "error de Marketaux")
        out = []
        for a in j.get("data") or []:
            ent = next((e for e in a.get("entities") or [] if (e.get("symbol") or "").upper() == ticker.upper()), {})
            out.append({"titular": _clean(a.get("title"), 300), "url": a.get("url"), "fecha": _fecha(a.get("published_at")),
                        "resumen": _clean(a.get("description") or a.get("snippet")), "medio": _medio_dominio(a.get("source")),
                        "tipo": "prensa", "via": "Marketaux",
                        **({"sentimiento": _sent(ent.get("sentiment_score"))} if ent.get("sentiment_score") is not None else {})})
        return [n for n in out if n["titular"] and n["url"]]


class AlphaVantage:
    """https://www.alphavantage.co/documentation/#news-sentiment · plan gratuito: 25 consultas al día."""
    nombre = "Alpha Vantage"
    URL = "https://www.alphavantage.co/query"

    def __init__(self, key, opener=None, min_relevancia=0.25, min_intervalo=1.5, sleep=time.sleep):
        self.key, self._open, self.min_rel = key, opener, min_relevancia
        self.min_intervalo, self._sleep, self._ultima = min_intervalo, sleep, 0.0

    def news(self, ticker, today=None, days=VENTANA_DIAS):
        espera = self.min_intervalo - (time.monotonic() - self._ultima)
        if espera > 0:
            self._sleep(espera)
        self._ultima = time.monotonic()
        today = today or date.today()
        q = {"function": "NEWS_SENTIMENT", "tickers": ticker, "sort": "LATEST", "limit": 50,
             "time_from": (today - timedelta(days=days)).strftime("%Y%m%dT0000"), "apikey": self.key}
        j = json.loads(_http_get(f"{self.URL}?{urllib.parse.urlencode(q)}", opener=self._open))
        if "feed" not in j:
            raise RuntimeError(_clean(j.get("Information") or j.get("Note") or j.get("Error Message") or "respuesta sin noticias", 160))
        out = []
        for a in j["feed"]:
            ts = next((t for t in a.get("ticker_sentiment") or [] if (t.get("ticker") or "").upper() == ticker.upper()), None)
            if not ts or float(ts.get("relevance_score") or 0) < self.min_rel:
                continue
            out.append({"titular": _clean(a.get("title"), 300), "url": a.get("url"), "fecha": _fecha(a.get("time_published")),
                        "resumen": _clean(a.get("summary")), "medio": a.get("source") or _medio_dominio(a.get("source_domain")),
                        "tipo": "prensa", "via": "Alpha Vantage", "sentimiento": _sent(ts.get("ticker_sentiment_score"))})
        return [n for n in out if n["titular"] and n["url"]]


class GoogleNews:
    """RSS de búsqueda de Google News, limitado a medios de referencia con «site:».
    Una consulta en inglés (prensa financiera internacional) y otra en español por compañía."""
    nombre = "Google News"
    URL = "https://news.google.com/rss/search"
    SITIOS_EN = ["reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com", "marketwatch.com",
                 "barrons.com", "theinformation.com", "apnews.com", "axios.com", "nytimes.com", "economist.com"]
    SITIOS_ES = ["expansion.com", "cincodias.elpais.com", "eleconomista.es", "elconfidencial.com", "lavanguardia.com", "elmundo.es"]

    def __init__(self, opener=None, dias=7, sleep=time.sleep, pausa=1.0):
        self._open, self.dias, self._sleep, self.pausa = opener, dias, sleep, pausa

    def _consulta(self, nombre, sitios, hl, gl, ceid):
        q = f'"{nombre}" (' + " OR ".join(f"site:{s}" for s in sitios) + f") when:{self.dias}d"
        url = f"{self.URL}?{urllib.parse.urlencode({'q': q, 'hl': hl, 'gl': gl, 'ceid': ceid})}"
        root = ET.fromstring(_http_get(url, opener=self._open, sleep=self._sleep))
        out = []
        for it in root.iter("item"):
            titulo = (it.findtext("title") or "").strip()
            fuente = it.find("source")
            medio = (fuente.text or "").strip() if fuente is not None else ""
            if medio and titulo.endswith(" - " + medio):
                titulo = titulo[: -len(medio) - 3].strip()
            dom = urllib.parse.urlparse(fuente.get("url") if fuente is not None else "").netloc
            out.append({"titular": _clean(titulo, 300), "url": (it.findtext("link") or "").strip(),
                        "fecha": _fecha(it.findtext("pubDate") or ""), "resumen": "",
                        "medio": MEDIOS_DOMINIO.get(dom.lower().removeprefix("www."), medio or _medio_dominio(dom)),
                        "tipo": "prensa", "via": "Google News"})
        return [n for n in out if n["titular"] and n["url"].startswith("http")]

    def news_company(self, company):
        nombre = re.sub(r",?\s+(Inc|Corp|Corporation|Holdings|Co|Ltd|plc)\.?$", "", company.get("nombre") or "").strip()
        out = self._consulta(nombre, self.SITIOS_EN, "en-US", "US", "US:en")
        self._sleep(self.pausa)
        try:
            out += self._consulta(nombre, self.SITIOS_ES, "es", "ES", "ES:es")
        except Exception:  # noqa: BLE001  la consulta en español es secundaria
            pass
        self._sleep(self.pausa)
        return out


class SeekingAlpha:
    """RSS público por ticker de Seeking Alpha (titulares de noticias y análisis; el texto es de pago)."""
    nombre = "Seeking Alpha"
    URL = "https://seekingalpha.com/api/sa/combined/{t}.xml"

    def __init__(self, opener=None, sleep=time.sleep, pausa=1.0):
        self._open, self._sleep, self.pausa = opener, sleep, pausa

    def news(self, ticker):
        items = parse_feed(_http_get(self.URL.format(t=urllib.parse.quote(ticker)), opener=self._open, sleep=self._sleep))
        self._sleep(self.pausa)
        return [dict(n, medio="Seeking Alpha", tipo="prensa", via="RSS de Seeking Alpha") for n in items]


def stocktwits(ticker, opener=None, sleep=time.sleep) -> dict:
    """Pulso de StockTwits: de los últimos mensajes (hasta 30), cuántos se etiquetan alcistas o bajistas."""
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{urllib.parse.quote(ticker)}.json"
    j = json.loads(_http_get(url, opener=opener, sleep=sleep))
    msgs = j.get("messages") or []
    etiq = [((m.get("entities") or {}).get("sentiment") or {}).get("basic") for m in msgs]
    alc, baj = etiq.count("Bullish"), etiq.count("Bearish")
    fechas = sorted(_fecha(m.get("created_at")) for m in msgs if m.get("created_at"))
    return {"fuente": "StockTwits (API pública)", "url": f"https://stocktwits.com/symbol/{ticker}",
            "mensajes": len(msgs), "alcistas": alc, "bajistas": baj,
            "pct_alcista": round(alc / (alc + baj) * 100) if alc + baj else None,
            "seguidores": (j.get("symbol") or {}).get("watchlist_count"),
            "desde": fechas[0] if fechas else None, "hasta": fechas[-1] if fechas else None,
            "fecha": date.today().isoformat()}


def _sent(score):
    """Escala de Alpha Vantage (−1 a 1; ±0,15 neutral, ±0,35 claro), también válida para Marketaux."""
    try:
        s = round(float(score), 3)
    except (TypeError, ValueError):
        return None
    lab = ("Bajista" if s <= -0.35 else "Algo bajista" if s <= -0.15 else "Neutral" if s < 0.15
           else "Algo alcista" if s < 0.35 else "Alcista")
    return {"puntuacion": s, "etiqueta": lab}


# Estado del proceso (lo prepara main.run): APIs configuradas y caché de feeds de esta ejecución
APIS: list = []
FEEDS_CACHE = None


REDES = False      # StockTwits (lo activa main.run en la ejecución real)


def apis_from_env():
    out = [GoogleNews(), SeekingAlpha()]
    if os.environ.get("MARKETAUX_API_KEY", "").strip():
        out.append(Marketaux(os.environ["MARKETAUX_API_KEY"].strip()))
    # Alpha Vantage pasó NEWS_SENTIMENT a sus planes de pago (comprobado el 5-nov-2026). Solo se usa
    # si se activa a propósito con ALPHAVANTAGE_NOTICIAS=1 (por ejemplo, con una suscripción).
    if os.environ.get("ALPHAVANTAGE_API_KEY", "").strip() and os.environ.get("ALPHAVANTAGE_NOTICIAS", "") == "1":
        out.append(AlphaVantage(os.environ["ALPHAVANTAGE_API_KEY"].strip()))
    return out


# ---------------------------------------------------------------- mezcla
TOPE_MEDIO = {"Yahoo Finance": 6}
TOPE_DURO = {"Yahoo Finance": 12}     # ni siquiera rellenando, si faltan otros medios
NOMBRES_ANTIGUOS = {"Yahoo": "Yahoo Finance", "SeekingAlpha": "Seeking Alpha"}
TOPE_OTRO = 6
TOPE_OFICIAL = 6


# Avisos repetidos de bufetes que buscan demandantes («class action», «deadline alert»…): llegan
# decenas por compañía y tapan las noticias. Se deja solo el más reciente.
RUIDO_BUFETES = re.compile(r"class action|deadline alert|investors? (with|who) (substantial )?loss|law firm|"
                           r"securities fraud|shareholder alert|investor alert|lead plaintiff|rosen law|pomerantz|"
                           r"bragar eagel|levi & korsinsky|glancy|faruqi|bronstein|kessler topaz|robbins geller", re.I)


def combinar(fuentes: list, previas: list | None = None, today=None, limite=LIMITE, dias=VENTANA_DIAS) -> list:
    """Une todas las fuentes y lo de noches anteriores: quita duplicados (misma URL o titular),
    descarta lo antiguo, limita cada medio para que haya variedad y deja como mucho `limite`."""
    today = today or date.today()
    desde = (today - timedelta(days=dias)).isoformat()
    todas = [n for lote in fuentes for n in lote] + [n for n in (previas or []) if not n.get("oficial")]
    for n in todas:                                     # nombres antiguos de Finnhub guardados en noches anteriores
        n["medio"] = NOMBRES_ANTIGUOS.get(n.get("medio") or "", n.get("medio") or "")
    # prioridad ante duplicados: oficial > nota de prensa > sectorial > con sentimiento > resto; Yahoo al final
    rango = lambda n: (not n.get("oficial"), n.get("tipo") != "nota_prensa", n.get("tipo") != "sectorial",
                       not n.get("sentimiento"), n.get("medio") == "Yahoo Finance")
    vistos_u, vistos_t, unicas = set(), set(), []
    for n in sorted(todas, key=rango):
        if not n.get("titular") or not n.get("url") or (n.get("fecha") or "9999") < desde:
            continue
        u, t = n["url"].split("#")[0].rstrip("/"), clave_titular(n["titular"])
        if u in vistos_u or t in vistos_t:
            continue
        vistos_u.add(u); vistos_t.add(t)
        n.setdefault("tipo", "prensa")
        unicas.append(n)
    unicas.sort(key=lambda n: n.get("fecha") or "", reverse=True)
    bufete = False
    filtradas = []
    for n in unicas:
        if not n.get("oficial") and RUIDO_BUFETES.search(n["titular"]):
            if bufete:
                continue
            bufete = True
        filtradas.append(n)
    unicas = filtradas
    out, cnt, oficiales = [], {}, 0
    for n in unicas:                                    # 1.ª pasada: topes por medio
        if n.get("oficial"):
            if oficiales < TOPE_OFICIAL:
                out.append(n); oficiales += 1
            continue
        if cnt.get(n["medio"], 0) < TOPE_MEDIO.get(n["medio"], TOPE_OTRO):
            out.append(n); cnt[n["medio"]] = cnt.get(n["medio"], 0) + 1
    if len(out) < limite:                               # 2.ª: rellena si no hay variedad suficiente
        ya = {id(n) for n in out}
        for n in unicas:                                # sin pasar el tope duro (Yahoo 15)
            if len(out) >= limite:
                break
            if id(n) in ya or n.get("oficial") or cnt.get(n["medio"], 0) >= TOPE_DURO.get(n["medio"], 99):
                continue
            out.append(n); cnt[n["medio"]] = cnt.get(n["medio"], 0) + 1
    out = sorted(out, key=lambda n: n.get("fecha") or "", reverse=True)
    if len(out) > limite:                               # recorta las más antiguas sin perder los 8-K
        keep, borrar = [], len(out) - limite
        for n in reversed(out):
            if borrar and not n.get("oficial"):
                borrar -= 1
                continue
            keep.append(n)
        out = list(reversed(keep))
    return out


def resumen_sentimiento(noticias):
    s = [n["sentimiento"]["puntuacion"] for n in noticias if (n.get("sentimiento") or {}).get("puntuacion") is not None]
    if len(s) < 3:
        return None
    m = sum(s) / len(s)
    return dict(_sent(m), noticias=len(s), fuente="Alpha Vantage / Marketaux (puntuación media de las noticias del último mes)")
