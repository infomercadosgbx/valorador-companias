"""Ingresos (y beneficio operativo) por segmento y por producto a partir del XBRL
completo de los informes (companyfacts no trae dimensiones).

Ejes leídos:
  - us-gaap:StatementBusinessSegmentsAxis  -> segmentos de negocio
  - srt:ProductOrServiceAxis               -> líneas de producto o servicio
Se leen el último 10-K y los 10-Q posteriores. Los 10-Q traen también el mismo
trimestre del año anterior, así que el 4T del año del 10-K se deduce como
anual − (1T + 2T + 3T) cuando están los tres trimestres.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

from .bonds import find_files, label_for, parse_instance, parse_labels, target_filings
from .filings import archive_base

VERSION = 5
AXES = {"StatementBusinessSegmentsAxis": "segmento", "ProductOrServiceAxis": "producto", "StatementGeographicalAxis": "geografia"}
OK_EXTRA = {"ConsolidationItemsAxis"}
REV = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet")
OPI = ("OperatingIncomeLoss", "SegmentReportingInformationOperatingIncomeLoss")
# Gasto de tecnología con etiqueta propia de la compañía (Amazon: «Technology and
# infrastructure», antes «Technology and content»): companyfacts no trae extensiones.
TECH = re.compile(r"^Technology(And\w+)?(Expense|Expenses|Costs)?$")
ADJ = re.compile(r"eliminat|reconcil|corporate|unallocated|hedg|intersegment|other than|all other|adjust", re.I)


def _d(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract(inst_xml: bytes, lab_xml: bytes | None):
    facts, ctx, units = parse_instance(inst_xml)
    labels = parse_labels(lab_xml)
    out = {}
    for f in facts:
        concept = f["c"]
        if concept in ("ConcentrationRiskPercentage1", "ConcentrationRiskPercentage"):
            c = ctx.get(f["ctx"])
            v = _num(f["v"])
            if not c or not c.get("start") or v is None:
                continue
            dims = dict(c["dims"])
            typ, bench = dims.pop("ConcentrationRiskByTypeAxis", ""), dims.pop("ConcentrationRiskByBenchmarkAxis", "")
            if "Customer" not in typ or not re.search(r"Revenue|Sales", bench):
                continue
            dims.pop("ConsolidationItemsAxis", None)
            who = dims.pop("MajorCustomersAxis", None)
            if not who and len(dims) == 1:
                who = next(iter(dims.values()))
            if not who:
                continue
            days = (_d(c["end"]) - _d(c["start"])).days
            per = "T" if 80 <= days <= 100 else "A" if 350 <= days <= 380 else None
            if per:
                if v > 1:
                    v = v / 100
                row = out.setdefault(("_conc", who), {"nombre": label_for(who, labels), "valores": {}})
                row["valores"][(per, c["start"], c["end"])] = v
            continue
        if TECH.match(concept):
            c = ctx.get(f["ctx"])
            v = _num(f["v"])
            if c and not c["dims"] and c.get("start") and v is not None and f.get("unit") and "USD" in str(units.get(f["unit"], "")):
                days = (_d(c["end"]) - _d(c["start"])).days
                per = "T" if 80 <= days <= 100 else "A" if 350 <= days <= 380 else None
                if per:
                    out.setdefault(("_tech", "_tech"), {}).setdefault(concept, {})[(per, c["start"], c["end"])] = v
            continue
        kind = "ingresos" if concept in REV else "operativo" if concept in OPI else None
        if not kind:
            continue
        c = ctx.get(f["ctx"])
        if not c or not c["dims"] or not c.get("start"):
            continue
        dims = dict(c["dims"])
        cons = dims.pop("ConsolidationItemsAxis", None)
        if cons and not cons.endswith("OperatingSegmentsMember"):
            continue
        by_seg = None
        if set(dims) == {"ProductOrServiceAxis", "StatementBusinessSegmentsAxis"}:
            by_seg = dims.pop("StatementBusinessSegmentsAxis")   # producto desglosado por segmento: se suma
        if len(dims) != 1:
            continue
        axis, member = next(iter(dims.items()))
        if axis not in AXES:
            continue
        s, e = _d(c["start"]), _d(c["end"])
        v = _num(f["v"])
        if not s or not e or v is None:
            continue
        days = (e - s).days
        per = "T" if 80 <= days <= 100 else "A" if 350 <= days <= 380 else "YTD" if days > 100 else None
        if not per:
            continue
        row = out.setdefault((axis, member), {"nombre": label_for(member, labels), "tipo": AXES[axis],
                                              "ingresos": {}, "operativo": {}, "conceptos": {}})
        if kind == "ingresos":
            row["conceptos"][concept] = row["conceptos"].get(concept, 0) + 1
        key = (per, c["start"], c["end"])
        if by_seg:
            bucket = row.setdefault("_por_segmento", {}).setdefault(kind, {}).setdefault(concept, {})
            bucket[key] = bucket.get(key, 0) + v
        else:
            row[kind].setdefault(concept, {})[key] = v
    for row in out.values():   # el total del producto manda; si no existe, la suma por segmentos
        for kind, by_c in row.pop("_por_segmento", {}).items():
            for concept, vals in by_c.items():
                dest = row[kind].setdefault(concept, {})
                for key, v in vals.items():
                    dest.setdefault(key, v)
    return out


def _series(by_concept, prefer):
    """Elige el concepto con más datos (en orden de preferencia) y devuelve {(per,start,end): v}."""
    best = None
    for c in prefer:
        if c in by_concept and (best is None or len(by_concept[c]) > len(by_concept[best])):
            best = c
    return by_concept.get(best, {}) if best else {}


def _q_label(end: date, fye_month: int):
    # trimestre fiscal según el mes de cierre del ejercicio
    m = (end.month - fye_month - 1) % 12
    q = m // 3 + 1
    fy = end.year if end.month <= fye_month else end.year + 1
    if fye_month == 12:
        fy = end.year
    return f"{q}T{str(fy)[2:]}"


def _assemble(series: dict, fye_month: int, max_q=12, max_a=5):
    q = {(s, e): v for (p, s, e), v in series.items() if p == "T"}
    a = {(s, e): v for (p, s, e), v in series.items() if p == "A"}
    # 4T = anual − tres trimestres dentro del ejercicio
    for (s, e), v in a.items():
        ds, de = _d(s), _d(e)
        inside = [(k, x) for k, x in q.items() if _d(k[0]) >= ds and _d(k[1]) <= de]
        if len(inside) == 3:
            last_end = max(_d(k[1]) for k, _ in inside)
            if (de - last_end).days > 60:
                q4s = date.fromordinal(last_end.toordinal() + 1).isoformat()
                q.setdefault((q4s, e), v - sum(x for _, x in inside))
    tri = [{"periodo": _q_label(_d(e), fye_month), "periodo_inicio": s, "periodo_fin": e, "valor": v}
           for (s, e), v in sorted(q.items(), key=lambda kv: kv[0][1])][-max_q:]
    anu = [{"periodo": str(_d(e).year if _d(e).month >= 6 else _d(e).year - 1),
            "periodo_inicio": s, "periodo_fin": e, "valor": v}
           for (s, e), v in sorted(a.items(), key=lambda kv: kv[0][1])][-max_a:]
    return tri, anu


def _conc_block(conc, fye_month):
    """Clientes que superan el 10% de los ingresos (nota de concentración del 10-K/10-Q)."""
    out = []
    for member, m in conc.items():
        pts = []
        for (per, s0, e0), (v, src) in sorted(m["valores"].items(), key=lambda kv: kv[0][2]):
            lab = _q_label(_d(e0), fye_month) if per == "T" else str(_d(e0).year if _d(e0).month >= 6 else _d(e0).year - 1)
            pts.append({"periodo": lab, "tipo": "trimestre" if per == "T" else "año", "periodo_inicio": s0, "periodo_fin": e0,
                        "porcentaje": round(v * 100, 1), "fuente": f"SEC EDGAR · {src.get('formulario', '')} (XBRL)",
                        "url": src.get("url"), "fecha_presentacion": src.get("fecha_presentacion")})
        if not pts:
            continue
        anual = [p for p in pts if p["tipo"] == "año"][-5:]
        tri = [p for p in pts if p["tipo"] == "trimestre"][-8:]
        last = max(pts, key=lambda p: (p["periodo_fin"], p["tipo"] == "año"))
        out.append({"miembro": member, "nombre": m["nombre"], "ultimo": last, "anual": anual, "trimestral": tri})
    out.sort(key=lambda x: (x["ultimo"]["periodo_fin"], x["ultimo"]["porcentaje"]), reverse=True)
    return out


def _tech_block(tech, fye_month):
    """Serie del gasto de tecnología (etiqueta propia) con su informe de origen."""
    if not tech:
        return None
    concept = max(tech, key=lambda c: (max(k[2] for k in tech[c]), len(tech[c])))
    vals = tech[concept]
    tri, anu = _assemble({k: v for k, (v, _) in vals.items()}, fye_month, max_q=12, max_a=5)
    def src_for(s, e):
        for (p, ks, ke), (_, src) in vals.items():
            if ke == e:
                return src
        return None
    def pt(x, derived=None):
        src = src_for(x["periodo_inicio"], x["periodo_fin"]) or {}
        out = {"periodo": x["periodo"], "valor": x["valor"], "periodo_inicio": x["periodo_inicio"], "periodo_fin": x["periodo_fin"],
               "fuente": f"SEC EDGAR · {src.get('formulario', '')} (XBRL)", "url": src.get("url"),
               "fecha_presentacion": src.get("fecha_presentacion"), "formulario": src.get("formulario"),
               "etiqueta": f"{src.get('ns') or 'ext'}:{concept}"}
        if (x["periodo_inicio"], x["periodo_fin"]) not in {(k[1], k[2]) for k in vals}:
            out["derivado"] = "Anual − tres trimestres"
        return out
    return {"concepto": concept, "trimestral": [pt(x) for x in tri], "anual": [pt(x) for x in anu]}


def _collect(client, cik, fl):
    """Lee el XBRL completo de cada informe (del más antiguo al más reciente) y fusiona las series."""
    merged, used, tech, conc = {}, [], {}, {}
    for r in reversed(fl):  # lo más reciente sobrescribe
        base = archive_base(cik, r["accessionNumber"])
        idx = client.get_json(f"{base}/index.json")
        inst_name, lab_name = find_files(idx)
        if not inst_name:
            continue
        inst = client.get_bytes(f"{base}/{inst_name}")
        lab = client.get_bytes(f"{base}/{lab_name}") if lab_name else None
        if not inst:
            continue
        try:
            rows = extract(inst, lab)
        except ET.ParseError:
            continue
        src = {"formulario": r["form"], "fecha_presentacion": r["filingDate"], "url": f"{base}/{r['accessionNumber']}-index.htm",
               "ns": inst_name.split("-")[0].split("_")[0]}
        for k in [k for k in rows if k[0] == "_conc"]:
            r0 = rows.pop(k)
            m = conc.setdefault(k[1], {"nombre": r0["nombre"], "valores": {}})
            for key, v in r0["valores"].items():
                m["valores"][key] = (v, src)
        for concept, vals in rows.pop(("_tech", "_tech"), {}).items():
            for key, v in vals.items():
                tech.setdefault(concept, {})[key] = (v, src)
        used.append({"formulario": r["form"], "fecha_presentacion": r["filingDate"], "fecha_periodo": r.get("reportDate"),
                     "url": f"{base}/{r['accessionNumber']}-index.htm", "fuente": f"SEC EDGAR · {r['form']} (XBRL)"})
        for k, row in rows.items():
            m = merged.setdefault(k, {"nombre": row["nombre"], "tipo": row["tipo"], "ingresos": {}, "operativo": {}})
            m["nombre"] = row["nombre"]
            for kind in ("ingresos", "operativo"):
                for concept, vals in row[kind].items():
                    m[kind].setdefault(concept, {}).update(vals)
    return merged, used, tech, conc


def build(client, cik, subs, previous=None, fye_month=12):
    fl = target_filings(subs)
    if not fl:
        return None
    accns = [r["accessionNumber"] for r in fl]
    if previous and previous.get("informes_accn") == accns and previous.get("version") == VERSION:
        return previous
    merged, used, tech, conc = _collect(client, cik, fl)
    out = {"segmento": [], "producto": [], "geografia": []}
    for (axis, member), m in merged.items():
        rev = _series(m["ingresos"], REV)
        if not rev:
            continue
        tri, anu = _assemble(rev, fye_month)
        if not tri and not anu:
            continue
        opi_t, opi_a = _assemble(_series(m["operativo"], OPI), fye_month)
        out[m["tipo"]].append({"miembro": member, "nombre": m["nombre"], "ajuste": bool(ADJ.search(m["nombre"] + " " + member)),
                               "trimestral": tri, "anual": anu,
                               "operativo_trimestral": opi_t, "operativo_anual": opi_a})
    out["gasto_tecnologia"] = _tech_block(tech, fye_month)
    out["clientes_concentracion"] = _conc_block(conc, fye_month)
    for k in ("segmento", "producto", "geografia"):
        out[k].sort(key=lambda x: -((x["trimestral"] or x["anual"] or [{"valor": 0}])[-1]["valor"] or 0))
    if not out["segmento"] and not out["producto"] and not out["geografia"] and not out["clientes_concentracion"]:
        return {"version": VERSION, "informes_accn": accns, "segmento": [], "producto": [], "informes": used}
    return {"version": VERSION, "informes_accn": accns, **out, "informes": used,
            "fuente": "SEC EDGAR · XBRL completo (dimensiones de segmento y producto)"}


def history(client, cik, subs, fye_month=12, n_filings=14):
    """Serie larga de ingresos y beneficio operativo por segmento y línea de producto
    (para el run-rate del informe de resultados). Lee los últimos «n_filings»
    10-Q/10-K; cada 10-Q trae además el mismo trimestre del año anterior, así que
    14 informes dan unos 4 años. Se ejecuta una sola vez por compañía: después,
    resultados.py va añadiendo los trimestres nuevos de data/<T>.json."""
    from .filings import recent_rows
    fl = [r for r in recent_rows(subs) if r["form"] in ("10-K", "10-Q")][:n_filings]
    if not fl:
        return None
    merged, used, _, _ = _collect(client, cik, fl)
    out = {"segmento": [], "producto": []}
    for (axis, member), m in merged.items():
        if m["tipo"] not in out:
            continue
        rev = _series(m["ingresos"], REV)
        if not rev:
            continue
        tri, _ = _assemble(rev, fye_month, max_q=60, max_a=10)
        opi, _ = _assemble(_series(m["operativo"], OPI), fye_month, max_q=60, max_a=10)
        if tri:
            out[m["tipo"]].append({"miembro": member, "nombre": m["nombre"], "ajuste": bool(ADJ.search(m["nombre"] + " " + member)),
                                   "trimestral": tri, "operativo_trimestral": opi})
    out["informes"] = len(used)
    return out
