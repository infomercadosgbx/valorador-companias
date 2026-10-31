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

VERSION = 3
AXES = {"StatementBusinessSegmentsAxis": "segmento", "ProductOrServiceAxis": "producto"}
OK_EXTRA = {"ConsolidationItemsAxis"}
REV = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet")
OPI = ("OperatingIncomeLoss", "SegmentReportingInformationOperatingIncomeLoss")
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
    facts, ctx, _ = parse_instance(inst_xml)
    labels = parse_labels(lab_xml)
    out = {}
    for f in facts:
        concept = f["c"]
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


def build(client, cik, subs, previous=None, fye_month=12):
    fl = target_filings(subs)
    if not fl:
        return None
    accns = [r["accessionNumber"] for r in fl]
    if previous and previous.get("informes_accn") == accns and previous.get("version") == VERSION:
        return previous
    merged, used = {}, []
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
        used.append({"formulario": r["form"], "fecha_presentacion": r["filingDate"], "fecha_periodo": r.get("reportDate"),
                     "url": f"{base}/{r['accessionNumber']}-index.htm", "fuente": f"SEC EDGAR · {r['form']} (XBRL)"})
        for k, row in rows.items():
            m = merged.setdefault(k, {"nombre": row["nombre"], "tipo": row["tipo"], "ingresos": {}, "operativo": {}})
            m["nombre"] = row["nombre"]
            for kind in ("ingresos", "operativo"):
                for concept, vals in row[kind].items():
                    m[kind].setdefault(concept, {}).update(vals)
    out = {"segmento": [], "producto": []}
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
    for k in out:
        out[k].sort(key=lambda x: -((x["trimestral"] or x["anual"] or [{"valor": 0}])[-1]["valor"] or 0))
    if not out["segmento"] and not out["producto"]:
        return {"version": VERSION, "informes_accn": accns, "segmento": [], "producto": [], "informes": used}
    return {"version": VERSION, "informes_accn": accns, **out, "informes": used,
            "fuente": "SEC EDGAR · XBRL completo (dimensiones de segmento y producto)"}
