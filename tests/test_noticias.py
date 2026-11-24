"""Noticias: mezcla de fuentes, topes por medio, feeds RSS, APIs y 8-K."""
import json
from datetime import date

from fetcher import filings as F
from fetcher import news as N
from fetcher.prices import FinnhubProvider
from fetcher.news import FeedCache, stocktwits as stocktwits_real   # los originales (conftest lo sustituye en el resto de tests)

HOY = date(2026, 11, 5)


def n(t, medio, f="2026-11-01", **kw):
    return dict({"titular": t, "medio": medio, "url": f"https://x/{t}", "fecha": f, "resumen": ""}, **kw)


def test_finnhub_entrega_candidatos_con_medio_legible():
    p = FinnhubProvider.__new__(FinnhubProvider)
    p._get = lambda *a, **k: [{"headline": "H", "source": "Yahoo", "url": "u", "datetime": 1793000000}]
    out = p.news("X", today=HOY)
    assert out[0]["medio"] == "Yahoo Finance" and out[0]["via"] == "Finnhub"


def test_combinar_tope_por_medio_limite_30_y_8k():
    yahoo = [n(f"Yahoo story {i}", "Yahoo Finance") for i in range(40)]
    otros = [n(f"{m} story {i}", m) for m in ("Benzinga", "Zacks", "CNBC", "Motley Fool") for i in range(5)]
    otros += [n("Sector piece", "Utility Dive", tipo="sectorial")] + [n(f"Benzinga extra {i}", "Benzinga") for i in range(4)]
    oficial = [n("8-K a la SEC: Resultados", "SEC · 8-K (oficial)", oficial=True)]
    out = N.combinar([yahoo, otros, oficial], today=HOY)
    assert len(out) == 30
    assert sum(x["medio"] == "Yahoo Finance" for x in out) <= 12       # tope duro a Yahoo
    assert sum(x["medio"] == "Benzinga" for x in out) >= 6              # primero el tope; luego se rellena
    assert any(x.get("oficial") for x in out) and any(x["medio"] == "Utility Dive" for x in out)
    assert [x["fecha"] for x in out] == sorted([x["fecha"] for x in out], reverse=True)


def test_combinar_quita_duplicados_prefiere_medio_original_y_acumula():
    a = n("Vistra signs nuclear deal with Meta", "Yahoo Finance")
    b = n("Vistra Signs Nuclear Deal With Meta", "Utility Dive", tipo="sectorial")
    viejo = n("Old story", "Digiday", f="2026-09-01")
    previa = n("Story from last night feed", "World Nuclear News", f="2026-10-30", tipo="sectorial")
    out = N.combinar([[a, b]], previas=[viejo, previa], today=HOY)
    assert [x["medio"] for x in out] == ["Utility Dive", "World Nuclear News"]   # sin duplicado ni lo antiguo


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Vistra to buy gas plants</title><link>https://www.utilitydive.com/news/a</link><pubDate>Mon, 03 Nov 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Deal&lt;/p&gt;</description></item>
<item><title>Grid news</title><link>https://www.utilitydive.com/news/b</link><pubDate>Mon, 03 Nov 2026 10:00:00 GMT</pubDate><description>Mentions Vistra Corp. in passing</description></item>
<item><title>Unrelated</title><link>https://www.utilitydive.com/news/c</link><pubDate>Mon, 03 Nov 2026 10:00:00 GMT</pubDate><description>nothing</description></item>
</channel></rss>"""
ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Broadcom ships Tomahawk 6</title>
<link rel="alternate" href="https://www.theregister.com/x"/><updated>2026-11-04T08:00:00Z</updated><summary>chips</summary></entry></feed>"""
WIRE = b"""<rss><channel><item><title>Acme partners with Vistra</title><link>https://www.businesswire.com/1</link><pubDate>Tue, 04 Nov 2026 12:00:00 GMT</pubDate><description>x</description></item>
<item><title>Acme results</title><link>https://www.businesswire.com/2</link><pubDate>Tue, 04 Nov 2026 12:00:00 GMT</pubDate><description>Vistra mentioned in body only</description></item></channel></rss>"""


def test_feeds_rss_y_atom_filtran_por_nombre_y_alias():
    assert N.parse_feed(ATOM)[0] == {"titular": "Broadcom ships Tomahawk 6", "url": "https://www.theregister.com/x",
                                     "fecha": "2026-11-04", "resumen": "chips"}
    feeds = {N.FEEDS["utilitydive"][1]: RSS, **{N.FEEDS[a][1]: (WIRE if a == "businesswire" else b"<rss/>") for a in N.AGENCIAS}}

    class R:
        def __init__(self, b): self.b = b
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *_): return self.b
    cache = FeedCache(opener=lambda req, timeout=0: R(feeds[req.full_url]), sleep=lambda s: None)
    out = N.from_feeds({"nombre": "Vistra", "medios": ["utilitydive"]}, cache)
    tit = {x["titular"]: x for x in out}
    assert set(tit) == {"Vistra to buy gas plants", "Grid news", "Acme partners with Vistra"}   # en agencias, solo el titular cuenta
    assert tit["Acme partners with Vistra"]["tipo"] == "nota_prensa" and cache.estado["utilitydive"]["ok"]
    assert not N.patron({"nombre": "UiPath"}).search("a new path for automation")


