"""Diagnóstico temporal: compara métodos de puntuación del índice propio de miedo y codicia."""
import math
import statistics as st
from datetime import date, timedelta

from fetcher import mercado_hoy as MH

f = MH.Fuentes()
desde = (f.hoy - timedelta(days=6 * 366)).isoformat()
S = {k: f.fred(k, desde) for k in ("SP500", "VIXCLS", "BAMLH0A0HYM2", "BAMLC0A0CM", "DGS10")}
sp, vix, hy, ig, y10 = (MH.Serie(S[k]) for k in ("SP500", "VIXCLS", "BAMLH0A0HYM2", "BAMLC0A0CM", "DGS10"))
ma125 = MH._media_movil(sp.v, 125)
vma = MH._media_movil(vix.v, 50)
vr = MH.Serie([(vix.d[i], vix.v[i] / vma[i] - 1) for i in range(len(vix)) if vma[i]])
met = {k: [] for k in ("impulso", "volatilidad", "bonos_basura", "refugio")}
for i, d in enumerate(sp.d):
    met["impulso"].append(sp.v[i] / ma125[i] - 1 if ma125[i] else None)
    met["volatilidad"].append(vr.en(d))
    h, g = hy.en(d), ig.en(d)
    met["bonos_basura"].append(h - g if h is not None and g is not None else None)
    r = None
    if i >= 20:
        a, b = y10.en(d), y10.en(sp.d[i - 20])
        if a is not None and b is not None:
            r = (sp.v[i] / sp.v[i - 20] - 1) * 100 - (-MH.DURACION_10A * (a - b) + b * 20 / 252)
    met["refugio"].append(r)
inv = {"volatilidad", "bonos_basura"}
Phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))


def score(k, i, metodo, ventana):
    xs = met[k]
    x = xs[i]
    if x is None:
        return None
    w = [v for v in xs[max(0, i - ventana + 1): i + 1] if v is not None]
    if len(w) < 60:
        return None
    if metodo == "pct":
        p = 100 * sum(1 for v in w if v <= x) / len(w)
    else:
        m, sd = st.mean(w), st.pstdev(w) or 1
        z = (x - m) / sd
        p = 100 * Phi(z) if metodo == "zphi" else max(0, min(100, 50 + 25 * z))
    return 100 - p if k in inv else p


METODOS = [("pct", 504, "percentil 2a (actual)"), ("pct", 252, "percentil 1a"), ("zphi", 252, "z 1a·normal"),
           ("zlin", 252, "z 1a·lineal"), ("zlin", 504, "z 2a·lineal")]
n = len(sp.d)
idx = list(range(n - 504, n))
res = {m[2]: [] for m in METODOS}
for i in idx:
    for met_, ven, nom in METODOS:
        vs = [score(k, i, met_, ven) for k in met]
        vs = [v for v in vs if v is not None]
        res[nom].append(sum(vs) / len(vs) if len(vs) >= 3 else None)
print("Últimas 25 sesiones")
print("fecha       " + " | ".join(f"{m[2]:>20}" for m in METODOS))
for j in range(len(idx) - 25, len(idx)):
    print(sp.d[idx[j]] + "  " + " | ".join(f"{(res[m[2]][j] or float('nan')):20.1f}" for m in METODOS))
print("\nReparto en los últimos 2 años (% de sesiones): miedo ext <25 | miedo 25-45 | neutral | codicia 55-75 | codicia ext >75 | media")
for m in METODOS:
    v = [x for x in res[m[2]] if x is not None]
    b = [sum(1 for x in v if lo <= x < hi) / len(v) * 100 for lo, hi in ((0, 25), (25, 45), (45, 55), (55, 75), (75, 101))]
    print(f"{m[2]:>22}: " + " | ".join(f"{x:5.1f}" for x in b) + f" | {st.mean(v):5.1f}")
print("\nComponentes hoy:", {k: round(met[k][-1], 4) if met[k][-1] is not None else None for k in met})
for met_, ven, nom in METODOS:
    print(f"{nom:>22}:", {k: round(score(k, n - 1, met_, ven) or -1, 1) for k in met})
