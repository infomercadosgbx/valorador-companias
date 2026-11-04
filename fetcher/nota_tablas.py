"""Cifras del trimestre leídas de las tablas de la nota de resultados (8-K, Exhibit 99.1).

El día de resultados el 10-Q todavía no existe (Amazon lo presenta al día
siguiente; Broadcom, una o dos semanas después), así que el informe de
resultados usa provisionalmente las tablas de la nota. Son las mismas cifras
que luego aparecen en el 10-Q, pero sin XBRL: hay que leerlas del HTML.

Cómo se elige la columna del trimestre: en la cabecera de cada tabla se leen
los años en orden («2025 2026 2025 2026» en Amazon, «2026 2026 2025» en
Broadcom). El primer grupo de columnas es el trimestre; dentro de él, la
columna con el año más reciente es el trimestre actual.

Solo se aceptan filas de las cuentas oficiales (GAAP): se ignoran las que
dicen «non-GAAP», «adjusted» o «excluding». Cada cifra se valida después
frente al trimestre anterior de la SEC (ver resultados.py).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

NUM = re.compile(r"^\(?-?\$?\s*\(?([\d][\d,]*(?:\.\d+)?)\)?\s*%?\)?$")
YEAR = re.compile(r"\b(20\d\d)\b")
BAD = re.compile(r"non-?gaap|adjusted|excluding|ex-|pro forma|constant currency|fx-neutral|organic|guidance|outlook|"
                 r"margin|% of|percent|growth|change|per diluted share impact|run[- ]rate|backlog|segment", re.I)

CONCEPTOS = {
    "ingresos": [
        r"total net sales", r"net sales", r"total revenues?", r"revenues?", r"net revenues?", r"total net revenues?",
        r"operating revenues?", r"total operating revenues?", r"sales and other operating revenues?", r"revenues?: global",
    ],
    "beneficio_operativo": [
        r"(?:total )?operating income(?: \(loss\))?", r"income(?: \(loss\))? from operations", r"operating (?:profit|loss)(?: \(loss\))?",
        r"operating \(loss\) income",
    ],
    "beneficio_neto": [
        r"net income(?: \(loss\))? attributable to (?!non)(?!preferred)[\w .,&'’]+", r"net income(?: \(loss\))?", r"net (?:loss|earnings)(?: \(loss\))?",
    ],
    "bpa_diluido": [
        r"diluted",   # la detección real del BPA va aparte (ver candidates)
    ],
    "beneficio_antes_impuestos": [
        r"(?:net )?income(?: \(loss\))? before (?:provision for )?income tax(?:es| expense)?(?: \(benefit\)| expense \(benefit\))?",
    ],
    "gastos_intereses": [r"interest (?:and debt )?expense(?:s)?(?: and related charges)?", r"interest and debt expense"],
}
_RX = {k: [re.compile(rf"^{p}[\s:,]*(?:\(\d\)|\*)?$", re.I) for p in v] for k, v in CONCEPTOS.items()}
EPS_SECTION = re.compile(r"per (?:common )?share|earnings per|net income per|\beps\b|per share of common", re.I)
NOT_EPS = re.compile(r"shares used|weighted|number of shares|shares outstanding|dilutive|basic", re.I)
QTR = re.compile(r"three months|quarter|\b(?:1[0-7]|[89]) weeks|\bq[1-4]\b|3 months", re.I)
YR = re.compile(r"year ended|years ended|twelve months|12 months|fiscal year|52 weeks|53 weeks|full year", re.I)


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._t, self._r, self._c, self._depth = [], None, None, None, 0
        self.pre_text, self._text = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._t = {"rows": [], "antes": " ".join(self._text[-40:])}
        elif self._t is not None and tag == "tr":
            self._r = []
        elif self._r is not None and tag in ("td", "th"):
            span = dict(attrs).get("colspan") or "1"
            self._c = {"t": [], "span": int(span) if str(span).isdigit() else 1}
        elif tag in ("br", "p", "div") and self._c is not None:
            self._c["t"].append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth -= 1
            if self._depth == 0 and self._t is not None:
                self.tables.append(self._t)
                self._t = None
        elif tag == "tr" and self._r is not None and self._t is not None:
            if any(c["x"] for c in self._r):
                self._t["rows"].append(self._r)
            self._r = None
        elif tag in ("td", "th") and self._c is not None and self._r is not None:
            x = re.sub(r"\s+", " ", "".join(self._c["t"]).replace("​", "")).strip()
            self._r.append({"x": x, "span": self._c["span"]})
            self._c = None

    def handle_data(self, data):
        if self._c is not None:
            self._c["t"].append(data)
        elif self._t is None:
            s = data.strip()
            if s:
                self._text.append(s)


def _num(s: str):
    s = s.replace("—", "").replace("–", "").replace("—", "").strip()
    if s in ("", "-", "$", "%"):
        return None
    m = NUM.match(s.replace(" ", ""))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    neg = s.startswith("(") or s.endswith(")") or s.startswith("-")
    return -v if neg else v


def _row_values(row):
    """Valores numéricos de la fila (sin porcentajes), uniendo «$ | 1,234 | )»."""
    cells = [c["x"] for c in row[1:]]
    joined, buf = [], ""
    for c in cells:
        if c in ("$", "(", "$(", "$ ("):
            buf += c
            continue
        if c in (")", "%", ")%", "%)") and joined:
            joined[-1] += c
            continue
        joined.append(buf + c)
        buf = ""
    out = []
    for c in joined:
        if not c or "%" in c:
            continue
        v = _num(c)
        if v is not None:
            out.append(v)
    return out


def _header_years(rows):
    """Años de la cabecera en orden de columna (filas antes de la primera fila con cifras)."""
    for r in rows[:8]:
        vals = _row_values(r)
        if vals and not all(v == int(v) and 1990 <= v <= 2100 for v in vals):
            break   # primera fila con cifras reales: ya no hay cabecera
        ys = [int(y) for c in r[1:] for y in YEAR.findall(c["x"])]
        if len(ys) < 2:   # años en la propia etiqueta de la primera columna («… 2026 2025»)
            ys = [int(y) for c in r for y in YEAR.findall(c["x"])]
        if len(ys) >= 2:
            return ys
    return []


def _current_index(years):
    """Posición del trimestre actual dentro de los valores de la fila."""
    if not years:
        return None
    group = []
    for y in years:
        if y in group:
            break
        group.append(y)
    return group.index(max(group))


def _scale(tab):
    ctx = (tab.get("antes", "")[-300:] + " " + " ".join(c["x"] for r in tab["rows"][:4] for c in r)).lower()
    if "in thousands" in ctx or "(000" in ctx:
        return 1e3
    if "in billions" in ctx:
        return 1e9
    if "in millions" in ctx or "millions" in ctx:
        return 1e6
    return None


def _clean_label(x):
    x = re.sub(r"\s+", " ", x or "").strip(" :")
    return re.sub(r"^[-–—•·]+\s*", "", x)


def candidates(html: str):
    """Todas las filas que encajan con un concepto, con su escala y tipo de periodo."""
    p = _Tables()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001  HTML roto: lo que se haya leído
        pass
    out = []
    for ti, tab in enumerate(p.tables):
        rows = tab["rows"]
        if len(rows) < 3:
            continue
        years = _header_years(rows)
        idx = _current_index(years)
        if idx is None:
            continue
        head = " ".join(c["x"] for r in rows[:6] for c in r if not _row_values(r) or YEAR.search(c["x"]))
        if re.search(r"non-?gaap|reconciliation|adjusted", head, re.I):
            continue
        per = "T" if QTR.search(head) else ("A" if YR.search(head + " " + tab.get("antes", "")[-200:]) else None)
        scale = _scale(tab)
        sections, mine = [], []
        for r in rows:
            label = _clean_label(r[0]["x"]) if r else ""
            vals = _row_values(r)
            if label and not vals:
                sections = (sections + [label.lower()])[-2:]
                continue
            if not label or not vals or idx >= len(vals) or BAD.search(label):
                continue
            low, sec = label.lower(), " | ".join(sections)
            if not NOT_EPS.search(low) and abs(vals[idx]) < 1000 and (
                    ("diluted" in low and (EPS_SECTION.search(low) or EPS_SECTION.search(sec)))
                    or (EPS_SECTION.search(low) and sections and "diluted" in sections[-1])):
                mine.append({"concepto": "bpa_diluido", "bruto": vals[idx], "escala": 1.0, "fila": label, "tabla": ti, "periodo": per})
                continue
            for k, rxs in _RX.items():
                if not any(rx.match(label) for rx in rxs):
                    continue
                if k == "bpa_diluido":
                    continue
                else:
                    if any(EPS_SECTION.search(x) for x in sections[-1:]) or re.search(r"per share", label, re.I):
                        continue
                    attributable = bool(re.search(r"attributable to", label, re.I))
                    mine.append({"concepto": k, "bruto": vals[idx], "escala": scale, "fila": label, "tabla": ti,
                                 "periodo": per, "atribuible": attributable})
        n = len({c["concepto"] for c in mine})
        for c in mine:
            c["puntos_tabla"] = n
        out += mine
    return out


SCALES = (1e3, 1e6, 1e9)


def elegir(cands, ref=None):
    """Una cifra por concepto. «ref» = {concepto: valor del trimestre anterior (SEC)}
    para deducir la escala cuando la tabla no la dice y descartar filas absurdas.
    Preferencia: tabla con más conceptos (la cuenta de resultados), cifra atribuible
    a la compañía, trimestre antes que año, y orden de aparición."""
    import math
    ref = ref or {}
    out = {}
    table_scale = {}
    if ref.get("ingresos"):
        for c in cands:
            if c["concepto"] == "ingresos" and c["escala"] is None and c["bruto"]:
                table_scale.setdefault(c["tabla"], min(SCALES, key=lambda s: abs(math.log10(abs(c["bruto"] * s) / abs(ref["ingresos"])))))
    for k in CONCEPTOS:
        rows = []
        for c in cands:
            if c["concepto"] != k:
                continue
            c = dict(c)
            r = ref.get(k)
            if c["escala"] is None:
                if c["tabla"] in table_scale:
                    c["escala"] = table_scale[c["tabla"]]
                elif r and c["bruto"]:
                    c["escala"] = min(SCALES, key=lambda s: abs(math.log10(abs(c["bruto"] * s) / abs(r))))
                else:
                    continue
                c["escala_deducida"] = True
            c["valor"] = c["bruto"] * c["escala"]
            if r and k in ("ingresos",) and not (0.5 <= c["valor"] / r <= 2.0) and c["periodo"] != "A":
                continue
            rows.append(c)
        if not rows:
            continue
        rows.sort(key=lambda c: (c["periodo"] == "A", -c["puntos_tabla"], not c.get("atribuible"), c["tabla"]))
        if k == "beneficio_neto":   # dentro de la misma tabla, la línea atribuible a la compañía manda
            best = rows[0]
            same = [c for c in rows if c["tabla"] == best["tabla"] and c.get("atribuible") and not re.search(r"common|preferred", c["fila"], re.I)]
            if same:
                best = same[0]
            out[k] = best
        else:
            out[k] = rows[0]
    return out


def extract(html: str, ref=None):
    """{concepto: {valor, fila, tabla, periodo («T» trimestre / «A» año)}} con las cifras GAAP del trimestre actual."""
    return elegir(candidates(html), ref)
