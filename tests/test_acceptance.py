"""Criterios de aceptación con fixtures reales de la SEC (tests/fixtures/*.json.gz).

Las fixtures se capturan con el workflow «Capturar fixtures SEC» (o con
`python scripts/capture_fixtures.py`) y quedan congeladas en git. Si faltan,
estos tests se saltan con un mensaje que lo indica.
"""
from conftest import load_fixture

from fetcher.build import build_from_sec

M = 1_000_000

COMPANIES = {
    "APP": {"ticker": "APP", "nombre": "AppLovin", "cik": "0001751008"},
    "GOOGL": {"ticker": "GOOGL", "nombre": "Alphabet", "cik": "0001652044"},
    "AVGO": {"ticker": "AVGO", "nombre": "Broadcom", "cik": "0001730168"},
    "RDDT": {"ticker": "RDDT", "nombre": "Reddit", "cik": "0001713445"},
    "AMZN": {"ticker": "AMZN", "nombre": "Amazon", "cik": "0001018724"},
}


def rec(t):
    cf, subs = load_fixture(t)
    return build_from_sec(COMPANIES[t], cf, subs)


def q(r, concept, label):
    return {p["periodo"]: p for p in r["resultados"][concept]["trimestral"]}[label]


def a(r, concept, label):
    return {p["periodo"]: p for p in r["resultados"][concept]["anual"]}[label]


def mill(p):
    return round(p["valor"] / M)


def test_alphabet_3t26_ingresos_caja_deuda():
    r = rec("GOOGL")
    assert mill(q(r, "ingresos", "3T26")) == 127_577
    caja, deuda = r["balance"]["caja"]["ultimo"], r["balance"]["deuda"]["ultimo"]
    assert caja["periodo_fin"] == "2026-09-30" and mill(caja) == 265_098
    assert deuda["periodo_fin"] == "2026-09-30" and mill(deuda) == 126_118
    assert r["balance"]["deuda"]["asumido"] is False


def test_alphabet_serie_anual_sin_huecos_pese_al_cambio_de_etiquetas():
    r = rec("GOOGL")
    years = [int(p["periodo"]) for p in r["resultados"]["ingresos"]["anual"]]
    assert years == list(range(years[0], years[-1] + 1)) and years[-1] >= 2025


def test_amazon_3t26_ingresos():
    assert mill(q(rec("AMZN"), "ingresos", "3T26")) == 201_944


def test_broadcom_beneficio_neto_2025():
    r = rec("AVGO")
    assert mill(a(r, "beneficio_neto", "2025")) == 23_126


def test_broadcom_52_53_semanas_trimestres_unicos():
    labels = [p["periodo"] for p in rec("AVGO")["resultados"]["ingresos"]["trimestral"]]
    assert len(labels) == len(set(labels))


def test_reddit_deuda_cero_asumida():
    d = rec("RDDT")["balance"]["deuda"]
    assert d["asumido"] is True and d["ultimo"]["valor"] == 0


def test_applovin_reclasificacion_avisa():
    r = rec("APP")
    codes = {(w["codigo"], w.get("periodo")) for w in r["avisos"]}
    assert ("posible_discontinuada", "2023") in codes or any(c == "4t_descartado" for c, _ in codes)


def test_todas_las_cifras_tienen_trazabilidad():
    for t in COMPANIES:
        r = rec(t)
        for concept in r["resultados"].values():
            for p in concept["anual"] + concept["trimestral"]:
                assert p["url"].startswith("https://www.sec.gov/") and p["etiqueta"] and p["fecha_presentacion"]


def test_amazon_4t_estacionales_no_se_descartan():
    r = rec("AMZN")
    assert mill(q(r, "beneficio_neto", "4T25")) > 0
    assert r["resultados"]["caja_operativa"]["ttm"] is not None


def test_acciones_siempre_presentes():
    for t in COMPANIES:
        assert rec(t)["acciones_en_circulacion"]["valor"] > 0


def test_broadcom_y_alphabet_amortizaciones_por_componentes():
    avgo = rec("AVGO")["resultados"]["amortizacion"]
    assert avgo["por_componentes"] and mill(a(rec("AVGO"), "amortizacion", "2025")) == 574 + 8062
    assert avgo["ttm"] is not None
    googl = rec("GOOGL")["resultados"]["amortizacion"]
    assert googl["ttm"] is not None and mill(a(rec("GOOGL"), "amortizacion", "2025")) >= 21136


def test_amazon_mantiene_la_etiqueta_combinada():
    assert not rec("AMZN")["resultados"]["amortizacion"].get("por_componentes")
