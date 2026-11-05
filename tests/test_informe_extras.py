"""Informe de resultados: traducción, «el trimestre por dentro» y reacción fuera de horario."""
import io
import json
from datetime import date, datetime, timezone

from fetcher import prices, resultados as RES, traduccion as TR


def test_traduccion_automatica_de_guia_y_cifras():
    assert TR.frase_guia("Revenue: $2,365 – $2,395 million") == "Ingresos: 2.365–2.395 M$"
    assert TR.frase_guia("Adjusted EBITDA Margin: 84% – 85%") == "Margen de EBITDA ajustado: 84–85%"
    assert TR.frase_guia("Mystery metric: $1 – $2 million") is None   # sin glosario: queda pendiente
    assert TR.cifra("$(8,221)", solo_numero=True) == "(8.221)"
    assert TR.cifra("91.5%") == "91,5%" and TR.cifra("(35)bps") == "(35) pb"
    assert TR.cabecera("(In millions, except percentages) 2026 2025 % Change") == "(millones de $, salvo porcentajes y datos por acción) 2026 2025 % var."


def test_aplicar_usa_i18n_y_cuenta_pendientes(tmp_path):
    (tmp_path / "i18n").mkdir()
    (tmp_path / "i18n" / "notas_es.json").write_text(json.dumps({"t": {"Record quarter.": "Trimestre récord."}}), encoding="utf-8")
    rep = {"destacados": {"texto": ["Record quarter.", "Untranslated line here."],
                          "filas": [{"etiqueta": "Adjusted EBITDA", "valores": ["$1,842", "59%"]}], "unidad": "million"},
           "guia": {"texto": ["Revenue: $2,365 – $2,395 million"]}, "cita": {"cita": "We grew a lot."}}
    TR.aplicar(rep, tmp_path)
    assert rep["destacados"]["texto_es"] == ["Trimestre récord.", None]
    assert rep["destacados"]["filas"][0]["etiqueta_es"] == "EBITDA ajustado"
    assert rep["destacados"]["filas"][0]["valores_es"] == ["1.842", "59%"]
    assert rep["guia"]["texto_es"] == ["Ingresos: 2.365–2.395 M$"]
    assert rep["cita"]["cita_es"] is None and rep["traduccion"]["pendientes"] == 2


def _q(per, fin, v):
    return {"periodo": per, "periodo_fin": fin, "valor": v, "url": "u", "fecha_presentacion": "2026-11-04"}


def test_por_dentro_caja_costes_y_dilucion():
    Q = [("3T25", "2025-09-30"), ("4T25", "2025-12-31"), ("1T26", "2026-03-31"), ("2T26", "2026-06-30"), ("3T26", "2026-09-30")]
    def serie(vals):
        return {"trimestral": [_q(p, f, v) for (p, f), v in zip(Q, vals) if v is not None]}
    rec = {"resultados": {
        "ingresos": serie([100, 110, 120, 130, 150]), "beneficio_neto": serie([20, 22, 24, 26, 30]),
        "caja_operativa": serie([25, 20, 30, 18, 33]), "capex": serie([5, 5, 5, 5, 6]),
        "recompras": serie([10, 10, 10, 10, 12]), "acciones_diluidas_media": serie([100, 99, 98, 97, 96]),
        "investigacion_desarrollo": serie([10, 10, 11, 11, 12]), "remuneracion_acciones": serie([3, 3, 3, 3, 3])}}
    d = RES.por_dentro(rec, "3T26", "2026-09-30")
    assert d["periodo"] == "3T26" and d["ingresos"][-1]["interanual_pct"] == 50.0
    last = d["caja"][-1]
    assert last["fcf"] == 27 and last["conversion_pct"] == 110
    assert d["gastos"][0]["nombre"] == "I+D" and d["gastos"][0]["pct"] == 8.0 and d["gastos"][0]["pct_ya"] == 10.0
    a = d["accionista"]
    assert a["recompras_12m"] == 42 and a["acciones_var_pct"] == -4.0
    assert a["retorno_base"] == "flujo de caja libre" and a["retorno_sobre_caja_pct"] == round(42 / (15 + 25 + 13 + 27) * 100)


