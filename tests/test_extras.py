"""Segmentos, formularios 4 y cambios en los riesgos del 10-K."""
from fetcher import insiders, riskfactors, segments

INST = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2024" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
<context id="q"><entity><segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">abc:CloudMember</xbrldi:explicitMember></segment></entity><period><startDate>2026-07-01</startDate><endDate>2026-09-30</endDate></period></context>
<context id="ytd"><entity><segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">abc:CloudMember</xbrldi:explicitMember></segment></entity><period><startDate>2026-01-01</startDate><endDate>2026-09-30</endDate></period></context>
<context id="tot"><entity></entity><period><startDate>2026-07-01</startDate><endDate>2026-09-30</endDate></period></context>
<context id="p"><entity><segment><xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">abc:AdsMember</xbrldi:explicitMember></segment></entity><period><startDate>2026-07-01</startDate><endDate>2026-09-30</endDate></period></context>
<unit id="usd"><measure>iso4217:USD</measure></unit>
<us-gaap:Revenues contextRef="q" unitRef="usd">100</us-gaap:Revenues>
<us-gaap:Revenues contextRef="ytd" unitRef="usd">280</us-gaap:Revenues>
<us-gaap:Revenues contextRef="tot" unitRef="usd">500</us-gaap:Revenues>
<us-gaap:OperatingIncomeLoss contextRef="q" unitRef="usd">30</us-gaap:OperatingIncomeLoss>
<us-gaap:Revenues contextRef="p" unitRef="usd">60</us-gaap:Revenues>
</xbrl>"""


def test_segmentos_extrae_trimestre_y_producto():
    rows = segments.extract(INST, None)
    cloud = rows[("StatementBusinessSegmentsAxis", "abc:CloudMember")]
    assert cloud["nombre"] == "Cloud" and cloud["ingresos"]["Revenues"][("T", "2026-07-01", "2026-09-30")] == 100
    assert cloud["operativo"]["OperatingIncomeLoss"][("T", "2026-07-01", "2026-09-30")] == 30
    assert ("ProductOrServiceAxis", "abc:AdsMember") in rows


def test_cuarto_trimestre_deducido():
    ser = {("T", "2025-01-01", "2025-03-31"): 10, ("T", "2025-04-01", "2025-06-30"): 11,
           ("T", "2025-07-01", "2025-09-30"): 12, ("A", "2025-01-01", "2025-12-31"): 50}
    tri, anu = segments._assemble(ser, 12)
    assert [t["periodo"] for t in tri] == ["1T25", "2T25", "3T25", "4T25"] and tri[-1]["valor"] == 17
    assert anu[0]["periodo"] == "2025"


FORM4 = b"""<?xml version="1.0"?><ownershipDocument><aff10b5One>1</aff10b5One>
<reportingOwner><reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Class C</value></securityTitle>
<transactionDate><value>2026-10-01</value></transactionDate><transactionCoding><transactionCode>S</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>250.5</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>900</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""


def test_form4_y_resumen():
    owners, tx, plan = insiders.parse_form4(FORM4)
    assert owners[0] == {"nombre": "Doe Jane", "cargo": "CFO"} and plan
    assert tx[0]["importe"] == 25050 and tx[0]["sentido"] == "venta"

    class C:
        def get_bytes(self, url):
            assert url.endswith("/f4.xml")
            return FORM4
    subs = {"filings": {"recent": {"accessionNumber": ["0001-26-1"], "filingDate": ["2026-10-02"], "reportDate": [""],
                                   "form": ["4"], "primaryDocument": ["xslF345X05/f4.xml"], "items": [""]}}}
    from datetime import date
    r = insiders.build(C(), "1", subs, today=date(2026, 10, 31))
    assert r["resumen"]["ventas_mercado"] == 25050 and r["resumen"]["ventas_con_plan"] == 25050


def test_riesgos_titulares_y_comparacion():
    long = "x " * 200
    html = ("<p>Item 1A. Risk Factors</p><p>Intense competition could harm our business and results.</p><p>%s</p>"
            "<p>New AI regulation may limit our products.</p><p>%s</p><p>Item 1B. Unresolved Staff Comments</p>") % (long, long)
    sec = riskfactors.risk_section(riskfactors.to_paragraphs(html))
    hs = riskfactors.headings(sec)
    assert hs == ["Intense competition could harm our business and results.", "New AI regulation may limit our products."]
    added, removed = riskfactors.compare(hs, ["Intense competition could harm our businesses and results.", "Pandemics may disrupt operations."])
    assert added == ["New AI regulation may limit our products."] and removed == ["Pandemics may disrupt operations."]


