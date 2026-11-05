"""Noticias: mezcla de fuentes, topes por medio, feeds RSS, APIs y 8-K."""
import json
from datetime import date

from fetcher import filings as F
from fetcher import news as N
from fetcher.prices import FinnhubProvider
from fetcher.news import FeedCache   # el original (conftest lo sustituye en el resto de tests)

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
    assert sum(x["medio"] == "Yahoo Finance" for x in out) <= 10       # tope a Yahoo
    assert sum(x["medio"] == "Benzinga" for x in out) == 6              # tope al resto
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