def test_alpaca_after_hours_y_premercado():
    bars = {"bars": {"APP": [
        {"t": "2026-11-04T21:05:00Z", "c": 290.0, "v": 1000},   # 16:05 ET, after-hours del día de resultados
        {"t": "2026-11-04T23:55:00Z", "c": 300.0, "v": 500},    # 18:55 ET
        {"t": "2026-11-05T13:10:00Z", "c": 310.5, "v": 800}]}}  # 08:10 ET, premercado
    seen = {}
    def opener(req, timeout=30):
        seen["url"], seen["hdr"] = req.full_url, dict(req.header_items())
        return io.BytesIO(json.dumps(bars).encode())
    A = prices.AlpacaExtendedHours("kid", "sec", opener=opener, sleep=lambda s: None)
    ext = A.extended("APP", date(2026, 11, 4), amc=True, now=datetime(2026, 11, 5, 13, 40, tzinfo=timezone.utc))
    assert "feed=sip" in seen["url"] and "start=2026-11-04T21%3A00%3A00Z" in seen["url"]
    assert seen["hdr"].get("Apca-api-key-id") == "kid"
    assert ext["ultimo"]["sesion"] == "premercado" and ext["ultimo"]["precio"] == 310.5
    assert ext["after_hours"]["precio"] == 300.0
    reac = {"cierre_antes": 271.75, "fecha_antes": "2026-11-04", "provisional": True}
    out = RES.extended_reaction(reac, ext)
    assert out["sesion_despues"] == "premercado" and out["variacion_pct"] == round((310.5 / 271.75 - 1) * 100, 2)
    assert out["fuera_de_hora"]["after_hours"]["variacion_pct"] == round((300 / 271.75 - 1) * 100, 2)
    # con el cierre siguiente ya disponible no se toca
    done = {"cierre_antes": 1, "provisional": False, "variacion_pct": 5}
    assert RES.extended_reaction(dict(done), ext) == done


def test_dia_resultados_elige_quien_presenta(tmp_path):
    from fetcher import dia_resultados as DR
    (tmp_path / "data").mkdir()
    def w(t, fecha, hora, k8="2026-08-01"):
        (tmp_path / "data" / f"{t}.json").write_text(json.dumps({"ticker": t, "ultimo_8k_resultados": {"fecha_presentacion": k8},
            "resultados_previstos": {"proximos": {"fecha": fecha, "hora_codigo": hora}}}), encoding="utf-8")
    w("VST", "2026-11-06", "bmo"); w("APP", "2026-11-05", "amc"); w("AMZN", "2027-02-01", "amc")
    w("RDDT", "2027-02-10", "amc", k8="2026-11-06")   # ya presentó hoy: Finnhub ya apunta al trimestre siguiente
    assert DR.elegir(tmp_path, "manana", date(2026, 11, 6)) == ["APP", "RDDT", "VST"]
    assert DR.elegir(tmp_path, "tarde", date(2026, 11, 5)) == ["APP"]
    assert DR.elegir(tmp_path, "manana", date(2026, 11, 10)) == []


def test_ebitda_ajustado_de_la_nota_frente_a_estimacion_manual():
    nota = {"ebitda_ajustado": {"fila": "Ongoing operations Adjusted EBITDA", "valores": [1767.0, 1349.0], "actual_primero": True}}
    k8 = {"url_ex99_1": "https://www.sec.gov/x.htm", "fecha_presentacion": "2026-08-07"}
    est = {"valor": 1700e6, "fuente": "manual", "manual": True}
    r = RES.ebitda_row(nota, k8, "2T26", 4_300e6, {}, est)
    assert r["reportado"]["valor"] == 1767e6 and r["anio_anterior"] == 1349e6
    assert r["resultado"] == "Beat" and round(r["dif_pct"], 1) == 3.9 and r["interanual_pct"] == 30.99
    # sin nota todavía: fila pendiente con la estimación
    p = RES.ebitda_row(None, k8, "3T26", None, {}, est)
    assert p["reportado"] is None and p["pendiente"]
    assert RES.ebitda_row(None, k8, "3T26", None, {}, None) is None
