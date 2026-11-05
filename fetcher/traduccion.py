"""Traducción al español de lo que se copia de la nota de resultados.

Dos vías, sin servicios de pago:
  - Automática para lo estructurado: las filas de tablas (etiqueta + cifras) y las
    horquillas de la guía («Revenue: $2,365 – $2,395 million» → «Ingresos: 2.365–2.395 M$»),
    con un glosario fijo y el formato de cifras en español.
  - Para las frases: i18n/notas_es.json ({"t": {original: traducción}}), que rellena la
    tarea programada «Revisión tras resultados» (ver propuestas/INSTRUCCIONES.md) o
    cualquiera a mano. Lo que falte se muestra en inglés, marcado como «sin traducir».

`pendientes(root)` lista las frases sin traducir de los informes de resultados vigentes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GLOSARIO = {
    "revenue": "Ingresos", "revenues": "Ingresos", "total revenue": "Ingresos totales", "total revenues": "Ingresos totales",
    "net revenue": "Ingresos netos", "total net revenue": "Ingresos netos totales", "net sales": "Ventas netas",
    "organic revenue": "Ingresos orgánicos", "organic revenue performance": "Crecimiento orgánico de ingresos",
    "change in revenues year over year": "Variación interanual de los ingresos",
    "change in constant currency revenues year over year": "Variación interanual de los ingresos a tipo de cambio constante",
    "gross margin": "Margen bruto", "gaap gross margin": "Margen bruto (GAAP)", "gross profit": "Beneficio bruto",
    "operating income": "Beneficio operativo", "income from operations": "Beneficio operativo",
    "operating profit": "Beneficio operativo", "core operating profit": "Beneficio operativo subyacente (core)",
    "operating margin": "Margen operativo", "core operating margin": "Margen operativo subyacente (core)",
    "net income": "Beneficio neto", "net margin": "Margen neto",
    "net income from continuing operations": "Beneficio neto de actividades continuadas",
    "net income available to common stockholders": "Beneficio neto atribuible a los accionistas",
    "other income (expense), net": "Otros ingresos (gastos) netos",
    "adjusted ebitda": "EBITDA ajustado", "adjusted ebitda margin": "Margen de EBITDA ajustado",
    "ongoing operations adjusted ebitda": "EBITDA ajustado de operaciones continuadas",
    "ongoing operations adjusted fcfbg": "Caja libre ajustada antes de crecimiento (FCFbG) de operaciones continuadas",
    "free cash flow": "Flujo de caja libre", "cash flow from operations": "Caja operativa",
    "net cash provided by operating activities": "Caja operativa", "operating cash flow": "Caja operativa",
    "capital expenditures": "Inversiones (capex)",
    "eps": "BPA", "core eps": "BPA subyacente (core)", "core constant currency eps": "BPA subyacente a tipo de cambio constante",
    "diluted": "BPA diluido", "basic": "BPA básico", "diluted eps": "BPA diluido",
    "earnings per common share - diluted": "BPA diluido", "diluted net income per common share": "BPA diluido",
    "diluted net income per share": "BPA diluido", "basic net income per share": "BPA básico",
    "u.s.": "EE. UU.", "us": "EE. UU.", "united states": "EE. UU.", "international": "Internacional", "rest of world": "Resto del mundo",
    "semiconductor solutions": "Soluciones de semiconductores", "infrastructure software": "Software de infraestructura",
    "arr": "ARR (ingresos recurrentes anualizados)", "north america": "Norteamérica", "aws": "AWS", "consolidated": "Consolidado",
    "return on capital employed (roce) (%)": "Rentabilidad sobre el capital empleado (ROCE, %)",
    "capital expenditures (capex) ($ b)": "Inversiones (capex, miles de M$)", "affiliate capex ($ b)": "Capex de participadas (miles de M$)",
    "debt-to-cffo ratio": "Deuda / caja operativa", "net oil-equivalent production (mboed)": "Producción neta (miles de barriles equivalentes/día)",
    "ratio": "Ratio", "foreign exchange translation": "Efecto del tipo de cambio",
}
_CAB = [(r"\(dollars in millions, except per share data\)", "(millones de $, salvo datos por acción)"),
        (r"\((?:\$ )?in millions, except (?:for )?percentages(?: and per share amounts)?(?:; unaudited)?\)", "(millones de $, salvo porcentajes y datos por acción)"),
        (r"\((?:\$ )?in millions(?:, except eps)?\)", "(millones de $)"), (r"\(dollars in millions\)", "(millones de $)"),
        (r"% change", "% var."), (r"\bchange\b", "Var."), (r"\blow\b", "Mínimo"), (r"\bhigh\b", "Máximo"),
        (r"\bquarter ended\b", "Trimestre"), (r"\bthree months ended\b", "Trimestre"), (r"\bnine months ended\b", "Nueve meses"),
        (r"\bunit\b", "Unidad"), (r"\bytd\b", "Acumulado"), (r"\b([1-4])Q\s?(?:20)?(\d{2})\b", r"\1T\2")]


def _key(etq: str) -> str:
    e = re.sub(r"[*†‡]+|\s+\d$|\s\d\s", " ", etq or "")
    return re.sub(r"\s+", " ", e).strip(" :").lower()


def etiqueta(etq: str, mapa: dict | None = None):
    """Traducción de una etiqueta de fila o de guía (glosario, luego i18n). None si no se sabe."""
    if mapa and etq in mapa:
        return mapa[etq]
    return GLOSARIO.get(_key(etq))


def cifra(v: str, unidad: str | None = None, solo_numero=False) -> str:
    """«$2,365» → «2.365 $»; «91.5%» → «91,5%»; «$(8,221)» → «(8.221 $)»; «(35)bps» → «(35) pb».
    Con unidad: «2.365 M$». solo_numero: sin «$» (la cabecera de la tabla ya da la unidad)."""
    s = (v or "").strip()
    suf = re.search(r"(bps|pp)$", s)
    if suf:
        base = cifra(s[:suf.start()], solo_numero=True)
        return f"{base} {'pb' if suf.group(1) == 'bps' else 'pp'}"
    neg = s.startswith("(") and s.endswith(")") or "$(" in s
    pct = s.endswith("%")
    sign = "+" if s.lstrip("($").startswith("+") else ("−" if re.match(r"^\(?\$?\s?[-−]", s) else "")
    num = re.sub(r"[^\d.,]", "", s)
    if not num:
        return s
    es = num.replace(",", "§").replace(".", ",").replace("§", ".")
    out = f"{sign}{es}{'%' if pct else ''}"
    if solo_numero:
        pass
    elif not pct and unidad and "$" in s:
        out += {"million": " M$", "billion": " mil M$", "thousand": " miles de $"}.get(unidad, " $")
    elif not pct and "$" in s:
        out += " $"
    return f"({out})" if neg and not pct else out


_GROW = re.compile(r"^(?P<etq>[^:]{2,90}):\s(?P<a>[^–]+?)(?:\s–\s(?P<b>.+))?$")


def frase_guia(t: str, mapa: dict | None = None):
    """Frases de guía generadas a partir de tablas («Revenue: $2,365 – $2,395 million»)."""
    m = _GROW.match(t or "")
    if not m:
        return None
    lab = etiqueta(m.group("etq"), mapa)
    if not lab:
        return None
    b = m.group("b")
    unidad = None
    for u in ("million", "billion", "thousand"):
        if (b or m.group("a")).rstrip().endswith(u):
            unidad = u
    a = re.sub(r"\s*(million|billion|thousand)$", "", m.group("a").strip())
    if b is None:
        return f"{lab}: {cifra(a, unidad or 'million')}"
    b = re.sub(r"\s*(million|billion|thousand)$", "", b.strip())
    if a.endswith("%") and b.endswith("%"):
        return f"{lab}: {cifra(a)[:-1]}–{cifra(b)}"
    ca, cb = cifra(a, unidad or "million"), cifra(b, unidad or "million")
    ua = re.sub(r"^[^ ]+", "", ca)
    return f"{lab}: {ca.replace(ua, '') if ua and ua == re.sub(r'^[^ ]+', '', cb) else ca}–{cb}"


def cabecera(c: str | None):
    if not c:
        return None
    s = c
    for rx, rep in _CAB:
        s = re.sub(rx, rep, s, flags=re.I)
    s = re.sub(r"\bQ([1-4])\s?'?(\d{2})\b", r"\1T\2", s)
    return s


def cargar(root: Path) -> dict:
    try:
        return (json.loads((root / "i18n" / "notas_es.json").read_text(encoding="utf-8")) or {}).get("t") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def aplicar(informe: dict, root: Path) -> dict:
    """Añade los campos *_es al informe (copia los bloques de la nota para no tocar data/<T>.json)."""
    mapa = cargar(root)
    falta = []

    def tr(t):
        if t in mapa:
            return mapa[t]
        falta.append(t)
        return None

    d = informe.get("destacados")
    if d:
        d = informe["destacados"] = json.loads(json.dumps(d))
        d["texto_es"] = [tr(t) for t in d.get("texto") or []]
        for f in d.get("filas") or []:
            f["etiqueta_es"] = etiqueta(f["etiqueta"], mapa) or tr(f["etiqueta"])
            f["valores_es"] = [cifra(v, solo_numero=bool(d.get("unidad"))) for v in f.get("valores") or []]
        d["cabecera_es"] = cabecera(d.get("cabecera"))
    g = informe.get("guia")
    if g and g.get("texto"):
        g["texto_es"] = [mapa.get(t) or frase_guia(t, mapa) or tr(t) for t in g["texto"]]
    c = informe.get("cita")
    if c and c.get("cita"):
        c = informe["cita"] = dict(c)
        c["cita_es"] = tr(c["cita"])
    informe["traduccion"] = {"pendientes": len(falta), "completa": not falta,
                             "fuente": "Glosario automático y i18n/notas_es.json (revisión tras resultados)"}
    return informe


def pendientes(root: Path):
    """[(ticker, periodo, texto)] sin traducir en el último informe de cada compañía."""
    out = []
    for idx in sorted((root / "data" / "resultados").glob("*/index.json")):
        try:
            it = (json.loads(idx.read_text(encoding="utf-8")).get("informes") or [])[0]
            rep = json.loads((idx.parent / it["json"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, IndexError, KeyError):
            continue
        mapa = cargar(root)
        for blk, key in (("destacados", "texto"), ("guia", "texto")):
            b = rep.get(blk) or {}
            es = b.get(f"{key}_es") or []
            for i, t in enumerate(b.get(key) or []):
                if not (es[i] if i < len(es) else None) and t not in mapa:
                    out.append((rep["ticker"], rep["periodo"], t))
        for f in (rep.get("destacados") or {}).get("filas") or []:
            if not f.get("etiqueta_es") and f["etiqueta"] not in mapa:
                out.append((rep["ticker"], rep["periodo"], f["etiqueta"]))
        c = rep.get("cita") or {}
        if c.get("cita") and not c.get("cita_es") and c["cita"] not in mapa:
            out.append((rep["ticker"], rep["periodo"], c["cita"]))
    return out


if __name__ == "__main__":   # python -m fetcher.traduccion  → lista lo pendiente
    import sys
    root = Path(__file__).resolve().parent.parent
    rows = pendientes(root)
    for t, p, s in rows:
        print(f"{t} {p}\t{s}")
    print(f"Frases sin traducir: {len(rows)}", file=sys.stderr)
