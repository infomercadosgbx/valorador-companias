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

print("### Cboe")
for s in ("VIX", "VIX3M", "VXN", "OVX", "GVZ", "VVIX", "SKEW"):
    show("cboe " + s, f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{s}_History.csv")

print("### ECB")
show("ecb aaa10y", "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y?format=csvdata&lastNObservations=3", n=3)
show("ecb dfr", "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.DFR.LEV?format=csvdata&lastNObservations=2", n=2)
show("ecb eurusd", "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata&lastNObservations=2", n=2)

print("### FRED series")
for sid in ("DTWEXBGS", "BAMLC0A0CM", "MORTGAGE30US", "DCOILBRENTEU", "DCOILWTICO", "DHHNGSP", "ICSA", "RSAFS",
            "JTSJOL", "UMCSENT", "HOUST", "SP500", "VIXCLS", "NASDAQCOM", "CPIAUCSL", "T10Y2Y", "T10YIE", "NFCI"):
    q = urllib.parse.urlencode({"series_id": sid, "api_key": fk, "file_type": "json", "sort_order": "desc", "limit": 2})
    s, b = get(f"https://api.stlouisfed.org/fred/series/observations?{q}")
    try:
        o = json.loads(b)["observations"]
        obs = [(x["date"], x["value"]) for x in o]
    except Exception:
        obs = b[:150]
    q = urllib.parse.urlencode({"series_id": sid, "api_key": fk, "file_type": "json"})
    s2, b2 = get(f"https://api.stlouisfed.org/fred/series/release?{q}")
    try:
        rel = [(r["id"], r["name"]) for r in json.loads(b2)["releases"]]
    except Exception:
        rel = b2[:100]
    print(f"== fred {sid} [{s}] {obs} release={rel}")
    time.sleep(0.6)

print("### FRED próximas fechas de publicación")
for rid in (9, 180, 192, 91, 27, 10, 50, 54, 46, 53):
    q = urllib.parse.urlencode({"release_id": rid, "api_key": fk, "file_type": "json", "realtime_start": "2026-11-01",
                                "include_release_dates_with_no_data": "true", "sort_order": "asc", "limit": 6})
    s, b = get(f"https://api.stlouisfed.org/fred/release/dates?{q}")
    try:
        ds = [x["date"] for x in json.loads(b)["release_dates"]]
    except Exception:
        ds = b[:150]
    print(f"== release {rid} [{s}] {ds}")
    time.sleep(0.6)

print("### Finnhub")
for sym in ("DIA", "IWM", "VGK", "EWP", "EWJ", "MCHI", "EEM", "SOXX", "TLT", "CPER", "URA", "USO", "GLD", "UUP",
            "^GSPC", "OANDA:EUR_USD", "BINANCE:BTCUSDT"):
    s, b = get(f"https://finnhub.io/api/v1/quote?{urllib.parse.urlencode({'symbol': sym, 'token': hk})}")
    print(f"== finnhub {sym} [{s}] {b[:160]}")
    time.sleep(1.1)

print("### Twelve Data")
syms = "EUR/USD,USD/JPY,GBP/USD,USD/CNY,XAU/USD,XAG/USD,BTC/USD,ETH/USD,WTI/USD,XBR/USD,NG/USD,DXY"
s, b = get(f"https://api.twelvedata.com/quote?{urllib.parse.urlencode({'symbol': syms, 'apikey': tk})}", t=60)
try:
    j = json.loads(b)
    for k, v in j.items():
        print(f"== td {k}: {v.get('close')} prev={v.get('previous_close')} dt={v.get('datetime')} {v.get('message', '')[:120]}")
except Exception:
    print("== td batch", s, b[:400])
time.sleep(62)
s, b = get(f"https://api.twelvedata.com/time_series?{urllib.parse.urlencode({'symbol': 'SPY', 'interval': '1day', 'outputsize': 600, 'apikey': tk})}", t=60)
try:
    j = json.loads(b)
    v = j.get("values") or []
    print(f"== td SPY ts [{s}] n={len(v)} first={v[:1]} last={v[-1:]} {j.get('message', '')}")
except Exception:
    print("== td SPY ts", s, b[:300])

print("### Otros")
show("aaii", "https://www.aaii.com/sentimentsurvey/sent_results", n=1, tail=False)
show("naaim", "https://naaim.org/programs/naaim-exposure-index/", n=1, tail=False)
show("cboe putcall", "https://cdn.cboe.com/data/us/options/market_statistics/daily/2026-11-10_daily_options", n=0, tail=False)
