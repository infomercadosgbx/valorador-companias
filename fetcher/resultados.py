"""Informe de resultados de cada presentación trimestral.

Escribe data/resultados/<TICKER>/<periodo>.json (p. ej. 3T26.json) y el índice
data/resultados/<TICKER>/index.json. La página resultados.html lo convierte en
un informe de 2 páginas A4 y el Action lo guarda también en PDF.

De dónde sale cada bloque:
  - Cifras del trimestre: XBRL del 10-Q/10-K (definitivo). El día de resultados,
    mientras no hay 10-Q, de las tablas de la nota (8-K, Exhibit 99.1), marcadas
    como provisionales. Cuando llega el 10-Q, la siguiente ejecución las sustituye.
  - Estimaciones: manual/<T>.json («estimaciones_resultados») > foto del consenso
    de Finnhub (data/estimaciones) > calendario de Finnhub > sorpresas de BPA.
  - Guía: el texto de la nota («Outlook» / «Guidance»), con las horquillas leídas.
  - Reacción en bolsa y 12 meses de cotización: data/<T>.json → historico_precio.
  - Segmentos y run-rate: XBRL con dimensiones (segments.py) y su histórico
    (data/resultados/<T>/_segmentos.json, se amplía cada trimestre).
  - Lectura del trimestre: tu resumen (analysis → mgmt.call) o, si aún no lo has
    actualizado, la propuesta pendiente (propuestas/<T>.json).
Nada se inventa: si falta un dato, el bloque queda «pendiente» y la web lo dice.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import estimaciones as EST
from . import nota_tablas as NT

ESQUEMA = 1
CONCEPTOS = [("ingresos", "Ingresos"), ("beneficio_operativo", "Beneficio operativo (EBIT)"),
             ("beneficio_neto", "Beneficio neto"), ("bpa_diluido", "BPA diluido")]
GENERIC = {"us-gaap:ProductMember", "us-gaap:ServiceMember", "srt:ProductMember", "srt:ServiceMember"}


# ---------------------------------------------------------------- utilidades
def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _es(x, nd=2):
    return f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(a, b):
    return round((a / b - 1) * 100, 2) if a is not None and b not in (None, 0) and b > 0 else None


def _lab(label: str, dy=0, dq=0):
    """«3T26» desplazado dy años y dq trimestres."""
    m = re.fullmatch(r"(\d)T(\d{2})", label or "")
    if not m:
        return None
    q, y = int(m.group(1)) - 1 + dq, int(m.group(2)) + dy
    y += q // 4
    q %= 4
    return f"{q + 1}T{y % 100:02d}"


def _point(rec, concept, label):
    for p in ((rec.get("resultados") or {}).get(concept) or {}).get("trimestral") or []:
        if p.get("periodo") == label:
            return p
    return None


def _val(rec, concept, label):
    p = _point(rec, concept, label)
    return p.get("valor") if p else None


def _norm(s):
    s = re.sub(r"\b(segment|segments|member|services?)\b", "", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------------------------------------------------------------- trimestre
def target_quarter(rec):
    """(etiqueta, fin del periodo, definitivo) del trimestre que presenta el último 8-K."""
    k8 = rec.get("ultimo_8k_resultados") or {}
    F = _d(k8.get("fecha_presentacion"))
    Q = ((rec.get("resultados") or {}).get("ingresos") or {}).get("trimestral") or []
    if not F or not Q:
        return None
    hit = [p for p in Q if 0 <= (F - _d(p["periodo_fin"])).days <= 80]
    if hit:
        return hit[-1]["periodo"], hit[-1]["periodo_fin"], True
    last = Q[-1]
    end = _d(last["periodo_fin"]) + timedelta(days=91)
    if not -15 <= (F - end).days <= 95:
        return None
    return _lab(last["periodo"], dq=1), end.isoformat(), False


# ---------------------------------------------------------------- cifras reportadas
def _cifra_xbrl(p, extra=None):
    out = {k: p.get(k) for k in ("valor", "fuente", "url", "fecha_presentacion", "etiqueta", "periodo",
                                 "periodo_inicio", "periodo_fin", "formulario", "derivado") if p.get(k) is not None}
    out.update(extra or {})
    return out


def reported(rec, label, definitivo, html=None, cached=None):
    """{concepto: cifra} del trimestre. Si no es definitivo, lee la nota (o reutiliza «cached»)."""
    out, avisos = {}, []
    if definitivo:
        for k, _ in CONCEPTOS:
            p = _point(rec, k, label)
            if p:
                out[k] = _cifra_xbrl(p)
        return out, avisos
    if cached is not None:
        return cached, avisos
    k8 = rec.get("ultimo_8k_resultados") or {}
    if not html:
        avisos.append("Las cifras del trimestre aún no están en la SEC (falta el 10-Q) y no se pudo leer la nota de resultados.")
        return out, avisos
    prevq = _lab(label, dq=-1)
    ref = {k: _val(rec, k, prevq) for k, _ in CONCEPTOS}
    ref = {k: v for k, v in ref.items() if v}
    got = NT.extract(html, ref)
    base = {"fuente": "SEC EDGAR · 8-K, Exhibit 99.1 (provisional)", "url": k8.get("url_ex99_1"),
            "fecha_presentacion": k8.get("fecha_presentacion"), "periodo": label, "provisional": True}
    for k, _ in CONCEPTOS + [("beneficio_antes_impuestos", ""), ("gastos_intereses", "")]:
        g = got.get(k)
        if not g:
            continue
        v = g["valor"]
        cif = dict(base, valor=v, etiqueta=f"Nota de resultados: fila «{g['fila']}»")
        if g.get("periodo") == "A":
            # solo cifras anuales en la nota (típico del 4T): 4T = año − 1T − 2T − 3T de la SEC
            if k == "bpa_diluido" or not label.startswith("4T"):
                continue
            prev3 = [_val(rec, k, f"{q}T{label[2:]}") for q in (1, 2, 3)]
            if any(x is None for x in prev3):
                continue
            cif["valor"] = v - sum(prev3)
            cif["derivado"] = "Año (nota de resultados) − 1T − 2T − 3T (SEC)"
        if g.get("escala_deducida"):
            cif["nota"] = "Unidades deducidas comparando con el trimestre anterior (la tabla no las indica)."
        out[k] = cif
    r = out.get("ingresos")
    if r and ref.get("ingresos") and not 0.5 <= r["valor"] / ref["ingresos"] <= 2.0:
        avisos.append("Los ingresos leídos de la nota no encajan con el trimestre anterior; se descartan.")
        out.pop("ingresos")
    op = ((rec.get("resultados") or {}).get("beneficio_operativo") or {})
    if "beneficio_operativo" not in out and op.get("aproximado") and "beneficio_antes_impuestos" in out:
        pbt, it = out["beneficio_antes_impuestos"], out.get("gastos_intereses")
        out["beneficio_operativo"] = dict(base, valor=pbt["valor"] + abs(it["valor"] if it else 0),
                                          etiqueta="Nota de resultados: beneficio antes de impuestos + gastos por intereses",
                                          derivado="La compañía no publica beneficio operativo (EBIT aproximado)")
    out.pop("beneficio_antes_impuestos", None)
    out.pop("gastos_intereses", None)
    missing = [n for k, n in CONCEPTOS if k not in out]
    if missing:
        avisos.append(f"No se encontró en la nota: {', '.join(missing).lower()}. Llegará con el 10-Q.")
    return out, avisos


# ---------------------------------------------------------------- estimaciones
def estimates(root, ticker, rec, label, F, manual, provider=None, prev=None):
    """{concepto: {valor, fuente}} y lo que se guardó del calendario de Finnhub."""
    est = {}
    man = EST.manual_for(manual, label)
    snap = EST.for_report(root, ticker, F)
    cal = (prev or {}).get("_calendario_finnhub")
    if cal is None and provider is not None and (date.today() - F).days <= 31:
        try:
            cal = provider.earnings_on(ticker, F) or {}
        except Exception:  # noqa: BLE001  secundario
            cal = {}
    cal = cal or {}
    pe = {r["concepto"]: r.get("estimado") for r in (prev or {}).get("tabla") or [] if r.get("estimado")}
    mfuente = f"manual · {man.get('fuente')}" if man and man.get("fuente") else "manual"

    def pick(k, man_key=None, mult=1.0, snap_key=None, cal_key=None, sorp=False):
        if man and man_key and man.get(man_key) is not None:
            return {"valor": float(man[man_key]) * mult, "fuente": mfuente, "manual": True,
                    "fecha": man.get("fecha") or None}
        if snap and snap_key and (snap.get("finnhub") or {}).get(snap_key) is not None:
            f = snap["finnhub"]
            return {"valor": f[snap_key], "fuente": f"Finnhub · consenso del {f.get('capturado')}", "url": f.get("url")}
        if cal_key and cal.get(cal_key) is not None:
            return {"valor": cal[cal_key], "fuente": "Finnhub · calendario de resultados",
                    "url": "https://finnhub.io/docs/api/earnings-calendar"}
        if sorp:
            end = None
            tq = target_quarter(rec)
            if tq:
                end = _d(tq[1])
            for s in ((rec.get("resultados_previstos") or {}).get("sorpresas") or []):
                if end and s.get("bpa_estimado") is not None and abs((_d(s.get("periodo")) - end).days) <= 20:
                    return {"valor": s["bpa_estimado"], "fuente": "Finnhub · historial de sorpresas de BPA",
                            "url": "https://finnhub.io/docs/api/company-earnings"}
        return pe.get(k)

    est["ingresos"] = pick("ingresos", "ingresos_M", 1e6, "ingresos", "ingresos_estimados")
    est["bpa_diluido"] = pick("bpa_diluido", "bpa", 1.0, "bpa", "bpa_estimado", sorp=True)
    est["beneficio_operativo"] = pick("beneficio_operativo", "beneficio_operativo_M", 1e6)
    est["beneficio_neto"] = pe.get("beneficio_neto")
    segs = {}
    for name, v in ((man or {}).get("segmentos_M") or {}).items():
        if v is not None:
            segs[name] = {"valor": float(v) * 1e6, "fuente": mfuente, "manual": True}
    for r in (prev or {}).get("tabla") or []:
        if r.get("tipo") == "segmento" and r.get("estimado") and r["nombre"] not in segs and not man:
            segs[r["nombre"]] = r["estimado"]
    hora = (snap or {}).get("hora_codigo") or cal.get("hora")
    guia_est = {}
    if man and man.get("guia_ingresos_M") is not None:
        guia_est["ingresos"] = {"valor": float(man["guia_ingresos_M"]) * 1e6, "fuente": mfuente, "manual": True}
    if man and man.get("guia_beneficio_operativo_M") is not None:
        guia_est["beneficio_operativo"] = {"valor": float(man["guia_beneficio_operativo_M"]) * 1e6, "fuente": mfuente, "manual": True}
    return est, segs, cal, hora, guia_est, snap


def verdict(rep, est, tol=0.0005):
    if rep is None or est is None or not est.get("valor"):
        return None, None
    dif = (rep / est["valor"] - 1) * 100 if est["valor"] > 0 else None
    if dif is None:
        return None, None
    if abs(dif) < tol * 100:
        return round(dif, 2), "En línea"
    return round(dif, 2), "Beat" if dif > 0 else "Miss"


# ---------------------------------------------------------------- segmentos
def _seg_lists(rec):
    s = rec.get("segmentos") or {}
    return [("segmento", x) for x in s.get("segmento") or []] + [("producto", x) for x in s.get("producto") or []]


def _seg_val(item, label, key="trimestral"):
    for p in item.get(key) or []:
        if p.get("periodo") == label:
            return p.get("valor")
    return None


def find_segment(rec, name):
    n = _norm(name)
    best = None
    for tipo, it in _seg_lists(rec):
        m = _norm(it.get("nombre"))
        if m == n:
            return tipo, it
        if n and (n in m or m in n) and best is None:
            best = (tipo, it)
    return best


def breakdown(rec, label, total):
    """Crecimiento interanual y peso de cada línea de producto y segmento en el trimestre."""
    ya = _lab(label, dy=-1)
    out = {"producto": [], "segmento": []}
    for tipo, it in _seg_lists(rec):
        if it.get("ajuste"):
            continue
        v = _seg_val(it, label)
        if v is None:
            continue
        vya = _seg_val(it, ya)
        op, opya = _seg_val(it, label, "operativo_trimestral"), _seg_val(it, ya, "operativo_trimestral")
        out[tipo].append({"nombre": it["nombre"], "miembro": it.get("miembro"), "valor": v, "anio_anterior": vya,
                          "interanual_pct": _pct(v, vya), "peso_pct": round(v / total * 100, 1) if total else None,
                          "margen_operativo_pct": round(op / v * 100, 1) if op is not None and v else None,
                          "margen_operativo_ya_pct": round(opya / vya * 100, 1) if opya is not None and vya else None})
    for k in ("producto", "segmento"):   # un único segmento que es toda la compañía no aporta nada
        if len(out[k]) == 1 and (out[k][0]["peso_pct"] or 0) >= 95:
            out[k] = []
    if len([x for x in out["producto"] if x["miembro"] not in GENERIC]) >= 3:
        out["producto"] = [x for x in out["producto"] if x["miembro"] not in GENERIC]
    for k in out:
        out[k].sort(key=lambda x: -(x["valor"] or 0))
    return out


def star_segment(rec, label, total, clave=None):
    if clave:
        f = find_segment(rec, clave)
        if f:
            return f[1]
    for tipo in ("segmento", "producto"):
        cands = []
        for t, it in _seg_lists(rec):
            if t != tipo or it.get("ajuste") or it.get("miembro") in GENERIC:
                continue
            v, vya = _seg_val(it, label), _seg_val(it, _lab(label, dy=-1))
            if v and vya and total and 0.10 <= v / total < 0.95:
                cands.append((_pct(v, vya), it))
        if cands:
            return max(cands, key=lambda c: c[0])[1]
    return None


def update_history(root, ticker, rec, client=None, subs=None):
    """Mantiene data/resultados/<T>/_segmentos.json: serie larga por segmento.
    La primera vez (si hay cliente de la SEC) lee unos 4 años de informes."""
    from . import segments as SEG
    path = root / "data" / "resultados" / ticker.upper() / "_segmentos.json"
    H = _load(path) or {"_nota": "Histórico de ingresos y beneficio operativo por segmento (SEC, XBRL con dimensiones). Lo mantiene el Action.",
                        "miembros": {}}
    M = H["miembros"]

    def merge(tipo, it):
        m = M.setdefault(it["miembro"], {"nombre": it["nombre"], "tipo": tipo, "trimestral": {}, "operativo": {}})
        m["nombre"] = it["nombre"]
        for key, dst in (("trimestral", "trimestral"), ("operativo_trimestral", "operativo")):
            for p in it.get(key) or []:
                m[dst][p["periodo_fin"]] = {"periodo": p["periodo"], "valor": p["valor"]}

    if not H.get("historico_leido") and client is not None:
        fyem = 12
        an = ((rec.get("resultados") or {}).get("ingresos") or {}).get("anual") or []
        if an:
            fyem = _d(an[-1]["periodo_fin"]).month
        try:
            subs = subs or client.submissions(rec["cik"])
            h = SEG.history(client, rec["cik"], subs, fye_month=fyem)
            for tipo in ("segmento", "producto"):
                for it in (h or {}).get(tipo) or []:
                    merge(tipo, it)
            H["historico_leido"] = date.today().isoformat()
        except Exception as e:  # noqa: BLE001  secundario: se reintenta la próxima vez
            H["error_historico"] = f"{type(e).__name__}: {e}"[:300]
    for tipo, it in _seg_lists(rec):
        merge(tipo, it)
    for m in M.values():
        for key in ("trimestral", "operativo"):
            m[key] = dict(sorted(m[key].items())[-60:])
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(H, ensure_ascii=False, indent=1) + "\n"
    changed = not path.exists() or path.read_text(encoding="utf-8") != txt
    if changed:
        path.write_text(txt, encoding="utf-8")
    return H, changed


def star_series(H, member, upto_end, n=20):
    m = (H.get("miembros") or {}).get(member)
    if not m:
        return []
    pts = [(k, v) for k, v in sorted(m["trimestral"].items()) if k <= upto_end][-n - 4:]
    by_end = dict(pts)
    out = []
    for k, v in pts:
        e = _d(k)
        ya = next((x for kk, x in by_end.items() if abs((_d(kk) - (e - timedelta(days=365))).days) <= 12), None)
        op = m["operativo"].get(k)
        out.append({"periodo": v["periodo"], "periodo_fin": k, "valor": v["valor"], "run_rate": v["valor"] * 4,
                    "interanual_pct": _pct(v["valor"], ya["valor"] if ya else None),
                    "margen_operativo_pct": round(op["valor"] / v["valor"] * 100, 1) if op and v["valor"] else None})
    out = out[-n:]
    # solo el tramo continuo final: un trimestre que falta no puede verse como un salto en el gráfico
    for i in range(len(out) - 1, 0, -1):
        if (_d(out[i]["periodo_fin"]) - _d(out[i - 1]["periodo_fin"])).days > 100:
            return out[i:]
    return out


# ---------------------------------------------------------------- guía
_MULT = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "m": 1e6, "mm": 1e6}
_GKIND = [("ingresos", r"net sales|revenues?|total revenue"),
          ("beneficio_operativo", r"operating income|operating profit|income from operations"),
          ("bpa", r"(?:diluted )?(?:eps|earnings per share|net income per share)"),
          ("ebitda", r"adjusted ebitda|ebitda")]
_RANGE = re.compile(r"\$\s?([\d.,]+)\s*(billion|million|bn|mm|b|m)?\s*(?:and|to|-|–|—)\s*\$\s?([\d.,]+)\s*(billion|million|bn|mm|b|m)?", re.I)
_APPROX = re.compile(r"(?:approximately|about|of|be)\s+\$\s?([\d.,]+)\s*(billion|million|bn|mm|b|m)?", re.I)


def parse_guidance(textos):
    """Horquillas de la guía: [{concepto, min, max, medio, texto}] (en dólares; BPA en $/acción)."""
    out, seen = [], set()
    for t in textos or []:
        for sent in re.split(r"(?<=[.;])\s+", t):
            low = sent.lower()
            for k, rx in _GKIND:
                if k in seen or not re.search(rx, low):
                    continue
                if k == "ingresos" and re.search(r"advertis|segment|cloud|aws|services revenue", low) and not re.search(r"net sales|total revenue", low):
                    continue
                if k != "ebitda" and re.search(r"ebitda", low) and not re.search(rx.replace("|ebitda", ""), low.replace("ebitda", "")):
                    continue
                m = _RANGE.search(sent)
                if m:
                    a, ua, b, ub = m.groups()
                    mul = 1.0 if k == "bpa" else _MULT.get((ub or ua or "").lower(), 1.0)
                    if k != "bpa" and not (ua or ub):
                        mul = 1e6   # tablas de guía sin unidad: en millones («$6,800 - $7,600»)
                    lo, hi = float(a.replace(",", "")) * (1.0 if k == "bpa" else _MULT.get((ua or ub or "").lower(), mul)), float(b.replace(",", "")) * mul
                    out.append({"concepto": k, "min": lo, "max": hi, "medio": (lo + hi) / 2, "texto": sent.strip()[:400]})
                    seen.add(k)
                    continue
                m = _APPROX.search(sent)
                if m and k != "bpa":
                    v = float(m.group(1).replace(",", "")) * _MULT.get((m.group(2) or "").lower(), 1.0)
                    if v >= 1e6:
                        out.append({"concepto": k, "min": v, "max": v, "medio": v, "texto": sent.strip()[:400]})
                        seen.add(k)
    return out


# ---------------------------------------------------------------- cotización
def reaction(rec, F, hora, prev_reac=None):
    """Cierre anterior y posterior a la presentación. Tras el cierre (amc): día F frente al siguiente."""
    serie = ((rec.get("historico_precio") or {}).get("serie")) or []
    pts = [(_d(x[0]), x[1]) for x in serie if x and x[1] is not None]
    if not pts:
        return None, []
    amc = (hora or "amc") != "bmo"
    if amc:
        before = [p for p in pts if p[0] <= F]
        after = [p for p in pts if p[0] > F]
    else:
        before = [p for p in pts if p[0] < F]
        after = [p for p in pts if p[0] >= F]
    if not before:
        return None, []
    b = before[-1]
    out = {"hora": "tras el cierre" if amc else "antes de la apertura", "hora_supuesta": hora is None,
           "fecha_antes": b[0].isoformat(), "cierre_antes": b[1],
           "fuente": (rec.get("historico_precio") or {}).get("fuente") or "Twelve Data"}
    end = None
    if after:
        a = after[0]
        out.update({"fecha_despues": a[0].isoformat(), "cierre_despues": a[1], "variacion_pct": _pct(a[1], b[1]), "provisional": False})
        end = a[0]
    else:
        q = rec.get("precio") or {}
        if q.get("valor") and _d(q.get("fecha")) and _d(q["fecha"]) > b[0]:
            out.update({"fecha_despues": q["fecha"], "cierre_despues": q["valor"], "variacion_pct": _pct(q["valor"], b[1]),
                        "provisional": True, "fuente_despues": q.get("fuente") or "Finnhub"})
        else:
            out["provisional"] = True
        end = pts[-1][0]
    start = end - timedelta(days=365)
    win = [p for p in pts if start <= p[0] <= end]
    step = max(1, len(win) // 160)
    serie12 = [[p[0].isoformat(), round(p[1], 2)] for p in win[::step]]
    if win and serie12[-1][0] != win[-1][0].isoformat():
        serie12.append([win[-1][0].isoformat(), round(win[-1][1], 2)])
    return out, serie12


# ---------------------------------------------------------------- lectura del trimestre
def reading(root, ticker, analysis, periodo_fin, accn):
    call = ((analysis or {}).get("mgmt") or {}).get("call") or {}
    e = _d(periodo_fin)
    if call.get("periodEnd") and e and abs((_d(call["periodEnd"]) - e).days) <= 25:
        return {"estado": "revisada", "fuente": "Tu resumen de la presentación (Directiva)", **{k: call.get(k) for k in
                ("q", "date", "doc", "url", "nota", "dir", "ret", "guia", "cap") if call.get(k)}}
    prop = _load(root / "propuestas" / f"{ticker.upper()}.json")
    if prop and prop.get("informe_accn") == accn:
        for c in prop.get("cambios") or []:
            if c.get("campo") == "mgmt.call" and isinstance(c.get("valor"), dict):
                v = c["valor"]
                return {"estado": "propuesta", "fuente": "Propuesta pendiente de revisar (Claude, tras los resultados)",
                        **{k: v.get(k) for k in ("q", "date", "doc", "url", "nota", "dir", "ret", "guia", "cap") if v.get(k)}}
    return None


# ---------------------------------------------------------------- informe
def build(root: Path, company: dict, rec: dict, analysis=None, manual=None, client=None, provider=None, subs=None):
    """Devuelve (informe, historial_cambiado) o (None, False) si no hay presentación que reflejar."""
    t = company["ticker"].upper()
    if not rec or not rec.get("soportada", True):
        return None, False
    k8 = rec.get("ultimo_8k_resultados") or {}
    F = _d(k8.get("fecha_presentacion"))
    tq = target_quarter(rec)
    if not F or not tq:
        return None, False
    label, end, definitivo = tq
    path = root / "data" / "resultados" / t / f"{label}.json"
    prev = _load(path)
    if prev and prev.get("informe", {}).get("accn_8k") != k8.get("accn"):
        prev = None
    avisos = []

    # cifras
    cached = None
    if not definitivo and prev and prev.get("estado") == "provisional" and prev.get("_cifras_nota"):
        cached = prev["_cifras_nota"]
    html = None
    if not definitivo and cached is None and client is not None and k8.get("url_ex99_1"):
        try:
            html = client.get_text(k8["url_ex99_1"])
        except Exception:  # noqa: BLE001
            html = None
    rep, av = reported(rec, label, definitivo, html, cached)
    avisos += av
    total = (rep.get("ingresos") or {}).get("valor")

    # estimaciones
    est, segs_est, cal, hora, guia_est, snap = estimates(root, t, rec, label, F, manual, provider, prev)

    tabla = []
    for k, nombre in CONCEPTOS:
        r = rep.get(k)
        rv = r["valor"] if r else None
        ya = _val(rec, k, _lab(label, dy=-1))
        dif, res = verdict(rv, est.get(k))
        tabla.append({"concepto": k, "nombre": nombre, "tipo": "total", "reportado": r, "estimado": est.get(k),
                      "dif_pct": dif, "resultado": res, "anio_anterior": ya,
                      "interanual_pct": _pct(rv, ya) if k != "bpa_diluido" or (ya and ya > 0) else None})

    # El consenso de BPA suele ser «ajustado» (non-GAAP). Si el BPA real que da Finnhub
    # difiere del contable, la comparación se hace en la base del consenso y se explica.
    eps_row = next(r for r in tabla if r["concepto"] == "bpa_diluido")
    real = None
    for s_ in ((rec.get("resultados_previstos") or {}).get("sorpresas") or []):
        if s_.get("bpa_real") is not None and _d(s_.get("periodo")) and abs((_d(s_["periodo"]) - _d(end)).days) <= 20:
            real = {"valor": s_["bpa_real"], "fuente": "Finnhub · BPA real en la base del consenso", "url": "https://finnhub.io/docs/api/company-earnings"}
    if real is None and cal.get("bpa_real") is not None:
        real = {"valor": cal["bpa_real"], "fuente": "Finnhub · BPA real en la base del consenso", "url": "https://finnhub.io/docs/api/earnings-calendar"}
    gaap = (eps_row["reportado"] or {}).get("valor")
    if real and eps_row["estimado"] and not eps_row["estimado"].get("manual") and gaap is not None and \
            abs(real["valor"] - gaap) > max(0.02, abs(gaap) * 0.02):
        eps_row["comparable"] = real
        eps_row["dif_pct"], eps_row["resultado"] = verdict(real["valor"], eps_row["estimado"])
        eps_row["nota"] = (f"El consenso se refiere al BPA ajustado ({_es(real['valor'])} $ según Finnhub); "
                           f"el contable (GAAP) es {_es(gaap)} $.")
    rv_i = (next(r for r in tabla if r["concepto"] == "ingresos")["reportado"] or {}).get("valor")
    if rv_i and cal.get("ingresos_reales") and abs(cal["ingresos_reales"] / rv_i - 1) > 0.02:
        avisos.append("Los ingresos reales que da Finnhub difieren más de un 2% de los de la SEC; la tabla usa los de la SEC.")

    clave = EST.segmento_clave(manual)
    star = star_segment(rec, label, total, clave)
    seg_rows = dict(segs_est)
    if star and not any(_norm(n) == _norm(star["nombre"]) or _norm(star["nombre"]) in _norm(n) for n in seg_rows):
        seg_rows[star["nombre"]] = None
    pos = 1
    for name, e in seg_rows.items():
        f = find_segment(rec, name)
        v = _seg_val(f[1], label) if f else None
        vya = _seg_val(f[1], _lab(label, dy=-1)) if f else None
        rcif = None
        if v is not None:
            srcs = (rec.get("segmentos") or {}).get("informes") or []
            src = srcs[-1] if srcs else {}
            rcif = {"valor": v, "fuente": f"SEC EDGAR · {src.get('formulario', '10-Q')} (XBRL, segmentos)", "url": src.get("url"),
                    "fecha_presentacion": src.get("fecha_presentacion"), "periodo": label,
                    "etiqueta": f"{f[1].get('miembro')}"}
        dif, res = verdict(v, e)
        tabla.insert(pos, {"concepto": "segmento", "nombre": f[1]["nombre"] if f else name, "tipo": "segmento",
                           "reportado": rcif, "estimado": e, "dif_pct": dif, "resultado": res,
                           "anio_anterior": vya, "interanual_pct": _pct(v, vya),
                           "pendiente": None if v is not None else "Llega con el 10-Q (desglose por segmentos en XBRL)."})
        pos += 1

    # guía
    nota = k8.get("nota_resultados") if (k8.get("nota_resultados") or {}).get("accn") == k8.get("accn") else None
    gtxt = ((nota or {}).get("guia") or {}).get("texto") or []
    gpar = parse_guidance(gtxt)
    prev_guia = {g["concepto"]: g for g in ((prev or {}).get("guia") or {}).get("items") or []}
    E = (rec.get("resultados_previstos") or {}).get("proximos") or {}
    for g in gpar:
        e = guia_est.get(g["concepto"])
        if e is None and g["concepto"] == "ingresos":
            pg = prev_guia.get("ingresos") or {}
            if pg.get("estimado") and not pg["estimado"].get("manual"):
                e = pg["estimado"]   # congelado la primera vez
            elif E.get("ingresos_estimados") and _d(E.get("fecha")) and _d(E["fecha"]) > F and (date.today() - F).days <= 7:
                e = {"valor": E["ingresos_estimados"], "fuente": f"Finnhub · consenso del trimestre siguiente ({date.today().isoformat()})",
                     "url": "https://finnhub.io/docs/api/earnings-calendar"}
        if e is None and g["concepto"] in prev_guia and (prev_guia[g["concepto"]].get("estimado") or {}).get("valor"):
            e = prev_guia[g["concepto"]]["estimado"] if not prev_guia[g["concepto"]]["estimado"].get("manual") else None
        g["estimado"] = e
        g["dif_pct"], g["resultado"] = verdict(g["medio"], e)
    guia = {"items": gpar, "texto": gtxt, "titulo": ((nota or {}).get("guia") or {}).get("titulo"),
            "fuente": "SEC EDGAR · 8-K, Exhibit 99.1 (texto original)", "url": k8.get("url_ex99_1")} if gtxt else None

    # cotización
    reac, serie12 = reaction(rec, F, hora)
    q = rec.get("precio") or {}
    sh = (rec.get("acciones_en_circulacion") or {}).get("valor")
    px = (reac or {}).get("cierre_despues") or q.get("valor")
    cot = {"serie": serie12, "precio": px, "fecha_precio": (reac or {}).get("fecha_despues") or q.get("fecha"),
           "capitalizacion": px * sh if px and sh else None,
           "minimo_12m": min((p[1] for p in serie12), default=None), "maximo_12m": max((p[1] for p in serie12), default=None),
           "variacion_12m_pct": _pct(serie12[-1][1], serie12[0][1]) if len(serie12) > 1 else None,
           "fuente": (rec.get("historico_precio") or {}).get("fuente") or "Twelve Data"}

    # desglose, run-rate y márgenes
    H, hist_changed = update_history(root, t, rec, client, subs)
    des = breakdown(rec, label, total)
    estrella = None
    if star:
        estrella = {"nombre": star["nombre"], "miembro": star.get("miembro"), "elegido": "manual" if clave else "automático",
                    "serie": star_series(H, star.get("miembro"), end)}
    mq = []
    for p in (((rec.get("resultados") or {}).get("ingresos") or {}).get("trimestral") or [])[-12:]:
        op = _val(rec, "beneficio_operativo", p["periodo"])
        if op is not None and p["valor"]:
            mq.append({"periodo": p["periodo"], "margen_pct": round(op / p["valor"] * 100, 2)})
    if not definitivo and rep.get("ingresos") and rep.get("beneficio_operativo") and not any(m["periodo"] == label for m in mq):
        mq.append({"periodo": label, "margen_pct": round(rep["beneficio_operativo"]["valor"] / rep["ingresos"]["valor"] * 100, 2), "provisional": True})
    mq = mq[-12:]

    lect = reading(root, t, analysis, end, k8.get("accn"))
    ui = rec.get("ultimo_informe") or {}
    informe = {
        "_nota": "Informe de resultados generado por el Action (fetcher/resultados.py). No se edita a mano.",
        "esquema": ESQUEMA, "ticker": t, "nombre": company.get("nombre"), "color": company.get("color"),
        "monograma": company.get("monograma"), "logo": (rec.get("perfil") or {}).get("logo"),
        "periodo": label, "periodo_fin": end, "fecha_resultados": F.isoformat(),
        "estado": "definitivo" if definitivo else "provisional",
        "fuente_cifras": ("SEC EDGAR · " + ((rep.get("ingresos") or {}).get("formulario") or "10-Q") + " (XBRL)") if definitivo
                         else "Nota de resultados (8-K, Exhibit 99.1), provisional hasta el 10-Q",
        "informe": {"accn_8k": k8.get("accn"), "url_8k": k8.get("url_indice"), "url_nota": k8.get("url_ex99_1"),
                    "anexos": k8.get("anexos"),
                    "periodico": {k: ui.get(k) for k in ("formulario", "fecha_presentacion", "url_indice", "url_documento")}
                    if definitivo and _d(ui.get("fecha_periodo")) == _d(end) else None},
        "tabla": tabla, "guia": guia, "reaccion": reac, "cotizacion": cot,
        "desglose": des, "estrella": estrella, "margenes": {"trimestral": mq},
        "cita": (nota or {}).get("cita"), "destacados": (nota or {}).get("destacados"), "lectura": lect,
        "estimaciones": {"foto": {"fecha_resultados": snap.get("fecha_resultados"), "evolucion": snap.get("evolucion")} if snap else None,
                         "manual": bool(EST.manual_for(manual, label))},
        "avisos": avisos,
        "_calendario_finnhub": cal or None,
        "_cifras_nota": rep if not definitivo else None,
    }
    return informe, hist_changed


def write_index(root: Path, ticker: str):
    folder = root / "data" / "resultados" / ticker.upper()
    old = _load(folder / "index.json") or {}
    pdfs = {x["periodo"]: x for x in old.get("informes") or []}
    items = []
    for f in folder.glob("*.json"):
        if f.name.startswith("_") or f.name == "index.json":
            continue
        r = _load(f)
        if not r:
            continue
        o = pdfs.get(r["periodo"]) or {}
        items.append({"periodo": r["periodo"], "periodo_fin": r["periodo_fin"], "fecha_resultados": r["fecha_resultados"],
                      "estado": r["estado"], "json": f.name,
                      "pdf": o.get("pdf") if (folder / f"{r['periodo']}.pdf").exists() else None,
                      "pdf_de": o.get("pdf_de") if (folder / f"{r['periodo']}.pdf").exists() else None})
    items.sort(key=lambda x: x["periodo_fin"], reverse=True)
    obj = {"ticker": ticker.upper(), "informes": items}
    txt = json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
    p = folder / "index.json"
    if p.exists() and p.read_text(encoding="utf-8") == txt:
        return False
    folder.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")
    return True
