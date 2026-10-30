"""Cliente SEC (ritmo, reintentos) y ejecución completa con un cliente simulado."""
import io
import json
import urllib.error

import pytest
from conftest import companyfacts, fact, submissions

from fetcher import main as M
from fetcher.prices import NoPriceProvider
from fetcher.sec_client import SecClient, SecError


class FakeResp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_user_agent_obligatorio(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SecError):
        SecClient()
    with pytest.raises(SecError):
        SecClient("sinemail")


def test_reintenta_429_y_respeta_404():
    calls, sleeps = [], []

    def opener(req, timeout):
        calls.append(req.full_url)
        assert req.headers["User-agent"] == "Ana Perez ana@example.com"
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "slow", {}, None)
        if "missing" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return FakeResp(b'{"ok": 1}')

    c = SecClient("Ana Perez ana@example.com", opener=opener, sleep=sleeps.append)
    assert c.get_json("https://data.sec.gov/x") == {"ok": 1}
    assert len(calls) == 3 and any(s >= 1.5 for s in sleeps)
    assert c.get_json("https://data.sec.gov/missing") is None


def test_ritmo_maximo_5_por_segundo():
    sleeps = []
    c = SecClient("Ana Perez ana@example.com", opener=lambda r, timeout: FakeResp(b"{}"), sleep=sleeps.append)
    for _ in range(4):
        c.get_json("https://data.sec.gov/x")
    assert all(0 < s <= 0.2 for s in sleeps) and len(sleeps) >= 3


def test_falla_tras_agotar_reintentos():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "down", {}, None)
    c = SecClient("Ana Perez ana@example.com", opener=opener, sleep=lambda s: None, retries=3)
    with pytest.raises(SecError):
        c.get_json("https://data.sec.gov/x")


class FakeClient:
    requests_made = 0

    def __init__(self, data):
        self.data = data

    def companyfacts(self, cik):
        return self.data.get(cik, (None, None))[0]

    def submissions(self, cik):
        return self.data.get(cik, (None, None))[1]

    def company_tickers(self):
        return {"0": {"cik_str": 1, "ticker": "OK", "title": "Ok"}, "1": {"cik_str": 99, "ticker": "BAD", "title": "Bad"}}

    def get_text(self, url):
        return None


def _repo(tmp_path):
    (tmp_path / "companies.json").write_text(json.dumps({"companies": [
        {"ticker": "OK", "nombre": "Ok", "cik": "0000000001", "color": "#111", "monograma": "O"},
        {"ticker": "BAD", "nombre": "Bad", "cik": "0000000002", "color": "#222", "monograma": "B"}]}))
    return tmp_path


def test_run_escribe_datos_y_reporta_fallos(tmp_path):
    root = _repo(tmp_path)
    rev = [fact("2026-09-30", 10, start="2026-07-01")]
    client = FakeClient({"0000000001": (companyfacts({"Revenues": rev}), submissions([]))})
    report = tmp_path / "r.md"
    failures = M.run(root=root, client=client, provider=NoPriceProvider(), price_warning="sin clave", report=report)
    assert [t for t, _ in failures] == ["BAD"]
    ok = json.loads((root / "data" / "OK.json").read_text())
    assert ok["resultados"]["ingresos"]["trimestral"][0]["valor"] == 10
    assert any(w["codigo"] == "sin_precio" for w in ok["avisos"])
    assert any(w["codigo"] == "cik" for w in ok["avisos"]) is False
    idx = json.loads((root / "data" / "index.json").read_text())
    assert [c["ticker"] for c in idx["companias"]] == ["OK"]
    assert "BAD" in report.read_text()
    assert (root / "analysis" / "OK.json").exists() and (root / "manual" / "BAD.json").exists()


def test_cik_que_no_coincide_genera_aviso(tmp_path):
    root = _repo(tmp_path)
    rev = [fact("2026-09-30", 10, start="2026-07-01")]
    client = FakeClient({"0000000001": (companyfacts({"Revenues": rev}), submissions([])),
                         "0000000002": (companyfacts({"Revenues": rev}), submissions([]))})
    M.run(root=root, client=client, provider=NoPriceProvider(), price_warning="x")
    bad = json.loads((root / "data" / "BAD.json").read_text())
    assert bad["avisos"][0]["codigo"] == "cik"
