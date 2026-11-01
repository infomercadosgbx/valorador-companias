"""Lo que cuenta la compañía en su nota de resultados (8-K, Exhibit 99.1).

Extrae, en el idioma original, tres cosas que no vienen en datos estructurados:
  - la guía («Outlook» / «Guidance»),
  - los titulares («Highlights»),
  - la cita principal de la dirección.
Es una lectura automática del documento oficial: la web la muestra como texto
original con enlace, y tu análisis (mgmt.call) sigue siendo la versión revisada.
"""
from __future__ import annotations

import re

from .riskfactors import to_blocks

VERSION = 1
HEAD_OUT = re.compile(r"\b(outlook|guidance)\b", re.I)
HEAD_HI = re.compile(r"\b(highlights)\b", re.I)
QUOTE = re.compile(r"[“\"]([^”\"]{60,700})[”\"]")
SAID = re.compile(r"\b(said|says|commented|stated|added)\b", re.I)
NOISE = re.compile(r"forward-looking|non-gaap|reconciliation|safe harbor|conference call|webcast|about [A-Z]", re.I)


def _is_head(t, styled):
    return len(t) <= 90 and (styled or t.isupper() or not t.endswith("."))


def _section(blocks, head_re, max_chars=1400, max_items=8):
    for i, (t, st) in enumerate(blocks):
        if not (_is_head(t, st) and head_re.search(t)) or NOISE.search(t):
            continue
        out, n = [], 0
        for t2, st2 in blocks[i + 1:]:
            if (st2 or t2.isupper()) and len(t2) < 90 and not t2.endswith(":"):
                break
            if QUOTE.search(t2) and SAID.search(t2):
                break
            if NOISE.search(t2) and out:
                break
            if len(t2) < 3:
                continue
            out.append(t2[:500])
            n += len(t2)
            if n >= max_chars or len(out) >= max_items:
                break
        if out:
            return {"titulo": t, "texto": out}
    return None


def _quote(blocks):
    for t, _ in blocks[:80]:
        m = QUOTE.search(t)
        if m and SAID.search(t):
            who = re.search(r"(?:said|says|commented|stated|added)\s+([^,.]{3,80}(?:,[^.]{0,80})?)", t)
            return {"cita": m.group(1).strip(), "quien": (who.group(1).strip() if who else None)}
    return None


def extract(html: str):
    blocks = to_blocks(html or "")
    if not blocks:
        return None
    out = {"version": VERSION, "guia": _section(blocks, HEAD_OUT), "destacados": _section(blocks, HEAD_HI, 1600, 10),
           "cita": _quote(blocks)}
    return out if any(out[k] for k in ("guia", "destacados", "cita")) else None


def attach(client, rec, previous=None):
    """Añade «nota_resultados» al 8-K de resultados. Reutiliza lo anterior si es el mismo 8-K."""
    if not rec or not rec.get("url_ex99_1"):
        return
    prev = (previous or {}).get("nota_resultados")
    if prev and prev.get("accn") == rec.get("accn") and prev.get("version") == VERSION:
        rec["nota_resultados"] = prev
        return
    try:
        html = client.get_text(rec["url_ex99_1"])
    except Exception:  # noqa: BLE001  extra
        return
    got = extract(html)
    if got:
        got.update({"accn": rec.get("accn"), "url": rec["url_ex99_1"], "idioma": "en",
                    "fuente": "SEC EDGAR · 8-K, Exhibit 99.1 (lectura automática)"})
        rec["nota_resultados"] = got
