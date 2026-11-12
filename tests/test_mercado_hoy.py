"""«Mercado hoy»: lectura de cada fuente y cálculo del índice propio de miedo y codicia."""
import json
import math
from datetime import date, timedelta

from fetcher import mercado_hoy as MH


def dias(n, fin=date(2026, 11, 4)):
    """n días laborables que terminan en `fin`."""
    out, d = [], fin
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


# ------------------------------------------------------------ lectores
def test_fred_csv_y_json():
    csv_txt = "observation_date,VIXCLS\n2026-11-02,17.1\n2026-11-03,.\n2026-11-04,25.75\n"
    assert MH.parse_fred_csv(csv_txt) == [("2026-11-02", 17.1), ("2026-11-04", 25.75)]
    js = json.dumps({"observations": [{"date": "2026-11-03", "value": "."}, {"date": "2026-11-04", "value": "7430.43"}]})
    assert MH.parse_fred_json(js) == [("2026-11-04", 7430.43)]


def test_tesoro_varias_columnas():
    txt = '﻿Date,"1 Mo","5 Yr","10 Yr"\n11/04/2026,4.0,4.619,4.828\n11/03/2026,4.0,4.688,4.893\n'
    assert MH.parse_treasury(txt, "5 Yr") == [("2026-11-03", 4.688), ("2026-11-04", 4.619)]
    assert MH.parse_treasury(txt, "10 Yr")[-1] == ("2026-11-04", 4.828)


def test_ofr():
    txt = "Date,OFR FSI,Credit,Equity valuation\n2026-11-02,-1.2,0.1,-0.5\n2026-11-03,0.4,0.2,0.1\n"
    assert MH.parse_ofr(txt) == [("2026-11-02", -1.2), ("2026-11-03", 0.4)]


AAII_HTML = """<html><head><script>var x="Bullish 99%";</script></head><body>
<h2>This week's results</h2><p>Week ending November 4, 2026</p>
<div class="b"><span>Bullish</span> <strong>34.1%</strong> <small>Avg 37.5%</small></div>
<div><span>Neutral</span> <strong>17.5%</strong> <small>Avg 31.0%</small></div>
<div><span>Bearish</span> <strong>48.4%</strong> <small>Avg 31.5%</small></div>
<table><tr><td>11/4/2026</td><td>34.1%</td></tr></table></body></html>"""


def test_aaii():
    a = MH.parse_aaii(AAII_HTML)
    assert a["alcistas"] == 34.1 and a["neutrales"] == 17.5 and a["bajistas"] == 48.4
    assert a["fecha"] == "2026-11-04" and a["diferencial"] == -14.3
    assert a["medias"] == {"alcistas": 37.5, "neutrales": 31.0, "bajistas": 31.5}


def test_aaii_rechaza_porcentajes_que_no_suman_100():
    assert MH.parse_aaii("<p>Bullish 60%</p><p>Neutral 60%</p><p>Bearish 60%</p>") is None
    assert MH.parse_aaii("<p>Página de acceso</p>") is None


def test_cboe():
    js = json.dumps({"ratios": [{"name": "EQUITY PUT/CALL RATIO", "value": "0.61"},
                                {"name": "TOTAL PUT/CALL RATIO", "value": "0.93"}]})
    assert MH.parse_cboe(js) == 0.93
    assert MH.parse_cboe("<html>") is None


# ------------------------------------------------------------ índice de miedo y codicia
def mercado(n=800, crash=False):
    ds = dias(n)
    sp, vix, hy, ig, y10 = [], [], [], [], []
    for i, d in enumerate(ds):
        p = 4000 * (1.0004 ** i) * (1 + 0.01 * math.sin(i / 7))
        v, h, y = 16 + 2 * math.sin(i / 11), 3.2 + 0.2 * math.sin(i / 13), 4.2 + 0.1 * math.sin(i / 17)
        k = i - (n - 15)
        if crash and k > 0:            # últimas dos semanas: caída, volatilidad y huida a los bonos
            p *= 1 - 0.012 * k
            v *= 1 + 0.08 * k
            h += 0.12 * k
            y -= 0.03 * k
        sp.append((d, p)); vix.append((d, v)); hy.append((d, h)); ig.append((d, 1.0)); y10.append((d, y))
    return sp, vix, hy, ig, y10