def test_comparativa_con_competidores():
    from fetcher import peers as P
    rec = {"resultados": {"ingresos": {"ttm": {"valor": 1000, "periodo_fin": "2026-09-30"},
                                       "trimestral": [{"valor": v} for v in (200, 200, 200, 200, 250, 250, 250, 250)], "anual": []},
                          "beneficio_operativo": {"ttm": {"valor": 300}}, "beneficio_neto": {"ttm": {"valor": 200}},
                          "caja_operativa": {"ttm": {"valor": 350}}, "capex": {"ttm": {"valor": 50}}, "amortizacion": {"ttm": {"valor": 100}},
                          "coste_ventas": {"ttm": {"valor": 400}}},
           "balance": {"caja": {"ultimo": {"valor": 100}}, "deuda": {"ultimo": None, "asumido": True}},
           "acciones_en_circulacion": {"valor": 10}, "precio": {"valor": 50}}
    f = P.summarize(rec)
    assert f["crecimiento"] == 25 and f["margen_bruto"] == 60 and f["deuda"] == 0 and f["ebitda"] == 400
    w = P.with_price(f, 50)
    assert w["capitalizacion"] == 500 and w["ev"] == 400 and w["per"] == 2.5 and w["ev_ebitda"] == 1 and w["rentabilidad_fcf"] == 60

    class Prov:
        def peers(self, t):
            return ["OWN", "AAA", "ZZZ", "BBB"]
    lst, src = P.peer_list("OWN", [], Prov(), {"AAA": ("1", "A"), "BBB": ("2", "B")})
    assert lst == ["AAA", "BBB"] and src.startswith("Finnhub")
    lst, src = P.peer_list("OWN", ["BBB"], Prov(), {"AAA": ("1", "A"), "BBB": ("2", "B")})
    assert lst == ["BBB"] and src == "manual"


def test_avisos_sin_repetir(tmp_path):
    import json
    from datetime import date
    from fetcher import alerts as A
    c = {"ticker": "OK", "nombre": "Ok"}
    data = {"precio": {"valor": 90, "cierre_anterior": 100, "fecha": "2026-10-30"},
            "ultimo_informe": {"accn": "2", "formulario": "10-Q", "fecha_presentacion": "2026-10-29", "url_indice": "u"},
            "directivos": {"operaciones": [{"codigo": "P", "persona": "Ana", "cargo": "CEO", "fecha": "2026-10-28", "acciones": 100, "precio": 90, "importe": 9000, "url": "f4"}]},
            "resultados_previstos": {"proximos": {"fecha": "2026-11-02", "bpa_estimado": 1.2}}}
    prev = {"ultimo_informe": {"accn": "1"}, "directivos": {"operaciones": []}}
    an = {"verdict": {"buyBelow": 95}, "meta": {"asOf": "1-jun-2026"}}
    st = {}
    out = A.company_alerts(c, data, prev, an, st, date(2026, 11, 1))
    txt = " ".join(t for _, t in out)
    assert "zona de compra" in txt and "10-Q" in txt and "Compra de un directivo" in txt and "−10,0%" in txt
    assert "mañana" in txt and "153 días" in txt
    again = A.company_alerts(c, data, data, an, st, date(2026, 11, 1))
    assert again == []


def test_noticias_tope_por_medio_y_8k_oficiales():
    from datetime import date
    from fetcher import filings as F
    from fetcher.prices import FinnhubProvider
    p = FinnhubProvider.__new__(FinnhubProvider)
    rows = [{"headline": f"Y{i}", "source": "Yahoo", "url": "u", "datetime": 1793000000 - i} for i in range(40)]
    rows += [{"headline": f"S{i}", "source": "SeekingAlpha", "url": "u", "datetime": 1792000000 - i} for i in range(5)]
    p._get = lambda *a, **k: rows
    out = p.news("X", today=date(2026, 11, 5))
    assert len(out) == 30
    assert sum(n["medio"] == "Seeking Alpha" for n in out) == 5   # entran los otros medios
    subs = {"filings": {"recent": {"accessionNumber": ["0001-26-1", "0001-26-2"], "filingDate": ["2026-10-20", "2026-01-01"],
            "reportDate": ["", ""], "form": ["8-K", "8-K"], "primaryDocument": ["a.htm", "b.htm"], "items": ["2.02,9.01", "5.02"]}}}
    of = F.recent_8k_news("123", subs, today=date(2026, 11, 5))
    assert len(of) == 1 and of[0]["oficial"] and of[0]["titular"].endswith("Resultados")
