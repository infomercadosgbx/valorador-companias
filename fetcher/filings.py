"""Últimos informes de la compañía a partir de data.sec.gov/submissions."""
from __future__ import annotations

import re

PERIODIC = ("10-Q", "10-K")
FOREIGN = ("20-F", "40-F", "6-K", "20-F/A", "40-F/A")


def archive_base(cik, accn):
    return f"https://www.sec.gov/Archives/edgar/data/{int(str(cik))}/{accn.replace('-', '')}"


def recent_rows(subs):
    r = (subs or {}).get("filings", {}).get("recent", {})
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "primaryDocument", "items"]
    n = len(r.get("accessionNumber", []))
    rows = []
    for i in range(n):
        rows.append({k: (r.get(k) or [""] * n)[i] for k in keys})
    rows.sort(key=lambda x: (x["filingDate"], x["accessionNumber"]), reverse=True)
    return rows


def filing_record(cik, row, tipo):
    base = archive_base(cik, row["accessionNumber"])
    return {
        "tipo": tipo,
        "formulario": row["form"],
        "fecha_presentacion": row["filingDate"],
        "fecha_periodo": row.get("reportDate") or None,
        "accn": row["accessionNumber"],
        "url_documento": f"{base}/{row['primaryDocument']}" if row.get("primaryDocument") else None,
        "url_indice": f"{base}/{row['accessionNumber']}-index.htm",
        "fuente": f"SEC EDGAR · {row['form']}",
    }


def latest_periodic(cik, subs):
    for row in recent_rows(subs):
        if row["form"] in PERIODIC:
            return filing_record(cik, row, "informe periódico")
    return None


def latest_earnings_8k(cik, subs):
    for row in recent_rows(subs):
        if row["form"] == "8-K" and "2.02" in [x.strip() for x in (row.get("items") or "").split(",")]:
            return filing_record(cik, row, "8-K de resultados (Item 2.02)")
    return None


ITEMS_8K = {
    "1.01": "acuerdo relevante", "1.02": "fin de un acuerdo relevante", "1.05": "incidente de ciberseguridad",
    "2.01": "compra o venta de activos", "2.02": "resultados", "2.03": "nueva deuda u obligación financiera",
    "2.05": "costes de reestructuración", "2.06": "deterioro de activos", "3.02": "venta de acciones no registrada",
    "4.01": "cambio de auditor", "5.02": "cambios en directivos o consejeros", "5.03": "cambio de estatutos",
    "5.07": "votaciones de la junta", "7.01": "comunicación al mercado (Reg FD)", "8.01": "otros hechos relevantes",
}


def recent_8k_news(cik, subs, today=None, days=45, limit=6):
    """8-K recientes como noticias oficiales (sin peticiones extra: salen de submissions)."""
    from datetime import date, timedelta
    today = today or date.today()
    desde = (today - timedelta(days=days)).isoformat()
    out = []
    for row in recent_rows(subs):
        if row["form"] not in ("8-K", "8-K/A") or row["filingDate"] < desde:
            continue
        items = [x.strip() for x in (row.get("items") or "").split(",") if x.strip() and x.strip() != "9.01"]
        temas = [ITEMS_8K[i] for i in items if i in ITEMS_8K]
        if not temas:
            continue
        rec = filing_record(cik, row, "8-K")
        out.append({"titular": f"{row['form']} a la SEC: " + (lambda t: t[:1].upper() + t[1:])("; ".join(temas)),
                    "medio": "SEC · 8-K (oficial)", "url": rec["url_documento"] or rec["url_indice"],
                    "fecha": row["filingDate"], "resumen": "Comunicación oficial de la compañía. Items: " + ", ".join(items) + ".",
                    "oficial": True})
        if len(out) >= limit:
            break
    return out