def test_apis_marketaux_y_alpha_vantage_con_sentimiento():
    av = {"feed": [{"title": "Reddit beats", "url": "https://r/1", "time_published": "20261103T120000", "summary": "s",
                    "source": "Motley Fool", "ticker_sentiment": [{"ticker": "RDDT", "relevance_score": "0.8", "ticker_sentiment_score": "0.41"}]},
                   {"title": "Market wrap", "url": "https://r/2", "time_published": "20261103T120000", "summary": "s",
                    "source": "Benzinga", "ticker_sentiment": [{"ticker": "RDDT", "relevance_score": "0.05", "ticker_sentiment_score": "0.9"}]}]}
    mx = {"data": [{"title": "Reddit ads", "url": "https://m/1", "published_at": "2026-11-02T10:00:00.000000Z", "description": "d",
                    "source": "www.cnbc.com", "entities": [{"symbol": "RDDT", "sentiment_score": -0.2}]}]}

    class R:
        def __init__(self, b): self.b = json.dumps(b).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *_): return self.b
    a = N.AlphaVantage("k", opener=lambda req, timeout=0: R(av)).news("RDDT", today=HOY)
    assert len(a) == 1 and a[0]["sentimiento"]["etiqueta"] == "Alcista" and a[0]["fecha"] == "2026-11-03"
    m = N.Marketaux("k", opener=lambda req, timeout=0: R(mx)).news("RDDT", today=HOY)
    assert m[0]["medio"] == "CNBC" and m[0]["sentimiento"]["etiqueta"] == "Algo bajista"
    try:
        N.AlphaVantage("k", opener=lambda req, timeout=0: R({"Information": "limit reached"})).news("RDDT", today=HOY)
        assert False
    except RuntimeError as e:
        assert "limit" in str(e)
    assert N.resumen_sentimiento(a + m + a) is not None


def test_8k_oficiales_y_medios_por_sector():
    subs = {"filings": {"recent": {"accessionNumber": ["0001-26-1", "0001-26-2"], "filingDate": ["2026-10-20", "2026-01-01"],
            "reportDate": ["", ""], "form": ["8-K", "8-K"], "primaryDocument": ["a.htm", "b.htm"], "items": ["2.02,9.01", "5.02"]}}}
    of = F.recent_8k_news("123", subs, today=HOY)
    assert len(of) == 1 and of[0]["oficial"] and of[0]["titular"].endswith("Resultados")
    assert N.medios_por_sic("4911") == ["utilitydive", "wnn"] and "techcrunch" in N.medios_por_sic("7372")
    assert all(m in N.FEEDS for _, ms in N.SIC_MEDIOS for m in ms)


def test_patron_con_ticker_para_apis():
    p = N.patron({"nombre": "Vistra", "ticker": "VST"}, con_ticker=True)
    assert p.search("Shares of VST rallied") and not p.search("Wall Street Lunch: Fear Grips The Market")


def test_nombres_antiguos_cuentan_en_el_tope():
    previas = [n(f"Old yahoo {i}", "Yahoo") for i in range(15)]
    nuevas = [n(f"New yahoo {i}", "Yahoo Finance") for i in range(15)]
    out = N.combinar([nuevas, [n("Zacks piece", "Zacks")]], previas=previas, today=HOY, limite=11)
    assert {x["medio"] for x in out} == {"Yahoo Finance", "Zacks"} and sum(x["medio"] == "Yahoo Finance" for x in out) == 10


class _R:
    def __init__(self, b): self.b = b if isinstance(b, bytes) else json.dumps(b).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, *_): return self.b


