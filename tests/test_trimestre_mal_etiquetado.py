"""Oracle: sus 10-K de 2020-2022 etiquetan el ingreso ANUAL con un contexto de
3 meses (us-gaap:Revenues, inicio 1-mar). No debe tomarse como 4T."""
from fetcher.extract import build_flow
from datetime import date


def fact(start, end, val, form="10-Q", filed="2022-01-01", accn="0000000000-22-000001"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "accn": accn, "fy": 2022, "fp": "Q"}


def test_anual_con_contexto_trimestral_se_descarta():
    rfc = [
        fact("2021-06-01", "2021-08-31", 9728e6),
        fact("2021-09-01", "2021-11-30", 10360e6),
        fact("2021-12-01", "2022-02-28", 10513e6),
        fact("2021-06-01", "2022-05-31", 42440e6, form="10-K", filed="2024-06-20"),
        fact("2022-06-01", "2022-08-31", 11445e6),
    ]
    revs = [fact("2022-03-01", "2022-05-31", 42440e6, form="10-K", filed="2022-06-21")]
    cf = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": rfc}},
        "Revenues": {"units": {"USD": revs}},
    }}}
    res, avisos = build_flow(cf, 1341439, "ingresos", date(2022, 8, 31), "0531")
    q4 = next(q for q in res["trimestral"] if q["periodo"] == "4T22")
    assert q4["valor"] == 11839e6
    assert q4.get("derivado") == "Año − 1T − 2T − 3T"
    assert any(a["codigo"] == "trimestre_mal_etiquetado" for a in avisos)
