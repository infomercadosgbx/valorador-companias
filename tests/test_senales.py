"""scripts/senales.py: repaso semanal por companies.json → repaso y alarma diaria solo con lo grave."""
import importlib.util
import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _mod(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("senales", REPO / "scripts" / "senales.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    (tmp_path / "data").mkdir()
    (tmp_path / "propuestas").mkdir()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "ESTADO", tmp_path / "propuestas" / "_estado.json")
    (tmp_path / "companies.json").write_text(json.dumps({"companies": [
        {"ticker": "AAA", "repaso": "martes"}, {"ticker": "BBB", "repaso": "viernes"},
        {"ticker": "CCC", "repaso": "martes", "archivada": {"desde": "2026-11-13", "motivo": ""}}]}))
    serie = [["2026-11-10", 100], ["2026-11-11", 107], ["2026-11-12", 95]]          # +7 % y −11 %
    (tmp_path / "data" / "AAA.json").write_text(json.dumps({"historico_precio": {"serie": serie}}))
    (tmp_path / "data" / "BBB.json").write_text(json.dumps({"historico_precio": {"serie": serie[:2]}}))
    (tmp_path / "data" / "CCC.json").write_text(json.dumps({"historico_precio": {"serie": serie}}))
    (tmp_path / "propuestas" / "_estado.json").write_text(json.dumps({"internet": {"AAA": "2026-11-09", "BBB": "2026-11-09"}}))
    return m


def test_repaso_solo_las_del_dia_y_activas(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    r = m.calcular(date(2026, 11, 17), "repaso")                     # martes
    assert [x["ticker"] for x in r] == ["AAA"] and r[0]["revisar"] and r[0]["desde"] == "2026-11-09"
    assert [x["ticker"] for x in m.calcular(date(2026, 11, 20), "repaso")] == ["BBB"]   # viernes
    assert m.calcular(date(2026, 11, 16), "repaso") == []            # lunes: nada


def test_alarma_solo_lo_grave_y_una_vez(tmp_path, monkeypatch):
    m = _mod(tmp_path, monkeypatch)
    r = m.calcular(date(2026, 11, 13), "alarma")
    assert [x["ticker"] for x in r] == ["AAA"] and "-11.2 %" in r[0]["alarmas"][0]   # el +7 % no es grave; CCC archivada
    m.marcar(date(2026, 11, 13), ["AAA"], "alarma")
    assert m.calcular(date(2026, 11, 13), "alarma") == []           # ya vista: no se repite