GNEWS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Vistra signs data-center deal - Reuters</title><link>https://news.google.com/rss/articles/abc</link>
<pubDate>Wed, 12 Nov 2026 14:00:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>
<item><title>Vistra sube en bolsa - Expansi\xc3\xb3n</title><link>https://news.google.com/rss/articles/def</link>
<pubDate>Thu, 13 Nov 2026 08:00:00 GMT</pubDate><source url="https://www.expansion.com">Expansi\xc3\xb3n</source></item>
</channel></rss>"""


def test_google_news_limpia_el_medio_del_titular():
    urls = []
    g = N.GoogleNews(opener=lambda req, timeout=0: (urls.append(req.full_url), _R(GNEWS))[1], sleep=lambda s: None)
    out = g.news_company({"nombre": "Vistra Corp.", "ticker": "VST"})
    assert out[0] == {"titular": "Vistra signs data-center deal", "url": "https://news.google.com/rss/articles/abc",
                      "fecha": "2026-11-12", "resumen": "", "medio": "Reuters", "tipo": "prensa", "via": "Google News"}
    assert out[1]["medio"] == "Expansión"
    assert len(urls) == 2 and "site%3Areuters.com" in urls[0] and "hl=es" in urls[1] and "%22Vistra%22" in urls[0]


def test_stocktwits_cuenta_alcistas_y_bajistas():
    j = {"symbol": {"watchlist_count": 26037}, "messages": [
        {"created_at": "2026-11-13T08:00:00Z", "entities": {"sentiment": {"basic": "Bullish"}}},
        {"created_at": "2026-11-12T08:00:00Z", "entities": {"sentiment": {"basic": "Bullish"}}},
        {"created_at": "2026-11-12T07:00:00Z", "entities": {"sentiment": {"basic": "Bearish"}}},
        {"created_at": "2026-11-11T07:00:00Z", "entities": {"sentiment": None}}]}
    r = stocktwits_real("APP", opener=lambda req, timeout=0: _R(j), sleep=lambda s: None)
    assert (r["mensajes"], r["alcistas"], r["bajistas"], r["pct_alcista"], r["seguidores"]) == (4, 2, 1, 67, 26037)
    assert (r["desde"], r["hasta"]) == ("2026-11-11", "2026-11-13")


def test_avisos_de_bufetes_solo_el_mas_reciente():
    out = N.combinar([[n("Pomerantz Law Firm Announces Class Action Against AppLovin", "Morningstar", "2026-11-12"),
                       n("APP DEADLINE ALERT: AppLovin Investors with Substantial Losses", "Benzinga", "2026-11-11"),
                       n("AppLovin beats estimates", "Reuters", "2026-11-10")]], today=HOY.replace(day=13))
    assert [x["titular"] for x in out] == ["Pomerantz Law Firm Announces Class Action Against AppLovin", "AppLovin beats estimates"]


def test_reddit_pide_token_y_filtra_por_nombre():
    pedidos = []

    def opener(req, timeout=0):
        pedidos.append(req)
        if "access_token" in req.full_url:
            return _R({"access_token": "tok"})
        return _R({"data": {"children": [
            {"data": {"title": "AppLovin earnings thread", "subreddit": "stocks", "score": 120, "num_comments": 40,
                      "permalink": "/r/stocks/x", "created_utc": 1794787200}},
            {"data": {"title": "My app idea", "subreddit": "investing", "score": 5, "num_comments": 1,
                      "permalink": "/r/investing/y", "created_utc": 1794787200}}]}})
    r = N.Reddit("id", "sec", opener=opener, sleep=lambda s: None).pulso({"nombre": "AppLovin Corp", "ticker": "APP"})
    assert r["publicaciones_7d"] == 1 and r["comentarios_7d"] == 40 and r["foros"] == ["stocks"]
    assert r["destacadas"][0]["url"] == "https://www.reddit.com/r/stocks/x"
    assert pedidos[0].get_header("Authorization").startswith("Basic ") and pedidos[1].get_header("Authorization") == "bearer tok"


def test_429_reintenta_con_espera_y_pausa_entre_consultas_a_google_news():
    import io
    import urllib.error
    from fetcher import news as N
    N._ULTIMA_HOST.clear()
    esperas, llamadas = [], []

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=20):
        llamadas.append(req.full_url)
        if len(llamadas) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "30"}, None)
        return R(b"<rss/>")

    url = "https://news.google.com/rss/search?q=x"
    assert N._http_get(url, opener=opener, sleep=esperas.append) == b"<rss/>"
    assert len(llamadas) == 3
    assert 30 in esperas and 40 in esperas          # Retry-After y después 20 s × 2


def test_429_persistente_acaba_fallando():
    import urllib.error
    import pytest
    from fetcher import news as N

    def opener(req, timeout=20):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        N._http_get("https://example.com/feed", opener=opener, sleep=lambda s: None)


def test_google_news_bloqueado_no_se_vuelve_a_consultar_en_la_ejecucion():
    import urllib.error
    import pytest
    from fetcher import news as N
    N._CAIDOS.clear(); N._ULTIMA_HOST.clear()
    llamadas = []

    def opener(req, timeout=20):
        llamadas.append(1)
        raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        N._http_get("https://news.google.com/rss/search?q=a", opener=opener, sleep=lambda s: None)
    n = len(llamadas)
    with pytest.raises(urllib.error.HTTPError):
        N._http_get("https://news.google.com/rss/search?q=b", opener=opener, sleep=lambda s: None)
    assert len(llamadas) == n                      # la segunda ni siquiera llama
    N._CAIDOS.clear()


YAHOO = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Yahoo! Finance: VST News</title>
<item><title>Vistra signs new nuclear power deal</title><link>https://finance.yahoo.com/news/vistra-deal-1.html</link>
<pubDate>Mon, 23 Nov 2026 14:00:00 +0000</pubDate><description>Vistra agreed...</description></item></channel></rss>"""

