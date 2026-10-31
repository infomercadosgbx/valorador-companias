"""Cambios en el apartado de riesgos (Item 1A) entre los dos últimos 10-K.

Se descarga el documento principal de cada 10-K, se aísla el Item 1A y se
toman como «titulares de riesgo» los párrafos cortos seguidos de un párrafo
largo (así redactan casi todas las compañías sus factores de riesgo). Luego se
comparan con coincidencia aproximada. Es una detección automática: la web la
presenta como orientativa y enlaza a los documentos.
"""
from __future__ import annotations

import html as H
import re
from difflib import SequenceMatcher

from .filings import archive_base, recent_rows

VERSION = 2
BLOCK_END = re.compile(r"</(p|div|li|tr|h\d|table)>|<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")
START = re.compile(r"item\s*1a\.?\s*[\-–—:.]?\s*risk\s+factors", re.I)
END = re.compile(r"item\s*1b\.?|item\s*1c\.?|item\s*2\.?\s*[\-–—:.]?\s*properties|unresolved\s+staff\s+comments", re.I)


def to_paragraphs(doc_html: str):
    doc_html = re.sub(r"(?is)<(script|style|ix:header)[^>]*>.*?</\1>", " ", doc_html)
    txt = BLOCK_END.sub("\n", doc_html)
    txt = H.unescape(TAG.sub(" ", txt))
    paras = [re.sub(r"\s+", " ", p).strip() for p in txt.split("\n")]
    return [p for p in paras if p]


def risk_section(paras):
    """Párrafos del Item 1A (el tramo más largo entre «Item 1A» y el siguiente Item)."""
    best = []
    for i, p in enumerate(paras):
        if len(p) < 120 and START.search(p):
            j = i + 1
            while j < len(paras) and not (len(paras[j]) < 120 and END.search(paras[j])):
                j += 1
            if j - i > len(best):
                best = paras[i + 1:j]
    return best


def headings(section):
    out = []
    for i, p in enumerate(section[:-1]):
        nxt = section[i + 1]
        if 40 <= len(p) <= 450 and len(nxt) > 250 and p[-1:] in ".:" and not p.lower().startswith(("see ", "for example")):
            out.append(p)
    return out


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def compare(new, old, thr=0.72):
    old_n = [norm(x) for x in old]
    used = set()
    added = []
    for h in new:
        hn = norm(h)
        best, bi = 0, None
        for i, o in enumerate(old_n):
            if i in used:
                continue
            sm = SequenceMatcher(None, hn, o)
            if sm.real_quick_ratio() < thr or sm.quick_ratio() < thr:
                continue
            r = sm.ratio()
            if r > best:
                best, bi = r, i
        if best >= thr:
            used.add(bi)
        else:
            added.append(h)
    removed = [old[i] for i in range(len(old)) if i not in used]
    return added, removed


def build(client, cik, subs, previous=None):
    ks = [r for r in recent_rows(subs) if r["form"] == "10-K"][:2]
    if len(ks) < 2:
        return None
    accns = [r["accessionNumber"] for r in ks]
    if previous and previous.get("informes_accn") == accns and previous.get("version") == VERSION:
        return previous
    docs = []
    for r in ks:
        base = archive_base(cik, r["accessionNumber"])
        url = f"{base}/{r['primaryDocument']}"
        html = client.get_text(url)
        sec = risk_section(to_paragraphs(html or ""))
        docs.append({"formulario": "10-K", "fecha_presentacion": r["filingDate"], "fecha_periodo": r.get("reportDate"),
                     "url": url, "palabras": sum(len(p.split()) for p in sec), "titulares": headings(sec)})
    new, old = docs
    if len(new["titulares"]) < 5 or len(old["titulares"]) < 5:
        return {"version": VERSION, "informes_accn": accns, "ok": False, "informes": [{k: v for k, v in d.items() if k != "titulares"} for d in docs],
                "motivo": "No se ha podido aislar el apartado de riesgos de forma fiable."}
    added, removed = compare(new["titulares"], old["titulares"])
    return {"version": VERSION, "informes_accn": accns, "ok": True,
            "informes": [{k: v for k, v in d.items() if k != "titulares"} | {"n_riesgos": len(d["titulares"])} for d in docs],
            "nuevos": added[:25], "eliminados": removed[:25], "n_nuevos": len(added), "n_eliminados": len(removed),
            "fuente": "SEC EDGAR · 10-K, Item 1A (comparación automática)"}
