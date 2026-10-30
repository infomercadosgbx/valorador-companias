"""Tests de las reglas de extracción con companyfacts sintéticos (forma exacta de la SEC).
Los casos reales están en test_acceptance.py."""
import json

from conftest import COMPANY, companyfacts, fact, submissions

from fetcher import extract as X
from fetcher import filings as F
from fetcher.build import NoSecData, build_from_sec
from fetcher.main import write_if_changed

import pytest
from datetime import date

Q_ENDS = {1: ("01-01", "03-31"), 2: ("04-01", "06-30"), 3: ("07-01", "09-30"), 4: ("10-01", "12-31")}


def cal_year(y, quarters, annual=None, tag_form="10-Q", filed_annual=None, ytd=False):
    """Hechos de un año natural: trimestres discretos (o acumulados si ytd) + anual del 10-K."""
    out = []
    cum = 0
    for i, v in enumerate(quarters, start=1):
        s, e = Q_ENDS[i]
        if ytd:
            cum += v
            out.append(fact(f"{y}-{e}", cum, start=f"{y}-01-01", form=tag_form, filed=f"{y}-{e[:2]}-28" if i < 4 else None))
        elif i < 4 or annual is None:
            out.append(fact(f"{y}-{e}", v, start=f"{y}-{s}", form=tag_form))
    if ytd and len(quarters) == 4:
        out = out[:3]
    if annual is not None:
        out.append(fact(f"{y}-12-31", annual, start=f"{y}-01-01", form="10-K", filed=filed_annual or f"{y + 1}-02-01"))
    return out


def rev_cf(facts, tag="RevenueFromContractWithCustomerExcludingAssessedTax", extra=None):
    g = {tag: facts}
    g.update(extra or {})
    return companyfacts(g)


# ------------------------------------------------------------------ R3 / R4
def test_mismo_periodo_queda_el_presentado_mas_tarde():
    facts = cal_year(2024, [10, 10, 10], annual=40) + [
        fact("2024-12-31", 33, start="2024-01-01", form="10-K", filed="2026-02-20")]  # reexpresado
    flow, _ = X.build_flow(rev_cf(facts), "1", "ingresos", date(2024, 12, 31), "1231")
    assert [a["valor"] for a in flow["anual"]] == [33]
    assert flow["anual"][0]["fecha_presentacion"] == "2026-02-20"


def test_anual_solo_si_viene_de_un_10k():
    facts = [fact("2024-12-31", 40, start="2024-01-01", form="8-K")]
    flow, _ = X.build_flow(rev_cf(facts), "1", "ingresos", date(2024, 12, 31), "1231")
    assert flow["anual"] == []


def test_duraciones_trimestrales_80_100_dias():
    facts = [fact("2024-03-31", 5, start="2024-01-01"),          # 90 días: trimestre
             fact("2024-05-31", 7, start="2024-04-01")]          # 60 días: se ignora
    flow, _ = X.build_flow(rev_cf(facts), "1", "ingresos", date(2024, 5, 31), "1231")
    assert [q["valor"] for q in flow["trimestral"]] == [5]


# ------------------------------------------------------------------ R1 / R2
def test_ingresos_combinan_etiquetas_por_anio():
    old = cal_year(2017, [1, 1, 1], annual=4)
    new = cal_year(2018, [2, 2, 2], annual=8) + cal_year(2019, [3, 3, 3], annual=12)
    cf = companyfacts({"SalesRevenueNet": old, "Revenues": new})
    flow, _ = X.build_flow(cf, "1", "ingresos", date(2019, 12, 31), "1231")
    assert [(a["periodo"], a["valor"], a["etiqueta"]) for a in flow["anual"]] == [
        ("2017", 4, "us-gaap:SalesRevenueNet"), ("2018", 8, "us-gaap:Revenues"), ("2019", 12, "us-gaap:Revenues")]


def test_etiqueta_mas_reciente_manda_en_periodos_solapados():
    cf = companyfacts({
        "Revenues": cal_year(2023, [1, 1, 1], annual=10),
        "RevenueFromContractWithCustomerExcludingAssessedTax": cal_year(2023, [1, 1, 1], annual=11) + cal_year(2024, [3, 3, 3], annual=12),
    })
    flow, _ = X.build_flow(cf, "1", "ingresos", date(2024, 12, 31), "1231")
    assert flow["anual"][0]["valor"] == 11


def test_descarta_etiqueta_obsoleta_mas_de_60_dias():
    rev = cal_year(2025, [10, 10, 10], annual=40) + cal_year(2026, [10, 10, 10])
    ni_old = cal_year(2025, [1, 1, 1], annual=4)                      # termina dic-25
    pl = cal_year(2025, [2, 2, 2], annual=8) + cal_year(2026, [2, 2, 2])  # llega a sep-26
    cf = rev_cf(rev, extra={"NetIncomeLoss": ni_old, "ProfitLoss": pl})
    ref = X.revenue_reference_end(cf)
    flow, w = X.build_flow(cf, "1", "beneficio_neto", ref, "1231")
    assert flow["etiquetas_usadas"] == ["us-gaap:ProfitLoss"]
    assert any(x["codigo"] == "etiqueta_obsoleta" and x["etiqueta"] == "NetIncomeLoss" for x in w)


