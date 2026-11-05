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

VERSION = 5
HEAD_OUT = re.compile(r"\b(outlook|guidance)\b", re.I)
HEAD_HI = re.compile(r"\b(highlights)\b", re.I)
QUOTE = re.compile(r"[“\"]([^”\"]{60,700})(?:[”\"]|$)")
SAID = re.compile(r"\b(said|says|commented|stated|added)\b", re.I)
BOILER = re.compile(r"forward-looking|not a guarantee|uncertaint|undertakes no|risk factors|subject to substantial", re.I)
TABLEISH = re.compile(r"^\(?in (millions|thousands)|^(three|six|nine|quarter|year)s? (months )?ended|^\$? ?\(?[\d.,%$ ()-]+\)?$", re.I)
NOISE = re.compile(r"forward-looking|non-gaap|reconciliation|safe harbor|conference call|webcast|about [A-Z]", re.I)
BULLET = re.compile(r"^[●•▪◦·∙‣\-–—]\s*")
# Cabeceras de tabla: «September 30, Nine Months Ended September 30,», «(In millions…) Low High», «4Q26», «Q3 26 Q3 25 Change»
HEADER = re.compile(r"(months|quarters?|weeks|years?) ended\b|^\(?(dollars |amounts )?in (millions|thousands|billions)\b|^(low|high)\b"
                    r"|^(\d[QH]|Q\d|FY)\s?['’]?\d{2,4}\b|^unit\b|^(september|june|march|december|october|november|july|august|january|february|april|may)\s+\d{1,2},?\s*(\d{4})?\s*$", re.I)
FOOTNOTE = re.compile(r"^\(?\d{1,2}\)?\s+[A-Z][a-z]")
NUM = r"\(?[-−+]?\$?\s?[\d][\d.,]*\s?[%x]?\)?"
ROW = re.compile(rf"^(?P<etq>[A-Za-z][^$\d]{{1,70}}?)\*?\s*(?:\d\s+)?(?P<uni>\$\s?[BMK]\s+|%\s+|MBOED\s+|MBD\s+)?(?P<vals>(?:\$?\s?{NUM}\s*(?:bps|pp)?\s*){{1,8}})$")
DATELINE = re.compile(r"^[A-Z][A-Za-z.,' ]{2,40}\s[—–-]\s(?:[A-Z][a-z]{2,8}\.?\s\d{1,2},\s\d{4})\s[—–-]")
UNIT = re.compile(r"\bin (millions|billions|thousands)\b", re.I)


def _is_head(t, styled):
    return len(t) <= 90 and (styled or t.isupper() or not t.endswith("."))


def _row(t):
    """«Revenue $2,365 $2,395» → ("Revenue", ["$2,365", "$2,395"]); None si no es una fila de tabla."""
    if t.endswith(".") or len(t) > 160:
        return None
    t = re.sub(r"(\d)\s*[-–—]\s*(?=\$|\d)", r"\1 ", t.strip())   # «$6,800 - $7,600»
    m = ROW.match(t)
    if not m:
        return None
    etq = m.group("etq").strip(" :*")
    if m.group("uni"):
        etq = f"{etq} ({m.group('uni').strip()})"
    vals = re.findall(rf"\$?\s?{NUM}(?:\s*(?:bps|pp))?", m.group("vals"))
    vals = [re.sub(r"\s+", "", v) for v in vals if re.search(r"\d", v) and not re.fullmatch(r"\s*\(\d\)\s*", v)]
    if not etq or not vals or len(etq.split()) > 12:
        return None
    return etq, vals


def _guide_sentence(etq, vals, unit):
    """Fila de una tabla de guía → frase que entiende parse_guidance: «Revenue: $2,365 – $2,395 million»."""
    def u(v):
        return v if v.endswith("%") or not unit or "$" not in v else f"{v} {unit}"
    if len(vals) >= 2:
        return f"{etq}: {vals[0]} – {u(vals[1])}"
    return f"{etq}: {u(vals[0])}"


def _upper_head(t):
    letters = re.sub(r"[^A-Za-z]", "", t)
    return len(letters) >= 4 and t.isupper() and not re.search(r"\d", t)