# Otras presentaciones que pueden cambiar la tesis y que no son 8-K, 10-Q ni 10-K. Los formularios 4 ya se
# leen en directivos; el 144 (aviso de venta) y el 13G (inversor pasivo) son demasiado frecuentes y aportan poco.
OTRAS_FORMAS = {
    "3": "alta de un directivo o consejero (formulario 3)",
    "SC 13D": "accionista activista o de control con más del 5% (13D)", "SC 13D/A": "cambio en un 13D",
    "SCHEDULE 13D": "accionista activista o de control con más del 5% (13D)", "SCHEDULE 13D/A": "cambio en un 13D",
    "DEF 14A": "convocatoria de la junta (proxy)", "DEFA14A": "material adicional para la junta",
    "PRE 14A": "borrador de convocatoria de la junta", "PRE 14C": "decisión de accionistas por escrito (14C)",
    "DEF 14C": "decisión de accionistas por escrito (14C)",
    "S-1": "registro de una emisión", "S-3": "registro de una emisión (S-3)", "S-3ASR": "registro automático de emisión (S-3ASR)",
    "S-4": "registro por fusión o canje", "425": "comunicación sobre una fusión", "SC TO-T": "OPA de un tercero",
    "SC TO-I": "oferta de recompra propia", "SC 14D9": "posición del consejo ante una OPA",
    "10-K/A": "corrección del 10-K", "10-Q/A": "corrección del 10-Q", "NT 10-K": "retraso del 10-K", "NT 10-Q": "retraso del 10-Q",
    "15-12B": "baja de registro", "25-NSE": "exclusión de cotización",
}


def recent_other_filings(cik, subs, today=None, days=45, limit=12):
    """Presentaciones relevantes que no son 8-K/10-Q/10-K, de los últimos «days» días (sin peticiones extra)."""
    from datetime import date, timedelta
    today = today or date.today()
    desde = (today - timedelta(days=days)).isoformat()
    out = []
    for row in recent_rows(subs):
        if row["filingDate"] < desde:
            break
        forma = row["form"]
        if forma.startswith("424B"):
            desc = "folleto de una emisión (424B)"
        else:
            desc = OTRAS_FORMAS.get(forma)
        if not desc:
            continue
        rec = filing_record(cik, row, forma)
        out.append({"formulario": forma, "descripcion": desc, "fecha_presentacion": row["filingDate"],
                    "accn": row["accessionNumber"], "url_indice": rec["url_indice"],
                    "url_documento": rec["url_documento"], "fuente": f"SEC EDGAR · {forma}"})
        if len(out) >= limit:
            break
    return out


def is_foreign_filer(subs):
    rows = recent_rows(subs)
    forms = {r["form"] for r in rows}
    return bool(forms & set(FOREIGN)) and not (forms & set(PERIODIC))


_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_HREF = re.compile(r'href="([^"]+)"', re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)


def find_exhibit(index_html: str, wanted=("EX-99.1", "EX-99", "EX-99.01")) -> str | None:
    """Busca en la página índice del filing la fila cuyo «Type» es EX-99.1."""
    if not index_html:
        return None
    rows = []
    for m in _ROW.finditer(index_html):
        cells = [re.sub(r"<[^>]+>", "", c).strip().upper() for c in _CELL.findall(m.group(1))]
        href = _HREF.search(m.group(1))
        if href and cells:
            rows.append((cells, href.group(1)))
    for w in wanted:
        for cells, href in rows:
            if w in cells:
                href = href.replace("/ix?doc=", "")
                return href if href.startswith("http") else "https://www.sec.gov" + href
    return None


def list_exhibits(index_html: str):
    """Todos los anexos EX-99.x del filing con su descripción (nota, presentación, carta…)."""
    out = []
    for m in _ROW.finditer(index_html or ""):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in _CELL.findall(m.group(1))]
        href = _HREF.search(m.group(1))
        typ = next((c for c in cells if re.fullmatch(r"EX-99(\.\d+)?", c.upper())), None)
        if href and typ:
            u = href.group(1).replace("/ix?doc=", "")
            desc = cells[1] if len(cells) > 1 and cells[1] and cells[1].upper() != typ.upper() else ""
            out.append({"tipo": typ.upper(), "descripcion": desc, "url": u if u.startswith("http") else "https://www.sec.gov" + u})
    return out


def attach_exhibit(client, rec):
    """Añade url_ex99_1 y la lista de anexos EX-99 al registro del 8-K (una petición a www.sec.gov)."""
    if not rec:
        return rec
    try:
        html = client.get_text(rec["url_indice"])
    except Exception:  # el enlace es un extra: si falla, no rompe la extracción
        html = None
    rec["url_ex99_1"] = find_exhibit(html)
    rec["anexos"] = list_exhibits(html)
    return rec
