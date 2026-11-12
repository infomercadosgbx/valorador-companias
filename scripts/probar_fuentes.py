"""Diagnóstico temporal: qué fuentes de mercado responden desde GitHub."""
import json, os, time, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (valorador-companias; diagnostico)"}


def get(url, t=30):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), str(e)


def show(tag, url, n=2, tail=True):
    s, b = get(url)
    lines = b.strip().splitlines()
    out = (lines[:1] + lines[-n:]) if tail and len(lines) > 3 else lines[:n + 1]
    print(f"== {tag} [{s}] {len(b)}B")
    for l in out:
        print("   ", l[:300])


fk, hk, tk = (os.environ.get(k, "") for k in ("FRED_API_KEY", "FINNHUB_API_KEY", "TWELVEDATA_API_KEY"))

print("### Twelve Data")
for n, syms in enumerate(("EUR/USD,USD/JPY,GBP/USD,XAU/USD,XAG/USD,WTI/USD,XBR/USD,USD/CNY", "NG/USD,DXY,EUR/GBP,USD/CHF,XCU/USD,ETH/USD,HG1,CL1")):
    if n: time.sleep(65)
    s, b = get(f"https://api.twelvedata.com/quote?{urllib.parse.urlencode({'symbol': syms, 'apikey': tk})}", t=60)
    try:
        j = json.loads(b)
        for k, v in j.items():
            print(f"== td {k}: {v.get('close')} prev={v.get('previous_close')} dt={v.get('datetime')} {str(v.get('message', ''))[:140]}")
    except Exception:
        print("== td batch", s, b[:400])
