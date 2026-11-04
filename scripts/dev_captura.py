"""Temporal (rama dev-captura): descarga notas de resultados reales para desarrollar el informe."""
import gzip, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fetcher.sec_client import SecClient
from fetcher import filings as F

OUT = ROOT / "captura"
OUT.mkdir(exist_ok=True)
c = SecClient()
idx = []
for comp in json.loads((ROOT / "companies.json").read_text())["companies"]:
    subs = c.submissions(comp["cik"])
    n = 0
    for row in F.recent_rows(subs):
        if row["form"] == "8-K" and "2.02" in [x.strip() for x in (row.get("items") or "").split(",")]:
            rec = F.filing_record(comp["cik"], row, "8-K")
            F.attach_exhibit(c, rec)
            if rec.get("url_ex99_1"):
                html = c.get_text(rec["url_ex99_1"]) or ""
                name = f"{comp['ticker']}_{row['filingDate']}.htm.gz"
                (OUT / name).write_bytes(gzip.compress(html.encode("utf-8")))
                idx.append({"ticker": comp["ticker"], "fecha": row["filingDate"], "accn": row["accessionNumber"], "url": rec["url_ex99_1"], "archivo": name})
                print(comp["ticker"], row["filingDate"], len(html))
            n += 1
            if n >= 3:
                break
(OUT / "index.json").write_text(json.dumps(idx, indent=1))
