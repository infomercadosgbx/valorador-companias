"""Detalle de la deuda emisión por emisión, a partir del XBRL completo de los
informes (el API companyfacts de la SEC elimina las dimensiones, así que no
distingue un bono de otro).

Se leen el último 10-K y los 10-Q posteriores:
  - instancia XBRL extraída por EDGAR (<doc>_htm.xml) y su linkbase de
    etiquetas (<doc>_lab.xml), localizadas con index.json del filing;
  - hechos con la dimensión us-gaap:DebtInstrumentAxis -> una emisión
    (cupón, vencimiento, nominal, importe en libros, divisa);
  - hechos con la dimensión us-gaap:LongtermDebtTypeAxis -> composición por tipo.
Solo biblioteca estándar.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

from .filings import archive_base, recent_rows

VERSION = 4
AX_INSTR = "DebtInstrumentAxis"
AX_TYPES = {"LongtermDebtTypeAxis", "ShortTermDebtTypeAxis", "DebtInstrumentAxis"}
ALLOWED_EXTRA = {"LongtermDebtTypeAxis", "ShortTermDebtTypeAxis", "LegalEntityAxis"}

C_COUPON = ("DebtInstrumentInterestRateStatedPercentage",)
C_EFFECTIVE = ("DebtInstrumentInterestRateEffectivePercentage",)
C_FACE = ("DebtInstrumentFaceAmount",)
C_BOOK = ("LongTermDebt", "DebtInstrumentCarryingAmount", "LongTermDebtNoncurrent", "LongTermDebtGross",
          "SeniorNotes", "ConvertibleNotesPayable", "SecuredDebt", "UnsecuredDebt", "SecuredLongTermDebt",
          "UnsecuredLongTermDebt", "LongTermLineOfCredit", "OtherLongTermDebt", "NotesPayable", "SeniorLongTermNotes",
          "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities", "DebtLongtermAndShorttermCombinedAmount",
          "LineOfCreditFacilityBorrowingsOutstanding")
C_MATURITY = ("DebtInstrumentMaturityDate", "DebtInstrumentMaturityDateRangeEnd")
C_ISSUED = ("DebtInstrumentIssuanceDate", "DebtInstrumentIssueDate")
C_TYPE_AMOUNT = ("LongTermDebt", "DebtInstrumentCarryingAmount", "LongTermDebtNoncurrent",
                 "ShortTermBorrowings", "CommercialPaper", "DebtCurrent")

ISO = re.compile(r"iso4217:([A-Z]{3})")
YEAR = re.compile(r"\b(20[2-9]\d|21\d\d)\b")
DUE = re.compile(r"due[^0-9]{0,30}?((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{4})", re.I)
PROGRAM = re.compile(r"^(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?((?:19|20)\d\d)\b(?!\s*Notes? due)", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                            "august", "september", "october", "november", "december"])}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def qname_local(q: str) -> str:
    return q.split(":", 1)[-1]


# ----------------------------------------------------------------- etiquetas
def parse_labels(lab_xml: bytes | None) -> dict:
    """{"amzn_FooMember": "Foo label"} a partir del linkbase de etiquetas."""
    if not lab_xml:
        return {}
    try:
        root = ET.fromstring(lab_xml)
    except ET.ParseError:
        return {}
    XL = "{http://www.w3.org/1999/xlink}"
    out = {}
    for link in root.iter():
        if local(link.tag) != "labelLink":
            continue
        locs, labs, arcs = {}, {}, []
        for el in link:
            t = local(el.tag)
            if t == "loc":
                locs[el.get(XL + "label")] = (el.get(XL + "href") or "").split("#")[-1]
            elif t == "label":
                role = el.get(XL + "role") or ""
                prio = 0 if role.endswith("/label") else 1 if role.endswith("terseLabel") else 2
                labs.setdefault(el.get(XL + "label"), []).append((prio, (el.text or "").strip()))
            elif t == "labelArc":
                arcs.append((el.get(XL + "from"), el.get(XL + "to")))
        for f, t in arcs:
            if f in locs and t in labs:
                best = sorted(labs[t])[0][1]
                cur = out.get(locs[f])
                if best and (cur is None):
                    out[locs[f]] = best
    return out


def humanize(member_q: str) -> str:
    name = qname_local(member_q)
    name = re.sub(r"Member$", "", name)
    name = re.sub(r"^A(?=\d)", "", name)
    name = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def label_for(member_q: str, labels: dict) -> str:
    key = member_q.replace(":", "_")
    lab = labels.get(key) or humanize(member_q)
    return re.sub(r"\s*\[Member\]\s*$", "", lab).strip()


# --------------------------------------------------------------- instancia
def parse_instance(inst_xml: bytes):
    """Devuelve (facts, contexts, units). facts: lista de dicts con concepto,
    contexto, unidad y valor (texto)."""
    root = ET.fromstring(inst_xml)
    contexts, units, facts = {}, {}, []
    for el in root:
        t = local(el.tag)
        if t == "context":
            dims = {}
            for m in el.iter():
                if local(m.tag) == "explicitMember":
                    dims[qname_local(m.get("dimension", ""))] = (m.text or "").strip()
            per = {}
            for p in el.iter():
                lt = local(p.tag)
                if lt in ("instant", "startDate", "endDate"):
                    per[lt] = (p.text or "").strip()
            contexts[el.get("id")] = {"dims": dims, "end": per.get("instant") or per.get("endDate"),
                                      "start": per.get("startDate")}
        elif t == "unit":
            txt = " ".join((m.text or "") for m in el.iter() if local(m.tag) == "measure")
            iso = ISO.search(txt)
            units[el.get("id")] = iso.group(1) if iso else ("pure" if "pure" in txt else txt.strip())
        elif el.get("contextRef"):
            facts.append({"c": local(el.tag), "ctx": el.get("contextRef"), "unit": el.get("unitRef"),
                          "v": (el.text or "").strip(), "scale": el.get("scale")})
    return facts, contexts, units


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick_latest(rows):
    """rows: [(end, value, extra)] -> la de fecha más reciente."""
    rows = [r for r in rows if r[1] is not None]
    return max(rows, key=lambda r: r[0] or "") if rows else None


def maturity_from_label(label: str):
    m = DUE.search(label or "")
    if not m:
        return None, False
    txt = m.group(1)
    if re.fullmatch(r"\d{4}", txt):
        return txt + "-12-31", True
    mm = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", txt)
    try:
        return date(int(mm.group(3)), MONTHS[mm.group(1).lower()], int(mm.group(2))).isoformat(), False
    except (ValueError, KeyError, AttributeError):
        return None, False


def classify(label: str, member_q: str) -> str:
    s = f"{label} {member_q}".lower()
    if "convertible" in s:
        return "Bono convertible"
    if "commercial paper" in s or "commercialpaper" in s:
        return "Papel comercial"
    if "term loan" in s or "termloan" in s:
        return "Préstamo a plazo"
    if "revolving" in s or "credit facility" in s or "line of credit" in s or "creditfacility" in s:
        return "Línea de crédito"
    if "secured" in s and "unsecured" not in s:
        return "Deuda garantizada"
    if "lease" in s or "finance obligation" in s:
        return "Arrendamiento / obligación financiera"
    if "debenture" in s:
        return "Obligación (debenture)"
    if "note" in s or "bond" in s or "senior" in s:
        return "Bono senior"
    return "Otra deuda"


def extract(inst_xml: bytes, lab_xml: bytes | None, period_end: str | None):
    """Emisiones y composición por tipo de UN informe."""
    facts, ctx, units = parse_instance(inst_xml)
    labels = parse_labels(lab_xml)
    instr, types, seen_concepts = {}, {}, {}
    for f in facts:
        c = ctx.get(f["ctx"])
        if not c or not c["dims"]:
            continue
        dims = set(c["dims"])
        if AX_INSTR in dims:
            if not dims - {AX_INSTR} <= ALLOWED_EXTRA:
                continue
            m = c["dims"][AX_INSTR]
            seen_concepts[f["c"]] = seen_concepts.get(f["c"], 0) + 1
            row = instr.setdefault(m, {"coupon": [], "eff": [], "face": [], "book": [], "mat": [], "iss": [], "ccy": set(), "tipo_ax": None})
            extra = dims - {AX_INSTR} - {"LegalEntityAxis"}
            if extra:
                row["tipo_ax"] = c["dims"][next(iter(extra))]
            unit = units.get(f["unit"], "")
            if f["c"] in C_COUPON:
                row["coupon"].append((c["end"], _num(f["v"]), None))
            elif f["c"] in C_EFFECTIVE:
                row["eff"].append((c["end"], _num(f["v"]), None))
            elif f["c"] in C_FACE:
                row["face"].append((c["end"], _num(f["v"]), unit)); row["ccy"].add(unit)
            elif f["c"] in C_BOOK:
                row["book"].append((c["end"], _num(f["v"]), unit)); row["ccy"].add(unit)
            elif f["c"] in C_MATURITY:
                row["mat"].append((c["end"], f["v"][:10], None))
            elif f["c"] in C_ISSUED:
                row["iss"].append((c["end"], f["v"][:10], None))
        elif dims <= {"LongtermDebtTypeAxis", "ShortTermDebtTypeAxis"} and len(dims) == 1 and f["c"] in C_TYPE_AMOUNT:
            d = next(iter(dims)); m = c["dims"][d]
            if period_end and c["end"] != period_end:
                continue
            v = _num(f["v"])
            if v is not None and units.get(f["unit"]) == "USD":
                key = (m, f["c"])
                types[key] = v
    out = []
    for m, r in instr.items():
        label = label_for(m, labels)
        coupon = _pick_latest(r["coupon"]); eff = _pick_latest(r["eff"])
        face_units = {}
        for row in sorted(r["face"], key=lambda x: x[0] or ""):
            if row[1] is not None:
                face_units[row[2] or "USD"] = row
        ccy = next((u for u in face_units if u not in ("USD", "pure") and re.fullmatch(r"[A-Z]{3}", u)), None) or \
            next((u for u in r["ccy"] if u not in ("USD", "pure") and re.fullmatch(r"[A-Z]{3}", u or "")), None) or "USD"
        face = face_units.get(ccy) or face_units.get("USD")
        usd_book = [x for x in r["book"] if (x[2] or "USD") == "USD"]
        book = _pick_latest([x for x in usd_book if period_end and x[0] == period_end] or usd_book)
        mat = _pick_latest(r["mat"]); iss = _pick_latest(r["iss"])
        if mat:
            venc, aprox = mat[1], False
        else:
            venc, aprox = maturity_from_label(label)
        precision = "dia" if venc and not aprox else ("anio" if venc else None)
        if not any([coupon, face, book]):
            continue
        if book and book[1] == 0 and not (face and face[1]):
            continue  # amortizado
        prog = PROGRAM.match(label) if not mat and venc is None else None
        tail = re.search(r"Notes\s+((?:19|20)\d\d)$", label) if not mat and venc is None else None
        emision_lbl = None
        if prog:
            mon = MONTHS.get((prog.group(1) or "").lower())
            yr = int(prog.group(2))
            ref = period_end or date.today().isoformat()
            if mon:
                last_day = (date(yr + (mon == 12), mon % 12 + 1, 1) - date.resolution).isoformat()
                if last_day > ref:                     # «April 2028 Senior Notes»: vence en esa fecha
                    venc, aprox, precision = last_day, True, "mes"
                else:                                  # «March 2026 Euro Notes»: se emitió entonces
                    emision_lbl = f"{yr}-{mon:02d}"
            elif str(yr) <= ref[:4]:
                emision_lbl = str(yr)
        elif tail:
            emision_lbl = tail.group(1)
        variable = bool(re.search(r"floating|variable|sofr|libor", label, re.I))
        out.append({
            "miembro": m, "nombre": label, "tipo": classify(label, m),
            "cupon": None if variable else (round(coupon[1] * 100, 4) if coupon and coupon[1] < 1 else (coupon[1] if coupon else None)),
            "diferencial": (round(coupon[1] * 100, 4) if coupon[1] < 1 else coupon[1]) if (variable and coupon) else None,
            "variable": variable,
            "tipo_efectivo": round(eff[1] * 100, 4) if eff and eff[1] < 1 else (eff[1] if eff else None),
            "nominal": face[1] if face else None, "en_libros": book[1] if book else None,
            "en_libros_fecha": book[0] if book else None,
            "moneda": ccy,
            "nominal_moneda": face[2] if face else None,
            "vencimiento": venc, "vencimiento_aprox": aprox, "vencimiento_precision": precision,
            "emision": iss[1] if iss else emision_lbl,
            "programa": bool(emision_lbl),
        })
    comp = []
    by_member = {}
    for (m, concept), v in types.items():
        pref = C_TYPE_AMOUNT.index(concept)
        if m not in by_member or pref < by_member[m][0]:
            by_member[m] = (pref, v)
    for m, (_, v) in by_member.items():
        lab = label_for(m, labels)
        comp.append({"miembro": m, "nombre": lab, "tipo": classify(lab, m), "importe": v})
    return out, comp, seen_concepts


# ------------------------------------------------------------ orquestación
def target_filings(subs, max_q=4):
    """Último 10-K y los 10-Q presentados después (más recientes primero)."""
    rows = [r for r in recent_rows(subs) if r["form"] in ("10-K", "10-Q")]
    out = []
    for r in rows:
        out.append(r)
        if r["form"] == "10-K" or len(out) > max_q:
            break
    return out


def find_files(index_json):
    items = ((index_json or {}).get("directory") or {}).get("item") or []
    names = [i.get("name", "") for i in items]
    inst = next((n for n in names if n.endswith("_htm.xml")), None)
    if not inst:
        inst = next((n for n in names if n.endswith(".xml") and not re.search(r"_(cal|def|lab|pre)\.xml$|FilingSummary|MetaLinks", n)), None)
    lab = next((n for n in names if n.endswith("_lab.xml")), None)
    return inst, lab


def build(client, cik, subs, previous=None):
    """Devuelve el bloque «bonos» de data/<T>.json, o None si no hay nada.
    Reutiliza el resultado anterior si los informes no han cambiado."""
    fl = target_filings(subs)
    if not fl:
        return None
    accns = [r["accessionNumber"] for r in fl]
    if previous and previous.get("informes_accn") == accns and previous.get("version") == VERSION:
        return previous
    diag = {}
    today = date.today().isoformat()
    seen, comp, used, last_members = {}, [], [], None
    for r in reversed(fl):  # del 10-K al 10-Q más reciente: lo nuevo sobrescribe
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
            items, c, sc = extract(inst, lab, r.get("reportDate"))
            for k, v in sc.items():
                diag[k] = diag.get(k, 0) + v
        except ET.ParseError:
            continue
        src = {"formulario": r["form"], "fecha_presentacion": r["filingDate"], "fecha_periodo": r.get("reportDate"),
               "url": f"{base}/{r['accessionNumber']}-index.htm", "fuente": f"SEC EDGAR · {r['form']} (XBRL)"}
        used.append(src)
        for it in items:
            prev = seen.get(it["miembro"])
            merged = dict(prev or {})
            merged.update({k: v for k, v in it.items() if v is not None})
            merged["primera_vez"] = (prev or {}).get("primera_vez") or src
            merged["fuente"] = src
            seen[it["miembro"]] = merged
        if c:
            comp = [dict(x, fuente=src) for x in c]
        if len(items) >= 3:
            last_members = {it["miembro"] for it in items}
    def vigente(e):
        if last_members is not None and e["miembro"] not in last_members:
            return False                                   # ya no aparece en el último informe
        v = e.get("vencimiento")
        if v and v < today and e.get("vencimiento_precision") != "anio":
            return False                                   # vencido
        return e.get("en_libros") != 0
    emisiones = [e for e in seen.values() if vigente(e)]
    def key(e):
        if e.get("cupon") and e.get("vencimiento"):
            return ("cv", e["cupon"], e["vencimiento"][:4])
        return ("n", " ".join(sorted(re.findall(r"[a-z0-9]+", e["nombre"].lower().replace("seniors", "senior")))))
    best = {}
    for e in emisiones:
        k = key(e)
        score = (e["fuente"]["fecha_presentacion"], sum(1 for f in ("cupon", "nominal", "en_libros", "vencimiento") if e.get(f) is not None))
        if k not in best or score > best[k][0]:
            if k in best:  # completa huecos con el duplicado
                for f, v in best[k][1].items():
                    if e.get(f) is None and v is not None:
                        e[f] = v
            best[k] = (score, e)
        else:
            for f, v in e.items():
                if best[k][1].get(f) is None and v is not None:
                    best[k][1][f] = v
    emisiones = [b for _, b in best.values()]
    emisiones.sort(key=lambda e: (e.get("vencimiento") or "9999", e.get("nombre")))
    last_10k = next((s for s in used if s["formulario"] == "10-K"), None)
    for e in emisiones:
        e["nueva"] = bool(last_10k and e["primera_vez"]["formulario"] == "10-Q")
    top = dict(sorted(diag.items(), key=lambda kv: -kv[1])[:25])
    return {"version": VERSION, "informes_accn": accns, "emisiones": emisiones, "composicion": comp, "informes": used,
            "conceptos_xbrl": top}