def test_miedo_codicia_tranquilo_y_pánico():
    r = MH.miedo_codicia(*mercado())
    calma = [v for v in r["total"] if v is not None][-1]
    r2 = MH.miedo_codicia(*mercado(crash=True))
    panico = [v for v in r2["total"] if v is not None][-1]
    assert panico < 25 < calma
    assert MH.etiqueta(panico) == "Miedo extremo"
    for k in ("impulso", "volatilidad", "bonos_basura", "refugio"):
        assert r2["puntuaciones"][k][-1] <= 10, k
    assert r2["puntuaciones"]["put_call"][-1] is None       # sin datos del Cboe no se inventa


def test_putcall_por_tramos_y_resumen():
    assert MH.puntuar_putcall(1.3) == 0 and MH.puntuar_putcall(0.6) == 100
    assert abs(MH.puntuar_putcall(0.95) - 50) < 1e-9
    sp, vix, hy, ig, y10 = mercado()
    pc = [(d, 0.95) for d, _ in sp[-10:]]
    r = MH.miedo_codicia(sp, vix, hy, ig, y10, pc)
    assert r["puntuaciones"]["put_call"][-1] == 50.0
    fu = {k: ("x", "https://x") for k in MH.COMPONENTES}
    s = MH.resumen_miedo_codicia(r, fu)
    assert s["n_componentes"] == 5 and s["fecha"] == sp[-1][0]
    assert s["hace_1s"]["fecha"] == sp[-6][0] and s["hace_1m"]["fecha"] == sp[-22][0]
    assert 0 <= s["valor"] <= 100 and s["etiqueta"] == MH.etiqueta(s["valor"])
    assert len(s["serie"]) == 60


def test_etiquetas_como_cnn():
    assert [MH.etiqueta(v) for v in (10, 30, 50, 60, 90)] == ["Miedo extremo", "Miedo", "Neutral", "Codicia", "Codicia extrema"]


# ------------------------------------------------------------ fuentes nuevas
def test_cboe_csv_y_bce():
    vix = "DATE,OPEN,HIGH,LOW,CLOSE\n11/10/2026,19.76,21.61,19.29,19.460000\n11/11/2026,18.81,18.96,17.33,17.490000\n"
    assert MH.parse_cboe_csv(vix) == [("2026-11-10", 19.46), ("2026-11-11", 17.49)]
    ovx = "DATE,OVX\n11/11/2026,51.260000\n11/10/2026,53.1\n"
    assert MH.parse_cboe_csv(ovx) == [("2026-11-10", 53.1), ("2026-11-11", 51.26)]
    ecb = ("KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
           "YC.B.U2,B,2026-11-10,3.3308865271,A\nYC.B.U2,B,2026-11-11,3.3400829714,A\n")
    assert MH.parse_ecb_csv(ecb) == [("2026-11-10", 3.3309), ("2026-11-11", 3.3401)]


def test_twelvedata_en_lote_y_serie():
    llamadas, esperas = [], []

    def http(url, **k):
        llamadas.append(url)
        if "time_series" in url:
            return json.dumps({"values": [{"datetime": "2026-11-11", "close": "759.81"}, {"datetime": "2026-11-10", "close": "750.0"}]})
        return json.dumps({"EUR/USD": {"close": "1.10781", "previous_close": "1.10933", "datetime": "2026-11-12"},
                           "XAG/USD": {"code": 400, "status": "error", "message": "**symbol** XAG/USD is not available with your plan"}})
    f = MH.Fuentes(env={"TWELVEDATA_API_KEY": "x"}, http=http, sleep=esperas.append)
    assert f.td_serie("SPY") == [("2026-11-10", 750.0), ("2026-11-11", 759.81)]
    q = f.twelvedata(["EUR/USD", "XAG/USD"])
    assert q["EUR/USD"] == {"valor": 1.10781, "anterior": 1.10933, "fecha": "2026-11-12"}
    assert isinstance(q["XAG/USD"], RuntimeError) and "plan" in str(q["XAG/USD"])
    assert esperas == [62] and len(llamadas) == 2        # la segunda petición espera al minuto siguiente


