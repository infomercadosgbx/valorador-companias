import json
from datetime import date

from fetcher import lecturas as L

IXBRL = """<html><body><ix:header><ix:hidden>dei:DocumentType 10-Q 123456</ix:hidden></ix:header>
<div style="display:none">oculto</div><p>Item 2. Management&#8217;s Discussion</p>
<table><tr><td>Revenue</td><td>895</td></tr></table><script>var x=1</script></body></html>"""

WEB = """<html><head><title>Reddit Inc</title><style>.a{}</style></head><body>
<h1>Products</h1><p>Reddit Pro for businesses.</p>
<a href="/blog/reddit-answers">Reddit Answers launches</a>
<a href="https://investor.redditinc.com/news">Investors</a>
<a href="https://twitter.com/reddit">X</a><a href="#top">Top</a></body></html>"""


def test_html_a_texto_quita_xbrl_oculto_y_scripts():
    t = L.html_a_texto(IXBRL)
    assert "Management’s Discussion" in t and "Revenue" in t and "895" in t
    assert "DocumentType" not in t and "oculto" not in t and "var x" not in t


def test_enlaces_solo_mismo_dominio():
    ls = L.enlaces(WEB, "https://redditinc.com/")
    us = [x["u"] for x in ls]
    assert "https://redditinc.com/blog/reddit-answers" in us
    assert "https://investor.redditinc.com/news" in us
    assert not any("twitter" in u for u in us)


def _repo(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "companies.json").write_text(json.dumps({"companies": [
        {"ticker": "RDDT", "webs_oficiales": [{"t": "Blog", "u": "https://redditinc.com/blog"},
                                              {"t": "IR", "u": "https://investor.redditinc.com"}]},
        {"ticker": "CVX", "archivada": {"desde": "2026-11-13"}}]}), encoding="utf-8")
    d = {"ultimo_8k_resultados": {"accn": "0001-26-000114", "url_ex99_1": "https://www.sec.gov/a/ex991.htm",
                                  "fecha_presentacion": "2026-10-29"},
         "ultimo_informe": {"accn": "0001-26-000116", "formulario": "10-Q", "url_documento": "https://www.sec.gov/a/q.htm",
                            "fecha_presentacion": "2026-10-30"},
         "noticias": [{"medio": "SEC · 8-K (oficial)", "fecha": "2026-11-16", "titular": "8-K: acuerdo",
                       "url": "https://www.sec.gov/Archives/edgar/data/1/000168285226000208/x.htm"},
                      {"medio": "SEC · 8-K (oficial)", "fecha": "2026-09-01", "titular": "viejo",
                       "url": "https://www.sec.gov/Archives/edgar/data/1/000168285226000100/y.htm"}],
         "presentaciones_sec": [{"formulario": "424B2", "fecha_presentacion": "2026-11-17", "accn": "0002-26-1",
                                 "url_documento": "https://www.sec.gov/a/p.htm", "descripcion": "folleto"}]}
    (tmp_path / "data" / "RDDT.json").write_text(json.dumps(d), encoding="utf-8")
    return tmp_path


class FakeSec:
    def __init__(self):
        self.urls = []

    def get_bytes(self, u):
        self.urls.append(u)
        return IXBRL.encode()


def test_actualizar_copia_sec_y_webs(tmp_path):
    root = _repo(tmp_path)
    sec = FakeSec()

    def web(u):
        return (200, WEB) if "blog" in u else (403, "")

    est = L.actualizar(root, sec=sec, web_get=web, hoy=date(2026, 11, 19), log=lambda *_: None)
    carpeta = root / "lecturas" / "RDDT"
    nombres = sorted(p.name for p in carpeta.iterdir())
    assert "sec_nota_resultados_0001-26-000114.txt" in nombres
    assert "sec_10-q_0001-26-000116.txt" not in nombres and "sec_10q_0001-26-000116.txt" in nombres
    assert "sec_8k_0001682852-26-000208.txt" in nombres          # dentro de la ventana
    assert not any("000100" in n for n in nombres)                # fuera de la ventana
    assert "sec_424b2_0002-26-1.txt" in nombres
    assert len(sec.urls) == 4
    assert not (root / "lecturas" / "CVX").exists()               # archivada: no se toca
    web_est = est["RDDT"]["web"]
    assert web_est["https://redditinc.com/blog"]["ok"] and web_est["https://redditinc.com/blog"]["enlaces"] == 2
    assert web_est["https://investor.redditinc.com"] == {**web_est["https://investor.redditinc.com"], "ok": False, "error": "HTTP 403"}
    txt = (carpeta / "web_redditinc-com-blog.txt").read_text(encoding="utf-8")
    assert "Reddit Pro" in txt and "Reddit Answers launches" in txt
    # Segunda pasada: no vuelve a descargar la SEC y la web sin cambios no se reescribe.
    sec2 = FakeSec()
    est2 = L.actualizar(root, sec=sec2, web_get=web, hoy=date(2026, 11, 19), log=lambda *_: None)
    assert sec2.urls == []
    assert est2["RDDT"]["web"]["https://redditinc.com/blog"]["cambio"] is False
    assert json.loads((root / "lecturas" / "_estado.json").read_text(encoding="utf-8"))["RDDT"]["sec"][0]["ok"]


def test_borra_documentos_que_dejan_de_ser_los_ultimos(tmp_path):
    root = _repo(tmp_path)
    L.actualizar(root, sec=FakeSec(), web_get=lambda u: (200, WEB), hoy=date(2026, 11, 19), log=lambda *_: None)
    d = json.loads((root / "data" / "RDDT.json").read_text())
    d["ultimo_informe"]["accn"] = "0001-27-000010"
    (root / "data" / "RDDT.json").write_text(json.dumps(d))
    L.actualizar(root, sec=FakeSec(), web_get=lambda u: (200, WEB), hoy=date(2026, 11, 19), log=lambda *_: None)
    nombres = {p.name for p in (root / "lecturas" / "RDDT").iterdir()}
    assert "sec_10q_0001-27-000010.txt" in nombres and "sec_10q_0001-26-000116.txt" not in nombres
