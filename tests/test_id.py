"""I+D: etiqueta us-gaap y extensión propia de la compañía (Amazon)."""
from datetime import date

from fetcher import extract as X


def fact(start, end, val, filed, fy, fp, form="10-K", accn="0000000000-00-000001"):
    return {"start": start, "end": end, "val": val, "filed": filed, "fy": fy, "fp": fp, "form": form, "accn": accn}


def cf_with(taxonomy, tag):
    ann = [fact("2023-01-01", "2023-12-31", 80, "2024-02-01", 2023, "FY"),
           fact("2024-01-01", "2024-12-31", 100, "2025-02-01", 2024, "FY", accn="0000000000-00-000002")]
    return {"facts": {"us-gaap": {}, taxonomy: {tag: {"units": {"USD": ann}}}}}


def test_id_etiqueta_gaap():
    cf = cf_with("us-gaap", "ResearchAndDevelopmentExpense")
    r, _ = X.build_flow(cf, "0000000001", "investigacion_desarrollo", date(2024, 12, 31), "12-31")
    assert [p["valor"] for p in r["anual"]] == [80, 100]
    assert r["anual"][-1]["etiqueta"] == "us-gaap:ResearchAndDevelopmentExpense"


def test_id_extension_propia():
    cf = cf_with("amzn", "TechnologyAndInfrastructureExpense")
    r, _ = X.build_flow(cf, "0000000001", "investigacion_desarrollo", date(2024, 12, 31), "12-31")
    assert [p["valor"] for p in r["anual"]] == [80, 100]
    assert r["anual"][-1]["etiqueta"] == "amzn:TechnologyAndInfrastructureExpense"


def test_id_tecnologia_desde_xbrl_completo():
    from fetcher import segments as SEG
    xml = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:amzn="http://www.amazon.com/20241231" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
 <context id="c1"><entity><identifier scheme="x">1</identifier></entity><period><startDate>2024-01-01</startDate><endDate>2024-12-31</endDate></period></context>
 <context id="c2"><entity><identifier scheme="x">1</identifier></entity><period><startDate>2023-01-01</startDate><endDate>2023-12-31</endDate></period></context>
 <unit id="usd"><measure>iso4217:USD</measure></unit>
 <amzn:TechnologyAndInfrastructureExpense contextRef="c1" unitRef="usd" decimals="-6">88544000000</amzn:TechnologyAndInfrastructureExpense>
 <amzn:TechnologyAndInfrastructureExpense contextRef="c2" unitRef="usd" decimals="-6">85622000000</amzn:TechnologyAndInfrastructureExpense>
</xbrl>"""
    rows = SEG.extract(xml, None)
    vals = rows[("_tech", "_tech")]["TechnologyAndInfrastructureExpense"]
    assert vals[("A", "2024-01-01", "2024-12-31")] == 88544000000
    src = {"formulario": "10-K", "fecha_presentacion": "2025-02-07", "url": "u", "ns": "amzn"}
    blk = SEG._tech_block({"TechnologyAndInfrastructureExpense": {k: (v, src) for k, v in vals.items()}}, 12)
    assert [p["periodo"] for p in blk["anual"]] == ["2023", "2024"]
    assert blk["anual"][-1]["etiqueta"] == "amzn:TechnologyAndInfrastructureExpense"


def test_bono_10a_csv_del_tesoro():
    from fetcher import market as MK
    txt = '﻿Date,"1 Mo","2 Mo","10 Yr","30 Yr"\n10/30/2026,4.01,4.00,4.12,4.60\n10/29/2026,4.02,4.01,4.08,4.58\n'
    assert MK.parse_csv(txt) == ("2026-10-30", 4.12)


def test_nota_resultados_guia_destacados_y_cita():
    from fetcher import pressrelease as PR, filings as F
    html = """<html><body>
<p><b>Reddit Reports Third Quarter 2026 Results</b></p>
<p><b>Third Quarter 2026 Highlights</b></p>
<ul><li>Revenue grew 53% year-over-year to $895 million.</li><li>Net income was $283 million.</li></ul>
<p>“We delivered another strong quarter and our community keeps growing across the world,” said Steve Huffman, Reddit Co-Founder and CEO.</p>
<p><b>Fourth Quarter 2026 Outlook</b></p>
<p>In the fourth quarter of 2026, we expect:</p>
<ul><li>Revenue in the range of $1,000 million to $1,030 million</li><li>Adjusted EBITDA in the range of $480 million to $510 million</li></ul>
<p><b>Conference Call</b></p><p>Reddit will host a conference call today.</p>
</body></html>"""
    got = PR.extract(html)
    assert got["guia"]["titulo"].startswith("Fourth Quarter 2026 Outlook")
    assert any("1,000 million" in t for t in got["guia"]["texto"])
    assert not any("conference call" in t.lower() for t in got["guia"]["texto"])
    assert got["destacados"]["texto"][0].startswith("Revenue grew 53%")
    assert got["cita"]["cita"].startswith("We delivered") and "Huffman" in got["cita"]["quien"]
    idx = """<table><tr><td>1</td><td>8-K</td><td><a href="/Archives/x/a.htm">a.htm</a></td><td>8-K</td></tr>
<tr><td>2</td><td>Press release</td><td><a href="/Archives/x/pr.htm">pr.htm</a></td><td>EX-99.1</td></tr>
<tr><td>3</td><td>Investor presentation</td><td><a href="/Archives/x/deck.pdf">deck.pdf</a></td><td>EX-99.2</td></tr></table>"""
    ex = F.list_exhibits(idx)
    assert [e["tipo"] for e in ex] == ["EX-99.1", "EX-99.2"] and ex[1]["descripcion"] == "Investor presentation"


def test_cita_con_dicho_antes():
    from fetcher import pressrelease as PR
    html = "<p>Sundar Pichai, CEO of Alphabet and Google, said:</p><p>“We delivered a strong quarter with growth across Search, YouTube and Cloud, and AI is driving it all.”</p>"
    c = PR.extract(html)["cita"]
    assert c["cita"].startswith("We delivered") and c["quien"].startswith("Sundar Pichai")
