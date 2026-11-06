"""Informe de resultados: lectura de la nota (8-K, Ex. 99.1), guía, estimaciones y reacción.

Las notas de tests/fixtures/notas/ son Exhibit 99.1 reales de la SEC, sin modificar.
Las cifras esperadas son las del 10-Q en XBRL de ese mismo trimestre."""
import gzip
import json
from datetime import date

import pytest

from conftest import FIXTURES
from fetcher import estimaciones as EST
from fetcher import nota_tablas as NT
from fetcher import resultados as RES

NOTAS = FIXTURES / "notas"


def nota(name):
    return gzip.decompress((NOTAS / f"{name}.htm.gz").read_bytes()).decode("utf-8")


# ------------------------------------------------------------- notas reales
@pytest.mark.parametrize("name,ref,expected", [
    # Amazon: columnas «2025 2026» (el año anterior primero)
    ("AMZN_2026-10-29", {"ingresos": 167.7e9}, {"ingresos": 201944e6, "beneficio_operativo": 28076e6,
                                                 "beneficio_neto": 20685e6, "bpa_diluido": 1.89}),
    # Broadcom: «trimestre actual, anterior, año anterior», ejercicio de 52/53 semanas
    ("AVGO_2026-09-02", {"ingresos": 22187e6}, {"ingresos": 29591e6, "beneficio_operativo": 15955e6,
                                                 "beneficio_neto": 13088e6, "bpa_diluido": 2.68}),
    # Reddit: tabla en miles sin unidades escritas (se deducen del trimestre anterior)
    ("RDDT_2026-10-29", {"ingresos": 804905e3}, {"ingresos": 894957e3, "beneficio_operativo": 261586e3,
                                                  "beneficio_neto": 283264e3, "bpa_diluido": 1.40}),
    # PepsiCo: «12 Weeks Ended», BPA bajo el subtítulo «Diluted», beneficio atribuible a PepsiCo
    ("PEP_2026-10-08", {"ingresos": 23.5e9}, {"ingresos": 25274e6, "beneficio_operativo": 4260e6,
                                               "beneficio_neto": 3048e6, "bpa_diluido": 2.23}),
])
def test_nota_cifras_gaap_del_trimestre(name, ref, expected):
    got = NT.extract(nota(name), ref)
    for k, v in expected.items():
        assert k in got, f"{name}: falta {k}"
        assert got[k]["valor"] == pytest.approx(v, rel=2e-3, abs=0.006), f"{name} {k}: {got[k]}"
        assert got[k]["periodo"] != "A"


def test_nota_chevron_sin_beneficio_operativo():
    got = NT.extract(nota("CVX_2026-10-30"), {"ingresos": 67199e6, "beneficio_neto": 12072e6})
    assert got["ingresos"]["valor"] == pytest.approx(65237e6)
    assert got["beneficio_neto"]["valor"] == pytest.approx(9924e6)     # atribuible a Chevron, no el total
    assert got["bpa_diluido"]["valor"] == pytest.approx(5.06)
    assert "beneficio_operativo" not in got
    assert "beneficio_antes_impuestos" in got