CNBC = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Market Insider</title>
<item><title>Vistra shares jump after data center contract</title><link>https://www.cnbc.com/2026/11/23/vistra.html</link>
<pubDate>Mon, 23 Nov 2026 15:00:00 GMT</pubDate><description>Shares rose.</description></item>
<item><title>Stocks close higher as tech rallies</title><link>https://www.cnbc.com/2026/11/23/markets.html</link>
<pubDate>Mon, 23 Nov 2026 21:00:00 GMT</pubDate><description>Indexes.</description></item></channel></rss>"""


class _RB:
    def __init__(self, b):
        self.b = b

    def read(self, n=-1):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_yahoo_finance_por_ticker():
    from fetcher import news as N
    urls = []
    y = N.YahooFinance(opener=lambda req, timeout=0: (urls.append(req.full_url), _RB(YAHOO))[1], sleep=lambda s: None)
    r = y.news("VST")
    assert "s=VST" in urls[0] and r[0]["medio"] == "Yahoo Finance" and r[0]["via"] == "RSS de Yahoo Finance"
    assert r[0]["titular"].startswith("Vistra signs")


def test_prensa_financiera_por_rss_se_filtra_por_nombre():
    from fetcher import news as N
    cnbc = N.FEEDS["cnbc_mercados"][1]
    cache = FeedCache(opener=lambda req, timeout=0: _RB(CNBC if req.full_url == cnbc else b"<rss/>"), sleep=lambda s: None)
    out = N.from_feeds({"ticker": "VST", "nombre": "Vistra Corp."}, cache)
    assert [n["titular"] for n in out] == ["Vistra shares jump after data center contract"]
    assert out[0]["medio"] == "CNBC" and out[0]["tipo"] == "prensa"
    assert "yahoo" not in " ".join(N.PRENSA)                       # Yahoo va por ticker, no como feed general


def test_google_news_pasa_por_el_worker_y_si_falla_vuelve_a_lo_directo(monkeypatch):
    import urllib.error
    from fetcher import news as N
    N._CAIDOS.clear(); N._ULTIMA_HOST.clear()
    monkeypatch.setattr(N, "PUENTE_GOOGLE", "https://w.workers.dev/noticias")
    monkeypatch.setattr(N, "ESTADO_PUENTE", {"usado": 0, "fallos": 0, "error": None})
    pedidas, puente_ok = [], [True]

    def opener(req, timeout=20):
        pedidas.append(req.full_url)
        if req.full_url.startswith("https://w.workers.dev/") and not puente_ok[0]:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return _RB(b"<rss/>")

    g = "https://news.google.com/rss/search?q=Vistra"
    assert N._http_get(g, opener=opener, sleep=lambda s: None) == b"<rss/>"
    assert pedidas == ["https://w.workers.dev/noticias?u=https%3A%2F%2Fnews.google.com%2Frss%2Fsearch%3Fq%3DVistra"]
    puente_ok[0] = False
    pedidas.clear()
    for _ in range(3):
        N._http_get(g, opener=opener, sleep=lambda s: None)
    assert pedidas.count(g) == 3                                  # siempre acaba en lo directo
    assert sum(p.startswith("https://w.workers.dev/") for p in pedidas) == 2   # tras dos fallos deja el Worker
    assert N.ESTADO_PUENTE["usado"] == 1 and N.ESTADO_PUENTE["fallos"] == 2
    N._CAIDOS.clear()


def test_puente_desde_ajustes(tmp_path):
    from fetcher import news as N
    (tmp_path / "ajustes.json").write_text('{"precio_vivo_url": "https://x.workers.dev/"}')
    assert N.puente_desde_ajustes(tmp_path) is None                          # apagado si no se pide
    (tmp_path / "ajustes.json").write_text('{"precio_vivo_url": "https://x.workers.dev/", "puente_google_news": true}')
    assert N.puente_desde_ajustes(tmp_path) == "https://x.workers.dev/noticias"
    (tmp_path / "ajustes.json").write_text('{"precio_vivo_url": ""}')
    assert N.puente_desde_ajustes(tmp_path) is None
