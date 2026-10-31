"""Captura fixtures reales de la SEC para los tests de aceptación.

  SEC_USER_AGENT="Nombre email" python scripts/capture_fixtures.py [APP GOOGL ...]

Guarda en tests/fixtures/<TICKER>_companyfacts.json.gz solo las etiquetas que usa
el fetcher (todas las candidatas, para poder probar cambios de etiqueta) y en
<TICKER>_submissions.json.gz los 300 filings más recientes. Son datos de la SEC
sin modificar, solo recortados.
"""
import gzip
import re
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fetcher import concepts as C  # noqa: E402
from fetcher.sec_client import SecClient  # noqa: E402

DEFAULT = ["APP", "GOOGL", "AVGO", "RDDT", "AMZN"]
OUT = ROOT / "tests" / "fixtures"


def wanted_tags():
    tags = set()
    for spec in C.FLOW_CONCEPTS.values():
        tags.update(spec["tags"])
    for spec in C.INSTANT_CONCEPTS.values():
        for s in spec["strategies"]:
            tags.update(s["required"])
            for group in s["optional"]:
                tags.update(group)
    tags.update(t for t, _ in C.DEBT_MATURITY_TAGS)
    return tags


def trim_facts(cf):
    keep = wanted_tags()
    facts = cf.get("facts", {})
    out = {"cik": cf.get("cik"), "entityName": cf.get("entityName"), "facts": {}}
    if "us-gaap" in facts:
        out["facts"]["us-gaap"] = {k: v for k, v in facts["us-gaap"].items()
                                   if k in keep or re.search(r"Depreciation|Amortization", k)}
    if "dei" in facts:
        out["facts"]["dei"] = {k: v for k, v in facts["dei"].items() if k == C.SHARES_OUTSTANDING_TAG[1]}
    for other in facts:
        if other not in ("us-gaap", "dei"):
            out["facts"][other] = {}  # se conserva la presencia de la taxonomía (p. ej. ifrs-full)
    return out


def trim_subs(subs, n=300):
    recent = subs.get("filings", {}).get("recent", {})
    subs = dict(subs)
    subs["filings"] = {"recent": {k: v[:n] for k, v in recent.items()}}
    return subs


def main(tickers):
    companies = {c["ticker"]: c for c in json.loads((ROOT / "companies.json").read_text())["companies"]}
    client = SecClient()
    OUT.mkdir(parents=True, exist_ok=True)
    for t in tickers:
        cik = companies[t]["cik"]
        cf = client.companyfacts(cik)
        subs = client.submissions(cik)
        if not cf or not subs:
            raise SystemExit(f"La SEC no devuelve datos para {t} (CIK {cik})")
        for name, obj in (("companyfacts", trim_facts(cf)), ("submissions", trim_subs(subs))):
            p = OUT / f"{t}_{name}.json.gz"
            with gzip.open(p, "wt", encoding="utf-8") as f:
                json.dump(obj, f, separators=(",", ":"))
            print(f"{p.relative_to(ROOT)}: {p.stat().st_size / 1024:.0f} KB")


def gh_error(msg):
    """Anotación visible en el resumen del Action (sin datos sensibles)."""
    print(f"::error title=Capturar fixtures::{msg}".replace("\n", "%0A"))


if __name__ == "__main__":
    import os
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    print(f"SEC_USER_AGENT: {'presente' if ua else 'VACÍO'}; formato «Nombre email»: "
          f"{'sí' if ('@' in ua and ' ' in ua) else 'NO'}")
    try:
        main(sys.argv[1:] or DEFAULT)
    except BaseException as e:  # noqa: BLE001
        gh_error(f"{type(e).__name__}: {e}")
        raise
