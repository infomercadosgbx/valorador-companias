"""Participaciones en no cotizadas y acciones preferentes: entran en el valor del
patrimonio con su dato de la SEC (fixtures reales del 3T26)."""
from conftest import companyfacts, fact

from fetcher import extract as X
from test_acceptance import mill, rec


def test_alphabet_participaciones_revalorizacion_y_preferentes():
    B = rec("GOOGL")["balance"]
    inv, up, down, pref = (B[k]["ultimo"] for k in
                           ("participaciones", "participaciones_subidas", "participaciones_bajadas", "preferentes"))
    assert inv["periodo_fin"] == "2026-09-30" and mill(inv) == 128_169
    assert "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount" in inv["etiqueta"]
    assert mill(up) == 88_784 and mill(down) == 9_210
    assert mill(pref) == 18_023 and "ConvertiblePreferredStock" in pref["etiqueta"]
    for p in (inv, up, down, pref):  # trazables como cualquier otra cifra
        assert p["url"] and p["fecha_presentacion"] and p["fuente"]


def test_amazon_participaciones_sin_revalorizacion_publicada():
    B = rec("AMZN")["balance"]
    inv = B["participaciones"]["ultimo"]
    assert inv["periodo_fin"] == "2026-09-30" and mill(inv) > 140_000
    assert B["participaciones_subidas"]["ultimo"] is None
    assert not B["preferentes"]["ultimo"] or B["preferentes"]["ultimo"]["valor"] == 0


def test_sin_participaciones_no_avisa():
    cf = companyfacts({"Revenues": [fact("2026-09-30", 10, start="2026-07-01")]})
    inst, w = X.build_instant(cf, 1, "participaciones", X.d("2026-09-30"))
    assert inst["ultimo"] is None and w == []


def test_preferentes_obsoletas_se_descartan():
    # Vistra: si las preferentes se amortizan y la etiqueta deja de aparecer, no se arrastra el saldo viejo
    cf = companyfacts({"Revenues": [fact("2026-09-30", 10, start="2026-07-01")],
                       "PreferredStockValue": [fact("2025-12-31", 2_476_000_000, form="10-K")]})
    inst, _ = X.build_instant(cf, 1, "preferentes", X.d("2026-09-30"))
    assert inst["ultimo"] is None


def _ctx(i, end, dims=()):
    mem = "".join(f'<xbrldi:explicitMember dimension="us-gaap:{a}">{m}</xbrldi:explicitMember>' for a, m in dims)
    seg = f"<xbrli:segment>{mem}</xbrli:segment>" if mem else ""
    return (f'<xbrli:context id="{i}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>{seg}'
            f'</xbrli:entity><xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>')


def test_cartera_cotizadas_y_participaciones_con_nombre():
    from fetcher import cartera as CA
    rec = ("FairValueByMeasurementFrequencyAxis", "us-gaap:FairValueMeasurementsRecurringMember")
    xml = ('<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2026" '
           'xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
           + _ctx("a", "2026-09-30", [rec]) + _ctx("b", "2026-09-30")
           + _ctx("c", "2026-09-30", [rec, ("ScheduleOfEquityMethodInvestmentEquityMethodInvesteeNameAxis", "goog:SpaceXMember"),
                                      ("FinancialInstrumentAxis", "goog:MarketableEquitySecuritiesMember")])
           + _ctx("d", "2026-09-30", [rec, ("FairValueByFairValueHierarchyLevelAxis", "us-gaap:FairValueInputsLevel1Member")])
           + _ctx("e", "2025-12-31")
           + '<us-gaap:EquitySecuritiesFvNi contextRef="a" unitRef="usd">90384000000</us-gaap:EquitySecuritiesFvNi>'
           '<us-gaap:EquitySecuritiesFvNi contextRef="d" unitRef="usd">89920000000</us-gaap:EquitySecuritiesFvNi>'
           '<us-gaap:EquitySecuritiesFvNi contextRef="c" unitRef="usd">75200000000</us-gaap:EquitySecuritiesFvNi>'
           '<us-gaap:EquitySecuritiesWithoutReadilyDeterminableFairValueAmount contextRef="b" unitRef="usd">128169000000'
           '</us-gaap:EquitySecuritiesWithoutReadilyDeterminableFairValueAmount>'
           '<us-gaap:EquitySecuritiesWithoutReadilyDeterminableFairValueAmount contextRef="e" unitRef="usd">68700000000'
           '</us-gaap:EquitySecuritiesWithoutReadilyDeterminableFairValueAmount>'
           '</xbrli:xbrl>').encode()
    out = CA.extract(xml, None)
    assert out["fecha"] == "2026-09-30"
    assert out["totales"]["cotizada"]["valor"] == 90_384_000_000      # la del nivel 1 no sustituye al total
    assert out["totales"]["no_cotizada"]["valor"] == 128_169_000_000   # la del cierre anterior no cuenta
    (d,) = out["detalle"]
    assert "Space" in d["nombre"] and d["tipo"] == "cotizada" and d["valor"] == 75_200_000_000


def test_aviso_si_las_participaciones_caen_de_golpe():
    # Una participada sale a bolsa y la compañía la saca de la partida de no cotizadas
    from fetcher.build import _aviso_participaciones
    tag = "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount"
    cf = companyfacts({tag: [fact("2026-09-30", 143_700_000_000, filed="2026-10-30"),
                             fact("2026-12-31", 2_000_000_000, form="10-K", filed="2027-02-05")]})
    (w,) = _aviso_participaciones(cf, X.d("2026-12-31"))
    assert w["codigo"] == "participaciones_caen" and w["nivel"] == "aviso"
    # si pasa a cotizadas a largo plazo, se sigue contando y no hay aviso
    cf["facts"]["us-gaap"]["EquitySecuritiesFvNiNoncurrent"] = {"units": {"USD": [
        fact("2026-12-31", 210_000_000_000, form="10-K", filed="2027-02-05")]}}
    assert _aviso_participaciones(cf, X.d("2026-12-31")) == []
    inst, _ = X.build_instant(cf, 1, "participaciones", X.d("2026-12-31"))
    assert inst["ultimo"]["valor"] == 212_000_000_000


def test_sin_caida_no_avisa():
    from fetcher.build import _aviso_participaciones
    tag = "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount"
    cf = companyfacts({tag: [fact("2026-06-30", 120e9), fact("2026-09-30", 128e9)]})
    assert _aviso_participaciones(cf, X.d("2026-09-30")) == []