def test_todas_obsoletas_genera_aviso_y_no_datos():
    rev = cal_year(2026, [10, 10, 10])
    cf = rev_cf(rev, extra={"NetIncomeLoss": cal_year(2024, [1, 1, 1], annual=4)})
    flow, w = X.build_flow(cf, "1", "beneficio_neto", X.revenue_reference_end(cf), "1231")
    assert flow["anual"] == [] and any(x["nivel"] == "aviso" for x in w)


# ---------------------------------------------------------------------- R5
def test_4t_se_deriva_del_anual():
    facts = cal_year(2025, [100, 110, 120], annual=460) + cal_year(2026, [140, 150, 160])
    flow, w = X.build_flow(rev_cf(facts), "1", "ingresos", date(2026, 9, 30), "1231")
    q = {p["periodo"]: p for p in flow["trimestral"]}
    assert q["4T25"]["valor"] == 130 and q["4T25"]["derivado"] == "Año − 1T − 2T − 3T"
    assert flow["ttm"]["valor"] == 130 + 140 + 150 + 160
    assert not [x for x in w if x["codigo"] == "4t_descartado"]


def test_4t_que_no_encaja_se_descarta_reclasificacion():
    # Anual reexpresado por discontinuadas (caso AppLovin 2023) y trimestres originales.
    facts = cal_year(2023, [100, 110, 120], annual=300) + cal_year(2024, [90, 95, 100])
    flow, w = X.build_flow(rev_cf(facts), "1", "ingresos", date(2024, 9, 30), "1231")
    assert "4T23" not in {p["periodo"] for p in flow["trimestral"]}
    assert any(x["codigo"] == "4t_descartado" for x in w)


def test_4t_ratio_frente_al_1t_siguiente():
    facts = cal_year(2025, [100, 100, 100], annual=480) + cal_year(2026, [50, 60, 70])  # 4T=180; 180/50=3,6
    flow, w = X.build_flow(rev_cf(facts), "1", "ingresos", date(2026, 9, 30), "1231")
    assert "4T25" not in {p["periodo"] for p in flow["trimestral"]}


def test_flujos_de_caja_acumulados_se_convierten_en_trimestres():
    ocf = cal_year(2025, [10, 20, 30, 40], annual=100, ytd=True)
    cf = rev_cf(cal_year(2025, [100, 110, 120], annual=460),
                extra={"NetCashProvidedByUsedInOperatingActivities": ocf})
    flow, _ = X.build_flow(cf, "1", "caja_operativa", date(2025, 12, 31), "1231")
    assert [(q["periodo"], q["valor"]) for q in flow["trimestral"]] == [
        ("1T25", 10), ("2T25", 20), ("3T25", 30), ("4T25", 40)]


# ------------------------------------------------------- etiquetas trimestre
def test_etiquetas_anio_52_53_semanas_broadcom():
    assert X.quarter_label(date(2025, 2, 2), "1102") == "1T25"
    assert X.quarter_label(date(2025, 5, 4), "1102") == "2T25"
    assert X.quarter_label(date(2025, 8, 3), "1102") == "3T25"
    assert X.quarter_label(date(2025, 11, 2), "1102") == "4T25"
    assert X.quarter_label(date(2024, 11, 3), "1102") == "4T24"
    assert X.quarter_label(date(2023, 10, 29), "1102") == "4T23"
    assert X.quarter_label(date(2026, 9, 30), "1231") == "3T26"
    assert X.fy_label(date(2026, 1, 3)) == 2025


# ---------------------------------------------------------------- balance
def test_deuda_suma_corriente_y_no_corriente_y_ventana_16_meses():
    rev = cal_year(2026, [10, 10, 10])
    cf = rev_cf(rev, extra={
        "LongTermDebtNoncurrent": [fact("2024-03-31", 1), fact("2025-12-31", 100, form="10-K"), fact("2026-09-30", 120)],
        "LongTermDebtCurrent": [fact("2026-09-30", 6)],
    })
    bal, w = X.build_instant(cf, "1", "deuda", date(2026, 9, 30))
    assert bal["ultimo"]["valor"] == 126 and bal["asumido"] is False
    assert [h["periodo_fin"] for h in bal["historico"]] == ["2025-12-31", "2026-09-30"]
    assert bal["historico"][0]["componentes_no_etiquetados"]  # sin porción corriente ese día
    assert "LongTermDebtCurrent" in bal["ultimo"]["etiqueta"]


