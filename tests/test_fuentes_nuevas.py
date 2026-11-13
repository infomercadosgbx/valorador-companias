"""Sala de prensa de la compañía, enlaces reales de Finnhub, otras presentaciones a la SEC y señales nuevas."""
import json
import sys
from datetime import date
from pathlib import Path

from fetcher import filings as F
from fetcher import news as N

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import senales as S  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>We Are Testing Ad Placements in Reddit Search Pages</title><link>https://redditinc.com/news/search-ads</link>
<pubDate>Tue, 03 Nov 2026 15:00:00 GMT</pubDate><description>Initial test</description></item>
</channel></rss>"""
PAGINA = b'<html><head><link rel="alternate" type="application/rss+xml" href="/blog/rss.xml"></head><body>x</body></html>'


class R:
    def __init__(self, body, headers=None, url=None):
        self.body, self.headers, self._url = body, headers or {}, url

    def read(self, n=-1):
        return self.body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_sala_por_feed_y_por_pagina():
    paginas = {"https://redditinc.com/news": PAGINA, "https://redditinc.com/blog/rss.xml": RSS}

    def opener(req, timeout=0):
        if req.full_url not in paginas:
            raise OSError("404")
        return R(paginas[req.full_url])

    items, url, err = N.leer_sala(["https://no.existe/rss", "https://redditinc.com/news"], opener=opener, sleep=lambda s: None)
    assert err is None and url == "https://redditinc.com/blog/rss.xml"
    assert items[0]["titular"].startswith("We Are Testing Ad Placements") and items[0]["fecha"] == "2026-11-03"

    cache = N.FeedCache(opener=opener, sleep=lambda s: None)
    out = N.from_newsroom({"ticker": "RDDT", "nombre": "Reddit", "newsroom": ["https://redditinc.com/news"]}, cache)
    assert out[0]["tipo"] == "nota_prensa" and out[0]["via"] == "Sala de prensa de la compañía"
    assert cache.estado["sala:RDDT"]["ok"] is True


def test_resolver_finnhub_y_reutilizar():
    u = "https://finnhub.io/api/news?id=abc"
    nots = [{"titular": "x", "url": u}, {"titular": "y", "url": "https://otro.com/a"}]
    abrir = lambda req, timeout=0: R(b"", headers={"Location": "https://www.benzinga.com/articulo"})
    assert N.resolver_finnhub(nots, opener=abrir) == 1
    assert nots[0]["url"] == "https://www.benzinga.com/articulo" and nots[0]["url_finnhub"] == u
    nuevas = [{"titular": "x", "url": u}]
    falla = lambda req, timeout=0: (_ for _ in ()).throw(AssertionError("no debe pedir"))
    assert N.resolver_finnhub(nuevas, previas=nots, opener=falla) == 0
    assert nuevas[0]["url"] == "https://www.benzinga.com/articulo"


def test_otras_presentaciones_sec():
    subs = {"filings": {"recent": {
        "accessionNumber": ["0002164682-26-000007", "0001950047-26-010772", "0001713445-26-000116", "0000093751-26-000713"],
        "filingDate": ["2026-11-10", "2026-11-06", "2026-10-30", "2026-11-10"],
        "reportDate": ["2026-10-28", "", "2026-09-30", ""],
        "form": ["3", "144", "10-Q", "SC 13D"],
        "primaryDocument": ["f3.xml", "p.xml", "q.htm", "d.xml"], "items": ["", "", "", ""]}}}
    out = F.recent_other_filings("0001713445", subs, today=date(2026, 11, 13))
    assert [o["formulario"] for o in out] == ["3", "SC 13D"]
    assert out[0]["url_indice"].endswith("0002164682-26-000007-index.htm")


def test_senales_nuevas():
    data = {"noticias": [
        {"titular": "We Are Testing Ad Placements", "fecha": "2026-11-03", "tipo": "nota_prensa", "via": S.VIA_SALA},
        {"titular": "Guggenheim Maintains Buy on Reddit, Lowers Price Target to $140", "fecha": "2026-11-10"}],
        "presentaciones_sec": [{"formulario": "3", "descripcion": "alta de un directivo o consejero (formulario 3)",
                                "fecha_presentacion": "2026-11-10"}]}
    s = S.senales("RDDT", data, date(2026, 11, 1), date(2026, 11, 13))
    assert any("sala de prensa" in x for x in s) and any(x.startswith("SEC: 3") for x in s)
    assert not any("nota(s) de prensa" in x for x in s)          # la sala no cuenta dos veces
    assert len(S.objetivos(data, date(2026, 11, 1))) == 1
    # blog con muchas entradas: solo las materiales
    blog = {"noticias": [{"titular": f"Tips {i}", "fecha": "2026-11-05", "via": S.VIA_SALA, "tipo": "nota_prensa"} for i in range(6)]}
    assert S.senales("GOOGL", blog, date(2026, 11, 1), date(2026, 11, 13)) == []
