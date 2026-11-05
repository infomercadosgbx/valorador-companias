"""Utilidades de test: construir companyfacts sintéticos con la forma exacta de la SEC
y cargar fixtures reales (tests/fixtures/*.json.gz)."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures"

_accn = [0]


def fact(end, val, start=None, form="10-Q", filed=None, accn=None):
    _accn[0] += 1
    f = {"end": end, "val": val, "form": form, "filed": filed or end,
         "accn": accn or f"0000000000-26-{_accn[0]:06d}", "fy": int(end[:4]), "fp": "FY"}
    if start:
        f["start"] = start
    return f


def companyfacts(gaap=None, dei=None, units=None, name="Test Co"):
    """gaap: {tag: [facts]} en USD salvo que units[tag] diga otra cosa."""
    units = units or {}
    facts = {"us-gaap": {t: {"units": {units.get(t, "USD"): fs}} for t, fs in (gaap or {}).items()}}
    if dei:
        facts["dei"] = {t: {"units": {"shares": fs}} for t, fs in dei.items()}
    return {"cik": 1, "entityName": name, "facts": facts}


def submissions(rows, fye="1231", name="Test Co"):
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "primaryDocument", "items"]
    recent = {k: [r.get(k, "") for r in rows] for k in keys}
    return {"name": name, "fiscalYearEnd": fye, "sic": "7370", "sicDescription": "Services",
            "filings": {"recent": recent}}


def load_fixture(ticker):
    cf = FIXTURES / f"{ticker}_companyfacts.json.gz"
    sb = FIXTURES / f"{ticker}_submissions.json.gz"
    if not cf.exists() or not sb.exists():
        pytest.skip(f"Falta la fixture real de {ticker}: lanza el workflow «Capturar fixtures SEC» (README).")
    with gzip.open(cf, "rt", encoding="utf-8") as a, gzip.open(sb, "rt", encoding="utf-8") as b:
        return json.load(a), json.load(b)


COMPANY = {"ticker": "TST", "nombre": "Test Co", "cik": "0000000001", "color": "#000", "monograma": "T"}


@pytest.fixture(autouse=True)
def _sin_red_noticias(monkeypatch):
    """Los tests no leen feeds RSS ni APIs de noticias reales."""
    from fetcher import news

    class _Cache(news.FeedCache):
        def get(self, fid):
            return []
    monkeypatch.setattr(news, "FeedCache", _Cache)
    monkeypatch.setattr(news, "apis_from_env", lambda: [])
