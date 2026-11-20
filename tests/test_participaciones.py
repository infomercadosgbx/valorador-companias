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