def test_temas_apuntan_a_indicadores_existentes():
    ids = {x["id"] for x in MH.INDICADORES}
    assert len(ids) == len(MH.INDICADORES)
    for g, t in MH.TEMAS.items():
        assert g in MH.GRUPOS and t["top"] in ids and len(t["resto"]) == 4 and set(t["resto"]) <= ids
        assert all(x["grupo"] == g for x in MH.INDICADORES if x["id"] in [t["top"], *t["resto"]])
    assert sum(x["origen"] == "twelvedata" for x in MH.INDICADORES) <= 7      # + la serie del SPY = 8 créditos/min


# ------------------------------------------------------------ construcción del JSON
class Falsas(MH.Fuentes):
    def __init__(self, fallan=()):
        super().__init__(env={}, hoy=date(2026, 11, 5), sleep=lambda s: None)
        self.fallan = set(fallan)
        self.m = dict(zip(("SP500", "VIXCLS", "BAMLH0A0HYM2", "BAMLC0A0CM", "DGS10"), mercado()))
        d = [x for x, _ in self.m["SP500"]]
        for sid in ("DTWEXBGS", "MORTGAGE30US", "DCOILBRENTEU", "DHHNGSP"):
            self.m[sid] = [(x, 50.0) for x in d[-30:]]
        self.m.update(NASDAQCOM=[(x, 20000.0 + i) for i, x in enumerate(d)], DCOILWTICO=[(x, 88.0) for x in d[:-1]] + [(d[-1], 90.2)])
        self.pedidos = []

    def _f(self, k):
        self.pedidos.append(k)
        if k in self.fallan:
            raise RuntimeError("HTTP 503")

    def fred(self, sid, desde):
        self._f(sid)
        return self.m[sid]

    def tesoro(self, col):
        self._f("tesoro")
        return [("2026-11-03", 4.893 if col == "10 Yr" else 4.688), ("2026-11-04", 4.828 if col == "10 Yr" else 4.619)]

    def finnhub(self, sym):
        self._f(sym)
        return {"valor": 77.22, "anterior": 77.52, "fecha": "2026-11-05"}

    def twelvedata(self, syms):
        self._f("td")
        return {k: {"valor": 1.1223, "anterior": 1.1229, "fecha": "2026-11-05"} for k in syms}

    def td_serie(self, sym, n=800):
        self._f("td_serie")
        return [(d, v / 10) for d, v in self.m["SP500"]]

    def cboe(self, sym):
        self._f("cboe:" + sym)
        return self.m["VIXCLS"] if sym == "VIX" else [("2026-11-03", 20.0), ("2026-11-04", 21.0)]

    def ecb(self, key, n=30):
        self._f("ecb")
        return [("2026-11-03", 3.3), ("2026-11-04", 3.34)]

    def ofr(self):
        self._f("ofr")
        return [("2026-10-27", -1.5), ("2026-11-02", -0.8), ("2026-11-03", 1.1)]

    def aaii(self):
        self._f("aaii")
        return MH.parse_aaii(AAII_HTML)

    def putcall(self, ya=None):
        self._f("cboe")
        return []


