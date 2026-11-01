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
