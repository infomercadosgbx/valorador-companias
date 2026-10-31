"""Compras y ventas de directivos y consejeros (formulario 4 de la SEC).

Se leen los formularios 4 de los últimos ~6 meses que aparecen en
data.sec.gov/submissions de la compañía (la SEC los asocia al emisor).
Cada filing se descarga una sola vez: se reutilizan los ya leídos.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from .filings import archive_base, recent_rows

VERSION = 1
DAYS = 183
MAX_NEW = 150
CODES = {"P": "Compra en mercado", "S": "Venta en mercado", "A": "Concesión (sueldo en acciones)",
         "M": "Ejercicio de opciones", "F": "Retención fiscal", "G": "Donación", "C": "Conversión",
         "D": "Devolución a la empresa", "X": "Ejercicio de opciones", "J": "Otra", "W": "Herencia"}


def _t(el, path):
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _strip_ns(xml: bytes) -> bytes:
    return re.sub(rb'\sxmlns(:\w+)?="[^"]+"', b"", xml, count=5)


def parse_form4(xml: bytes):
    root = ET.fromstring(_strip_ns(xml))
    owners = []
    for o in root.findall("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        cargo = []
        if rel is not None:
            if _t(rel, "isDirector") in ("1", "true"):
                cargo.append("Consejero")
            if _t(rel, "isOfficer") in ("1", "true"):
                cargo.append(_t(rel, "officerTitle") or "Directivo")
            if _t(rel, "isTenPercentOwner") in ("1", "true"):
                cargo.append("Accionista >10%")
        owners.append({"nombre": _t(o, "reportingOwnerId/rptOwnerName"), "cargo": ", ".join(cargo)})
    plan = _t(root, "aff10b5One") in ("1", "true")
    tx = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(t, "transactionCoding/transactionCode")
        sh = _f(_t(t, "transactionAmounts/transactionShares/value"))
        px = _f(_t(t, "transactionAmounts/transactionPricePerShare/value"))
        ad = _t(t, "transactionAmounts/transactionAcquiredDisposedCode/value")
        tx.append({"fecha": _t(t, "transactionDate/value"), "codigo": code, "tipo": CODES.get(code, code),
                   "acciones": sh, "precio": px, "importe": round(sh * px, 2) if sh and px else None,
                   "sentido": "compra" if ad == "A" else "venta" if ad == "D" else None,
                   "tras_operacion": _f(_t(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
                   "clase": _t(t, "securityTitle/value")})
    return owners, tx, plan


def build(client, cik, subs, previous=None, today=None):
    today = today or date.today()
    since = (today - timedelta(days=DAYS)).isoformat()
    rows = [r for r in recent_rows(subs) if r["form"] == "4" and r["filingDate"] >= since]
    prev = {o["accn"]: o for o in ((previous or {}).get("operaciones_por_filing") or [])} \
        if (previous or {}).get("version") == VERSION else {}
    filings, new = [], 0
    for r in rows:
        accn = r["accessionNumber"]
        if accn in prev:
            filings.append(prev[accn])
            continue
        if new >= MAX_NEW:
            continue
        doc = re.sub(r"^xslF345X\d+/", "", r.get("primaryDocument") or "")
        if not doc.endswith(".xml"):
            continue
        base = archive_base(cik, accn)
        xml = client.get_bytes(f"{base}/{doc}")
        new += 1
        if not xml:
            continue
        try:
            owners, tx, plan = parse_form4(xml)
        except ET.ParseError:
            continue
        filings.append({"accn": accn, "fecha_presentacion": r["filingDate"], "url": f"{base}/{accn}-index.htm",
                        "personas": owners, "plan_10b5_1": plan, "operaciones": tx})
    ops = []
    for f in filings:
        who = f["personas"][0] if f["personas"] else {"nombre": None, "cargo": ""}
        for t in f["operaciones"]:
            ops.append({**t, "persona": who["nombre"], "cargo": who["cargo"], "plan_10b5_1": f["plan_10b5_1"],
                        "fecha_presentacion": f["fecha_presentacion"], "url": f["url"]})
    ops.sort(key=lambda o: (o["fecha"] or "", o["fecha_presentacion"]), reverse=True)
    mkt = [o for o in ops if o["codigo"] in ("P", "S") and o["importe"]]
    resumen = {
        "compras_mercado": sum(o["importe"] for o in mkt if o["codigo"] == "P"),
        "ventas_mercado": sum(o["importe"] for o in mkt if o["codigo"] == "S"),
        "n_compras": sum(1 for o in mkt if o["codigo"] == "P"),
        "n_ventas": sum(1 for o in mkt if o["codigo"] == "S"),
        "ventas_con_plan": sum(o["importe"] for o in mkt if o["codigo"] == "S" and o["plan_10b5_1"]),
        "compradores": sorted({o["persona"] for o in mkt if o["codigo"] == "P" and o["persona"]}),
        "desde": since,
    }
    return {"version": VERSION, "fuente": "SEC EDGAR · formularios 4", "resumen": resumen,
            "operaciones": ops[:200], "operaciones_por_filing": filings, "n_formularios": len(filings)}