def _section(blocks, head_re, max_chars=1400, max_items=8, guide=False):
    """Sección bajo un título que encaje. Hay notas con un «Guidance» de una línea arriba y la guía
    de verdad más abajo, o con la tabla de cifras y los titulares en dos secciones: se toma la
    primera con texto suficiente y, si no trae tabla, las filas de la primera que la tenga."""
    prosa = tabla = mejor = None
    score = 0
    for i, (t, st) in enumerate(blocks):
        if not (_is_head(t, st) and head_re.search(t)) or NOISE.search(t) or BULLET.match(t):
            continue
        res = _section_at(blocks, i, head_re, max_chars, max_items, guide)
        if not res:
            continue
        sc = sum(len(x) for x in res["texto"])
        if prosa is None and sc >= 120:
            prosa = res
        if tabla is None and len(res.get("filas") or []) >= 2:
            tabla = res
        if sc + 60 * len(res.get("filas") or []) > score:
            mejor, score = res, sc + 60 * len(res.get("filas") or [])
        if prosa and (tabla or guide):
            break
    if prosa:
        if tabla and tabla is not prosa and not prosa.get("filas"):
            prosa = dict(prosa, filas=tabla["filas"], cabecera=tabla.get("cabecera"), unidad=tabla.get("unidad"))
        return prosa
    return tabla or mejor


def _section_at(blocks, i, head_re, max_chars, max_items, guide):
    t = blocks[i][0]
    if True:
        out, rows, cab, n = [], [], None, 0
        unit, pend = None, None
        for t2, st2 in blocks[i + 1:]:
            t2 = BULLET.sub("", t2).strip()
            if not t2:
                continue
            if pend and re.search(r"\d", t2) and not re.search(r"[A-Za-z]{3}", t2) and len(t2) < 120:
                t2 = f"{pend} {t2}"   # etiqueta en una línea y cifras en la siguiente
            pend = None
            if (st2 or _upper_head(t2)) and len(t2) < 90 and not t2.endswith(":"):
                if any(len(x) >= 30 for x in out) or rows:
                    break
                out.append(t2)   # subtítulo justo después del título («Fourth Quarter 2026 Guidance»)
                continue
            if QUOTE.search(t2) and SAID.search(t2):
                break
            if NOISE.search(t2) and (out or rows):
                break
            other = HEAD_HI if head_re is HEAD_OUT else HEAD_OUT
            if len(t2) < 90 and not t2.endswith(".") and other.search(t2) and (out or rows):
                break   # empieza la otra sección («Fourth Quarter 2026 Financial Guidance»)
            if FOOTNOTE.match(t2) and len(t2) > 60:
                if out or rows:
                    break   # notas al pie bajo la tabla: fin de la sección
                continue
            um = UNIT.search(t2)
            if um and len(t2) < 120:
                unit = {"millions": "million", "billions": "billion", "thousands": "thousand"}[um.group(1).lower()]
            if HEADER.search(t2) and not t2.endswith("."):
                if len(t2) < 120 and not out and not rows:
                    cab = t2
                continue
            r = _row(t2)
            if r:
                if guide:
                    out.append(_guide_sentence(r[0], r[1], unit))
                else:
                    rows.append({"etiqueta": r[0], "valores": r[1]})
                n += len(t2)
                if len(rows) >= 10:
                    break
                continue
            if len(t2) < 60 and t2.endswith(":") and not guide:
                continue   # subtítulo («Additional Financial Highlights:»)
            if len(t2) < 70 and not re.search(r"\d", t2) and not t2.endswith((".", ":")):
                pend = t2   # posible etiqueta de fila con las cifras en el bloque siguiente
            if DATELINE.match(t2):
                continue
            if (len(t2) < 30 and not t2.endswith(":")) or TABLEISH.search(t2) or (len(t2) > 200 and BOILER.search(t2)):
                continue
            out.append(t2[:500])
            n += len(t2)
            if n >= max_chars or len(out) >= max_items:
                break
        if any(len(x) >= 30 for x in out) or len(rows) >= 2:
            res = {"titulo": re.sub(r"[\s:]*\d?$", "", t).strip(), "texto": out}
            if rows:
                res["filas"] = rows
                res["cabecera"] = cab
                res["unidad"] = unit
            return res
    return None


def _quote(blocks):
    prev = ""
    for t, _ in blocks[:120]:
        m = QUOTE.search(t)
        if m and (SAID.search(t) or SAID.search(prev[-60:])):
            src = t if SAID.search(t) else prev
            who = re.search(r"(?:said|says|commented|stated|added)\s+([^,.“\"]{3,80}(?:,[^.“\"]{0,80})?)", src)
            if not who:
                who = re.search(r"([A-Z][\w.\- ]{3,60}(?:,[^:“\"]{0,80})?),?\s+(?:said|says|commented|stated|added)", src)
            return {"cita": m.group(1).strip().rstrip(","), "quien": (who.group(1).strip() if who else None)}
        prev = t
    return None


def extract(html: str):
    blocks = to_blocks(html or "")
    if not blocks:
        return None
    out = {"version": VERSION, "guia": _section(blocks, HEAD_OUT, guide=True), "destacados": _section(blocks, HEAD_HI, 1600, 10),
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
