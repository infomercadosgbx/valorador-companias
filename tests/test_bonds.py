"""Lectura de emisiones de deuda desde una instancia XBRL (con dimensiones)."""
from fetcher import bonds as B

INST = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:tst="http://tst.com/2025" xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
 <xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>
   <xbrldi:explicitMember dimension="us-gaap:DebtInstrumentAxis">tst:A4250NotesDueAugust2057Member</xbrldi:explicitMember>
 </xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="c2"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>
   <xbrldi:explicitMember dimension="us-gaap:DebtInstrumentAxis">tst:EuroNotesMember</xbrldi:explicitMember>
 </xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="c3"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>
   <xbrldi:explicitMember dimension="us-gaap:LongtermDebtTypeAxis">us-gaap:CommercialPaperMember</xbrldi:explicitMember>
 </xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="c4"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>
   <xbrldi:explicitMember dimension="us-gaap:DebtInstrumentAxis">tst:EuroNotesMember</xbrldi:explicitMember>
   <xbrldi:explicitMember dimension="srt:RangeAxis">srt:MinimumMember</xbrldi:explicitMember>
 </xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
 <xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
 <xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
 <us-gaap:DebtInstrumentInterestRateStatedPercentage contextRef="c1" unitRef="pure" decimals="5">0.0425</us-gaap:DebtInstrumentInterestRateStatedPercentage>
 <us-gaap:DebtInstrumentFaceAmount contextRef="c1" unitRef="usd" decimals="-6">1250000000</us-gaap:DebtInstrumentFaceAmount>
 <us-gaap:DebtInstrumentFaceAmount contextRef="c2" unitRef="eur" decimals="-6">750000000</us-gaap:DebtInstrumentFaceAmount>
 <us-gaap:DebtInstrumentInterestRateStatedPercentage contextRef="c2" unitRef="pure" decimals="5">0.031</us-gaap:DebtInstrumentInterestRateStatedPercentage>
 <us-gaap:DebtInstrumentMaturityDate contextRef="c2">2031-03-15</us-gaap:DebtInstrumentMaturityDate>
 <us-gaap:DebtInstrumentInterestRateStatedPercentage contextRef="c4" unitRef="pure" decimals="5">0.99</us-gaap:DebtInstrumentInterestRateStatedPercentage>
 <us-gaap:CommercialPaper contextRef="c3" unitRef="usd" decimals="-6">2000000000</us-gaap:CommercialPaper>
</xbrli:xbrl>"""

LAB = b"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
 <link:labelLink xlink:type="extended">
  <link:loc xlink:type="locator" xlink:href="tst-20251231.xsd#tst_A4250NotesDueAugust2057Member" xlink:label="loc1"/>
  <link:label xlink:type="resource" xlink:label="lab1" xlink:role="http://www.xbrl.org/2003/role/label">4.250% Notes due on August 22, 2057 [Member]</link:label>
  <link:labelArc xlink:type="arc" xlink:from="loc1" xlink:to="lab1"/>
 </link:labelLink>
</link:linkbase>"""


def test_emisiones_cupon_vencimiento_divisa():
    items, comp = B.extract(INST, LAB, "2025-12-31")
    by = {i["miembro"]: i for i in items}
    a = by["tst:A4250NotesDueAugust2057Member"]
    assert a["nombre"] == "4.250% Notes due on August 22, 2057"
    assert a["cupon"] == 4.25 and a["nominal"] == 1_250_000_000 and a["moneda"] == "USD"
    assert a["vencimiento"] == "2057-08-22" and a["tipo"] == "Bono senior"
    e = by["tst:EuroNotesMember"]
    assert e["moneda"] == "EUR" and e["cupon"] == 3.1 and e["vencimiento"] == "2031-03-15"  # se ignora el contexto con RangeAxis
    assert comp == [{"miembro": "us-gaap:CommercialPaperMember", "nombre": "Commercial Paper", "tipo": "Papel comercial", "importe": 2_000_000_000}]


def test_clasificacion_y_vencimiento_por_etiqueta():
    assert B.classify("1.5% Convertible Senior Notes due 2028", "") == "Bono convertible"
    assert B.classify("Term Loan A", "") == "Préstamo a plazo"
    assert B.maturity_from_label("Notes due 2030") == ("2030-12-31", True)


def test_ficheros_del_indice():
    idx = {"directory": {"item": [{"name": "a-20251231.htm"}, {"name": "a-20251231_htm.xml"}, {"name": "a-20251231_lab.xml"}, {"name": "FilingSummary.xml"}]}}
    assert B.find_files(idx) == ("a-20251231_htm.xml", "a-20251231_lab.xml")


def test_ultimo_10k_y_10q_posteriores():
    from conftest import submissions
    subs = submissions([
        {"accessionNumber": "3", "filingDate": "2026-10-30", "form": "10-Q"},
        {"accessionNumber": "2", "filingDate": "2026-07-30", "form": "10-Q"},
        {"accessionNumber": "x", "filingDate": "2026-07-29", "form": "8-K"},
        {"accessionNumber": "1", "filingDate": "2026-02-06", "form": "10-K"},
        {"accessionNumber": "0", "filingDate": "2025-10-30", "form": "10-Q"}])
    assert [r["accessionNumber"] for r in B.target_filings(subs)] == ["3", "2", "1"]