def test_sin_deuda_etiquetada_se_asume_cero():
    cf = rev_cf(cal_year(2026, [10, 10, 10]))
    bal, w = X.build_instant(cf, "1", "deuda", date(2026, 9, 30))
    assert bal["asumido"] is True and bal["ultimo"]["valor"] == 0
    assert any(x["codigo"] == "deuda_asumida_cero" for x in w)


def test_deuda_obsoleta_se_asume_cero():
    cf = rev_cf(cal_year(2026, [10, 10, 10]), extra={"LongTermDebt": [fact("2023-12-31", 50, form="10-K")]})
    bal, w = X.build_instant(cf, "1", "deuda", date(2026, 9, 30))
    assert bal["asumido"] is True


def test_acciones_varias_clases_se_suman():
    dei = {"EntityCommonStockSharesOutstanding": [
        fact("2026-10-20", 5, accn="A-1", filed="2026-10-29"), fact("2026-10-20", 1, accn="A-1", filed="2026-10-29"),
        fact("2026-10-20", 4, accn="A-1", filed="2026-10-29"), fact("2026-07-20", 99, accn="A-0", filed="2026-07-29")]}
    cf = companyfacts({}, dei=dei)
    p = X.shares_outstanding(cf, "1")
    assert p["valor"] == 10 and p["clases"] == 3


# ---------------------------------------------------------- ensamblado
def test_extranjera_ifrs_no_soportada():
    cf = {"cik": 1, "facts": {"ifrs-full": {"Revenue": {"units": {"EUR": []}}}}}
    rec = build_from_sec(COMPANY, cf, submissions([{"form": "20-F", "accessionNumber": "1", "filingDate": "2026-03-01"}]))
    assert rec["soportada"] is False and rec["avisos"][0]["codigo"] == "no_soportada"
    assert "resultados" not in rec


def test_sin_datos_de_la_sec_es_error():
    with pytest.raises(NoSecData):
        build_from_sec(COMPANY, None, None)
    with pytest.raises(NoSecData):
        build_from_sec(COMPANY, companyfacts({"Assets": [fact("2026-09-30", 1)]}), submissions([]))


def test_caida_de_ingresos_mayor_25_por_ciento_avisa():
    facts = cal_year(2022, [70, 70, 70], annual=280) + cal_year(2023, [45, 45, 45], annual=180)
    rec = build_from_sec(COMPANY, rev_cf(facts), submissions([]))
    assert any(w["codigo"] == "posible_discontinuada" and w["periodo"] == "2023" for w in rec["avisos"])


def test_cada_cifra_lleva_fuente_url_fecha_y_etiqueta():
    rec = build_from_sec(COMPANY, rev_cf(cal_year(2025, [1, 1, 1], annual=4)), submissions([]))
    p = rec["resultados"]["ingresos"]["anual"][0]
    for k in ("valor", "fuente", "url", "fecha_presentacion", "etiqueta"):
        assert p[k] not in (None, "")
    assert p["url"].startswith("https://www.sec.gov/Archives/edgar/data/1/")


# ---------------------------------------------------------------- filings
def test_ultimo_informe_y_8k_de_resultados():
    subs = submissions([
        {"accessionNumber": "0001-26-000003", "filingDate": "2026-10-29", "form": "8-K", "items": "5.02", "primaryDocument": "a.htm"},
        {"accessionNumber": "0001-26-000002", "filingDate": "2026-10-28", "form": "10-Q", "reportDate": "2026-09-30", "primaryDocument": "q.htm"},
        {"accessionNumber": "0001-26-000001", "filingDate": "2026-10-28", "form": "8-K", "items": "2.02,9.01", "primaryDocument": "e.htm"},
    ])
    p = F.latest_periodic("1652044", subs)
    e = F.latest_earnings_8k("1652044", subs)
    assert p["formulario"] == "10-Q" and p["url_documento"].endswith("/000126000002/q.htm")
    assert e["accn"] == "0001-26-000001"


def test_exhibit_99_1_desde_el_indice():
    html = """<table class="tableFile"><tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
    <tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/edgar/data/1/000/main.htm">main.htm</a></td><td>8-K</td></tr>
    <tr><td>2</td><td>PRESS RELEASE</td><td><a href="/Archives/edgar/data/1/000/ex991.htm">ex991.htm</a></td><td>EX-99.1</td></tr></table>"""
    assert F.find_exhibit(html) == "https://www.sec.gov/Archives/edgar/data/1/000/ex991.htm"
    assert F.find_exhibit("") is None


# ------------------------------------------------------------ escritura
def test_solo_escribe_si_cambia(tmp_path):
    p = tmp_path / "x.json"
    assert write_if_changed(p, {"a": 1, "generado": "t1"}) is True
    assert write_if_changed(p, {"a": 1, "generado": "t2"}) is False
    assert write_if_changed(p, {"a": 2, "generado": "t3"}) is True
    assert json.loads(p.read_text())["a"] == 2