def test_build_completo():
    f = Falsas()
    out = MH.build(f)
    ids = [i["id"] for i in out["indicadores"]]
    assert "move" not in ids and len(ids) == len(MH.INDICADORES) - 1
    us10 = next(i for i in out["indicadores"] if i["id"] == "us10y")
    assert us10["valor"] == 4.828 and "var_pct" not in us10 and abs(us10["var"] + 0.065) < 1e-9
    assert us10["seccion"] == "Deuda pública" and us10["serie"][-1] == ["2026-11-04", 4.828]
    wti = next(i for i in out["indicadores"] if i["id"] == "wti")
    assert wti["var_pct"] == round((90.2 / 88 - 1) * 100, 2) and wti["url"].endswith("DCOILWTICO")
    assert wti["vivo"] == {"ticker": "USO", "modo": "ref"} and wti["nota"]
    hyg = next(i for i in out["indicadores"] if i["id"] == "hyg")
    assert hyg["vivo"] == {"ticker": "HYG", "modo": "directo"} and "serie" not in hyg
    vix = next(i for i in out["indicadores"] if i["id"] == "vix")
    assert vix["fuente"] == "Cboe" and vix["grupo"] == "volatilidad"
    assert out["temas"]["bonos"]["top"] == "us10y" and out["esquema"] == 2
    assert f.pedidos.index("td_serie") < f.pedidos.index("td") and f.pedidos.count("td") == 1
    S = out["sentimiento"]
    assert S["aaii"]["bajistas"] == 48.4 and S["estres_ofr"]["valor"] == 1.1 and S["estres_ofr"]["hace_1s"] == -1.5
    mc = S["miedo_codicia"]
    assert mc["n_componentes"] == 4
    comp = {c["id"]: c for c in mc["componentes"]}
    assert "Twelve Data" in comp["impulso"]["fuente"] and comp["volatilidad"]["fuente"] == "VIX · Cboe"
    assert "SP500" not in f.pedidos and "VIXCLS" not in f.pedidos       # FRED solo como respaldo
    assert any("put/call" in a for a in out["avisos"])


def test_miedo_codicia_vuelve_a_fred_si_falla_twelvedata():
    f = Falsas(fallan={"td_serie", "cboe:VIX"})
    out = MH.build(f)
    comp = {c["id"]: c for c in out["sentimiento"]["miedo_codicia"]["componentes"]}
    assert "FRED" in comp["impulso"]["fuente"] and "FRED" in comp["volatilidad"]["fuente"]
    assert any(a.startswith("Serie diaria del SPY") for a in out["avisos"])


def test_build_conserva_lo_anterior_si_falla_una_fuente():
    prev = MH.build(Falsas())
    out = MH.build(Falsas(fallan={"HYG", "aaii", "ofr", "td"}), prev)
    hyg = next(i for i in out["indicadores"] if i["id"] == "hyg")
    assert hyg["desactualizado"] and hyg["valor"] == 77.22
    eur = next(i for i in out["indicadores"] if i["id"] == "eurusd")
    assert eur["desactualizado"] and eur["valor"] == 1.1223
    assert out["sentimiento"]["aaii"]["fecha"] == "2026-11-04"          # se mantiene la última semana leída
    assert any(a.startswith("Bonos high yield") for a in out["avisos"])
    assert any(a.startswith("Encuesta AAII") for a in out["avisos"])


def test_sin_claves_avisa_sin_romper():
    f = MH.Fuentes(env={}, http=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin red")), sleep=lambda s: None)
    out = MH.build(f)
    assert out["indicadores"] == [] and out["sentimiento"] == {}
    assert any("FINNHUB_API_KEY" in a for a in out["avisos"]) and any("TWELVEDATA_API_KEY" in a for a in out["avisos"])


def test_fred_caido_no_insiste():
    llamadas = []

    def http(url, **k):
        llamadas.append(url)
        if "stlouisfed" in url:
            raise RuntimeError("fred.stlouisfed.org: The read operation timed out")
        raise RuntimeError("sin red")
    out = MH.build(MH.Fuentes(env={}, http=http, sleep=lambda s: None))
    assert sum("stlouisfed" in u for u in llamadas) == 1
    assert any("FRED_API_KEY" in a for a in out["avisos"])