# ------------------------------------------------------------- tablas sintéticas
def _tabla(head, rows, units="(in millions, except per share data)"):
    hs = "".join(f"<td>{h}</td>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<p>{units}</p><table><tr><td>Three Months Ended</td></tr><tr><td></td>{hs}</tr>{body}</table>"


def test_columna_del_trimestre_y_filas_non_gaap():
    html = _tabla(["2025", "2026", "2025", "2026"], [
        ["Total revenues", "$", "100", "$", "120", "$", "300", "$", "350"],
        ["Operating income", "10", "15", "30", "40"],
        ["Adjusted operating income", "99", "99", "99", "99"],
        ["Net income", "8", "12", "24", "30"],
        ["Diluted earnings per share", "$", "0.50", "$", "0.75", "$", "1.5", "$", "2.0"],
    ])
    got = NT.extract(html)
    assert got["ingresos"]["valor"] == 120e6
    assert got["beneficio_operativo"]["valor"] == 15e6
    assert got["beneficio_neto"]["valor"] == 12e6
    assert got["bpa_diluido"]["valor"] == 0.75


def test_negativos_entre_parentesis():
    html = _tabla(["2026", "2025"], [["Revenue", "50", "40"], ["Operating loss", "(7)", "(9)"],
                                      ["Net loss", "(6)", "(8)"], ["Net loss per share, diluted", "(0.12)", "(0.20)"]])
    got = NT.extract(html)
    assert got["beneficio_operativo"]["valor"] == -7e6
    assert got["bpa_diluido"]["valor"] == -0.12


# ------------------------------------------------------------- guía
def test_guia_amazon():
    txt = ["• Net sales are expected to be between $240.0 billion and $247.0 billion, or to grow between 12% and 16% compared with fourth quarter 2025.",
           "• Operating income is expected to be between $28.5 billion and $33.5 billion, compared with $25.0 billion in fourth quarter 2025."]
    g = {x["concepto"]: x for x in RES.parse_guidance(txt)}
    assert g["ingresos"]["min"] == 240e9 and g["ingresos"]["max"] == 247e9 and g["ingresos"]["medio"] == 243.5e9
    assert g["beneficio_operativo"]["medio"] == 31e9


def test_guia_sin_unidades_en_millones_y_aproximada():
    g = RES.parse_guidance(["Ongoing Operations Adjusted EBITDA $6,800 - $7,600"])
    assert g[0]["concepto"] == "ebitda" and g[0]["min"] == 6800e6
    g = RES.parse_guidance(["Fourth quarter revenue guidance of approximately $34.8 billion."])
    assert g[0]["concepto"] == "ingresos" and g[0]["medio"] == 34.8e9


# ------------------------------------------------------------- piezas del informe
def test_etiquetas_de_trimestre():
    assert RES._lab("3T26", dq=1) == "4T26"
    assert RES._lab("4T26", dq=1) == "1T27"
    assert RES._lab("1T27", dq=-1) == "4T26"
    assert RES._lab("3T26", dy=-1) == "3T25"


def test_beat_miss():
    assert RES.verdict(105, {"valor": 100})[1] == "Beat"
    assert RES.verdict(95, {"valor": 100})[1] == "Miss"
    assert RES.verdict(100, {"valor": 100})[1] == "En línea"
    assert RES.verdict(None, {"valor": 100}) == (None, None)


def _rec_precios(serie, precio=None):
    return {"historico_precio": {"serie": serie, "fuente": "Twelve Data"}, "precio": precio or {}}


def test_reaccion_tras_el_cierre_y_antes_de_la_apertura():
    serie = [["2026-10-28", 100.0], ["2026-10-29", 110.0], ["2026-10-30", 99.0]]
    r, s12 = RES.reaction(_rec_precios(serie), date(2026, 10, 29), "amc")
    assert r["cierre_antes"] == 110 and r["cierre_despues"] == 99 and r["variacion_pct"] == -10.0
    assert s12[-1][0] == "2026-10-30"
    r, _ = RES.reaction(_rec_precios(serie), date(2026, 10, 29), "bmo")
    assert r["cierre_antes"] == 100 and r["cierre_despues"] == 110


def test_reaccion_provisional_con_la_cotizacion_del_dia():
    serie = [["2026-10-28", 100.0], ["2026-10-29", 110.0]]
    r, _ = RES.reaction(_rec_precios(serie, {"valor": 121.0, "fecha": "2026-10-30"}), date(2026, 10, 29), None)
    assert r["provisional"] and r["variacion_pct"] == 10.0 and r["hora_supuesta"]


def test_trimestre_provisional_si_no_hay_10q():
    rec = {"ultimo_8k_resultados": {"fecha_presentacion": "2026-10-30"},
           "resultados": {"ingresos": {"trimestral": [{"periodo": "2T26", "periodo_fin": "2026-06-30", "valor": 1}]}}}
    assert RES.target_quarter(rec) == ("3T26", "2026-09-29", False)
    rec["resultados"]["ingresos"]["trimestral"].append({"periodo": "3T26", "periodo_fin": "2026-09-30", "valor": 1})
    assert RES.target_quarter(rec) == ("3T26", "2026-09-30", True)


# ------------------------------------------------------------- foto del consenso
def test_foto_del_consenso_y_revisiones(tmp_path):
    rec = {"resultados_previstos": {"proximos": {"fecha": "2027-02-03", "hora": "tras el cierre", "hora_codigo": "amc",
                                                 "bpa_estimado": 2.47, "ingresos_estimados": 249.9e9}}}
    assert EST.snapshot(tmp_path, "AMZN", rec, today=date(2026, 11, 4)) is None   # faltan más de 30 días
    p = EST.snapshot(tmp_path, "AMZN", rec, today=date(2027, 1, 20))
    assert p and json.loads(p.read_text())["finnhub"]["bpa"] == 2.47
    assert EST.snapshot(tmp_path, "AMZN", rec, today=date(2027, 1, 21)) is None   # sin cambios
    rec["resultados_previstos"]["proximos"]["bpa_estimado"] = 2.50
    p = EST.snapshot(tmp_path, "AMZN", rec, today=date(2027, 1, 22))
    snap = json.loads(p.read_text())
    assert [e["bpa"] for e in snap["evolucion"]] == [2.47, 2.50]
    assert EST.for_report(tmp_path, "AMZN", date(2027, 2, 3))["finnhub"]["capturado"] == "2027-01-22"
    assert EST.for_report(tmp_path, "AMZN", date(2027, 3, 3)) is None


def test_estimaciones_manuales_por_trimestre():
    man = {"estimaciones_resultados": [{"periodo": "3T26", "bpa": 1.99, "segmento_clave": "AWS"},
                                       {"periodo": "4T26", "bpa": None}]}
    assert EST.manual_for(man, "3t26")["bpa"] == 1.99
    assert EST.manual_for(man, "1T27") is None
    assert EST.segmento_clave(man) == "AWS"
