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
