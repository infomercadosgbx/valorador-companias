import json
from datetime import date

from fetcher import objetivos as OBJ


class FakeResp:
    def __init__(self, body): self.body = body
    def read(self, n=-1): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_with(payload):
    return lambda req, timeout=20: FakeResp(json.dumps(payload).encode())


def warn(nivel, codigo, msg):
    return {"nivel": nivel, "codigo": codigo, "mensaje": msg}


def test_media_y_historial():
    p = OBJ.AlphaVantageTargets("k", opener=opener_with({"Symbol": "VST", "AnalystTargetPrice": "210.5",
                                                         "AnalystRatingStrongBuy": "8", "AnalystRatingBuy": "17", "AnalystRatingHold": "2"}), sleep=lambda s: None)
    rec = {}
    prev = {"objetivo_analistas": {"valor": 207.32, "fecha": "2026-11-11", "historial": [["2026-11-11", 207.32]]}}
    OBJ.actualizar(rec, "VST", prev, provider=p, today=date(2026, 11, 12), warn=warn)
    o = rec["objetivo_analistas"]
    assert o["valor"] == 210.5 and o["analistas"] == 27 and o["fecha"] == "2026-11-12"
    assert o["historial"] == [["2026-11-11", 207.32], ["2026-11-12", 210.5]]


def test_sin_cambio_no_duplica_y_una_consulta_al_dia():
    p = OBJ.AlphaVantageTargets("k", opener=opener_with({"Symbol": "VST", "AnalystTargetPrice": "207.32"}), sleep=lambda s: None)
    rec = {}
    prev = {"objetivo_analistas": {"valor": 207.32, "fecha": "2026-11-11", "historial": [["2026-11-11", 207.32]]}}
    OBJ.actualizar(rec, "VST", prev, provider=p, today=date(2026, 11, 12), warn=warn)
    assert rec["objetivo_analistas"]["historial"] == [["2026-11-11", 207.32]]
    boom = OBJ.AlphaVantageTargets("k", opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe consultar")))
    rec2 = {}
    OBJ.actualizar(rec2, "VST", {"objetivo_analistas": rec["objetivo_analistas"]}, provider=boom, today=date(2026, 11, 12), warn=warn)
    assert rec2["objetivo_analistas"]["valor"] == 207.32


def test_cuota_agotada_conserva_y_avisa():
    p = OBJ.AlphaVantageTargets("k", opener=opener_with({"Information": "Thank you for using Alpha Vantage! ... premium"}), sleep=lambda s: None)
    rec = {"avisos": []}
    prev = {"objetivo_analistas": {"valor": 200, "fecha": "2026-11-10", "historial": [["2026-11-10", 200]]}}
    OBJ.actualizar(rec, "VST", prev, provider=p, today=date(2026, 11, 12), warn=warn)
    assert rec["objetivo_analistas"]["valor"] == 200
    assert rec["avisos"][0]["codigo"] == "sin_objetivo_analistas"


def test_sin_proveedor_conserva():
    rec = {}
    OBJ.actualizar(rec, "VST", {"objetivo_analistas": {"valor": 1}}, provider=None)
    assert rec["objetivo_analistas"] == {"valor": 1}
