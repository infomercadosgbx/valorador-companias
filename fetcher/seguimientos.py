"""Seguimientos: vigilar un asunto concreto de una compañía cada noche.

La lista está en /seguimientos.json (se edita a mano). Para cada seguimiento:
  - revisa los 8-K, 10-Q y 10-K presentados desde «desde» que aún no se han leído
    (documento principal y anexos 99 de los 8-K) y busca los términos;
  - revisa los titulares y entradillas de data/<T>.json → noticias;
  - clasifica cada mención: «cierre» (firma o desembolso), «cancelación»,
    «riesgo» (supervisión, investigación, pausa) o «mención» (sin novedad);
  - guarda el historial en data/<T>.json → seguimientos y genera avisos visibles
    en la web cuando hay una señal de cierre, cancelación o riesgo reciente.
Los documentos ya leídos se recuerdan para no volver a descargarlos.
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import date, timedelta
from pathlib import Path

from .extract import warn
from .filings import archive_base, recent_rows

FORMS = ("8-K", "8-K/A", "10-Q", "10-K", "10-Q/A", "10-K/A")
VENTANA_AVISO = 60          # días que un hallazgo con señal sigue como aviso
MAX_HALLAZGOS = 40
MAX_POR_DOC = 4
CONTEXTO = 320

SENALES_DEF = {
    "cancelacion": r"terminat|rescind|withdr[ae]w|cancel|revok|no longer (?:pursu|expect|anticipat)|not (?:likely to be|be) met",
    "cierre": r"definitive (?:loan|financing|agreement|documents?)|financial close|closed (?:the|its|on the|on a)? ?(?:loan|financing)"
              r"|(?:loan|guarantee|credit) agreement (?:with|was)|entered into (?:a|the) (?:loan|guarantee|credit)|first (?:advance|draw|disbursement)"
              r"|funded the loan|loan (?:was|has been) (?:closed|finali[sz]ed|signed)",
    "riesgo": r"inspector general|oversight|investigat|probe|scrutin|subpoena|congression|hearing|claw ?back|paus|freez|under review|re-?evaluat|lawsuit|challeng",
}
ORDEN = {"cancelacion": 0, "cierre": 1, "riesgo": 2, "mencion": 3}
ETIQUETA = {"cancelacion": "posible cancelación", "cierre": "posible cierre definitivo", "riesgo": "señal de riesgo",
            "mencion": "mención sin cambios"}


def cargar(root) -> dict:
    try:
        return json.loads((Path(root) / "seguimientos.json").read_text(encoding="utf-8")).get("seguimientos") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def texto_plano(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _re(lista):
    return re.compile("|".join(f"(?:{x})" for x in lista), re.I) if lista else None


HIPOTETICO = re.compile(r"\b(?:may|might|could|would|can|cannot|no assurance|there can be|if|whether|unless|risk|expects?|anticipat\w*"
                        r"|intends?|plans?|subject to|potential|uncertain)\b", re.I)


def clasificar(texto, cfg) -> str:
    """Señal de la frase que habla del asunto. Las frases hipotéticas o de riesgos genéricos
    («could be terminated», «no assurance») cuentan como simple mención."""
    sen = dict(SENALES_DEF, **(cfg.get("senales") or {}))
    pat = _re(cfg.get("terminos"))
    frases = [f for f in re.split(r"(?<=[.;!?])\s+", texto) if not pat or pat.search(f)] or [texto]
    for s in ("cancelacion", "cierre", "riesgo"):
        for f in frases:
            if sen.get(s) and re.search(sen[s], f, re.I) and not HIPOTETICO.search(f):
                return s
    return "mencion"


def buscar(texto, cfg, max_n=MAX_POR_DOC) -> list:
    """Fragmentos del texto donde aparece el asunto (términos + al menos un término de contexto)."""
    pat, ctx = _re(cfg.get("terminos")), _re(cfg.get("contexto"))
    if not pat:
        return []
    out, ult = [], -10**9
    for m in pat.finditer(texto):
        if m.start() < ult:
            continue
        a, b = max(0, m.start() - CONTEXTO), min(len(texto), m.end() + CONTEXTO)
        frag = texto[a:b]
        if ctx and not ctx.search(frag):
            continue
        ult = b
        frag = ("…" if a else "") + frag.strip() + ("…" if b < len(texto) else "")
        out.append(frag)
        if len(out) >= max_n:
            break
    return out


def _anexos_8k(client, cik, row):
    """Nombres de los anexos 99 de un 8-K (desde index.json del expediente)."""
    base = archive_base(cik, row["accessionNumber"])
    try:
        idx = client.get_json(f"{base}/index.json") or {}
    except Exception:  # noqa: BLE001
        return []
    names = [it.get("name", "") for it in (idx.get("directory") or {}).get("item") or []]
    return [f"{base}/{n}" for n in names if re.search(r"ex-?99|99[-_.]?\d|earnings|press", n, re.I)
            and n.lower().endswith((".htm", ".html", ".txt")) and n != row.get("primaryDocument")][:3]


def revisar_documentos(client, company, cfg, subs, ya_leidos) -> tuple[list, list]:
    """Devuelve (hallazgos nuevos, accn leídos en esta pasada)."""
    cik = company["cik"]
    desde = cfg.get("desde") or "2000-01-01"
    hallazgos, leidos = [], []
    for row in recent_rows(subs):
        if row["form"] not in FORMS or row["filingDate"] < desde or row["accessionNumber"] in ya_leidos:
            continue
        base = archive_base(cik, row["accessionNumber"])
        urls = [f"{base}/{row['primaryDocument']}"] if row.get("primaryDocument") else []
        if row["form"].startswith("8-K"):
            urls += _anexos_8k(client, cik, row)
        ok = False
        for u in urls:
            raw = client.get_text(u)
            if raw is None:
                continue
            ok = True
            for frag in buscar(texto_plano(raw), cfg):
                hallazgos.append({"fecha": row["filingDate"], "fuente": f"SEC · {row['form']}", "oficial": True,
                                  "url": u, "accn": row["accessionNumber"], "texto": frag,
                                  "senal": clasificar(frag, cfg)})
        if ok:
            leidos.append(row["accessionNumber"])
    return hallazgos, leidos


def revisar_noticias(noticias, cfg) -> list:
    out = []
    for n in noticias or []:
        txt = " ".join(x for x in (n.get("titular"), n.get("resumen")) if x)
        if not buscar(txt, cfg, 1):
            continue
        out.append({"fecha": (n.get("fecha") or "")[:10], "fuente": n.get("medio") or "Prensa", "oficial": bool(n.get("oficial")),
                    "url": n.get("url"), "texto": n.get("titular") or txt[:280], "senal": clasificar(txt, cfg)})
    return out


def _clave(h):
    return (h.get("url") or "") + "|" + (h.get("texto") or "")[:120]


def estado(cfg, hallazgos) -> dict:
    """Estado actual: la señal más reciente que no sea simple mención; si no hay, el estado de partida."""
    con = [h for h in hallazgos if h["senal"] != "mencion"]
    if not con:
        return {"codigo": "sin_cambios", "texto": cfg.get("estado_inicial") or "Sin novedades"}
    ult = max(con, key=lambda h: (h["fecha"], -ORDEN[h["senal"]]))
    return {"codigo": ult["senal"], "texto": f"{ETIQUETA[ult['senal']][:1].upper()}{ETIQUETA[ult['senal']][1:]} "
                                              f"({ult['fuente']}, {ult['fecha']}). Revisar el texto.",
            "fecha": ult["fecha"], "url": ult.get("url")}


def actualizar(client, company, rec, previous, root, subs=None, today=None) -> list:
    """Rellena rec['seguimientos'] y añade avisos. Devuelve la lista de seguimientos."""
    cfgs = cargar(root).get(company["ticker"].upper()) or []
    if not cfgs:
        return []
    today = today or date.today()
    prev = {s.get("id"): s for s in ((previous or {}).get("seguimientos") or [])}
    if subs is None:
        subs = client.submissions(company["cik"])
    out = []
    for cfg in cfgs:
        p = prev.get(cfg["id"]) or {}
        ya = set(p.get("documentos_leidos") or [])
        hist = list(p.get("hallazgos") or [])
        try:
            nuevos, leidos = revisar_documentos(client, company, cfg, subs, ya)
            error = None
        except Exception as e:  # noqa: BLE001  un fallo de lectura no tumba la compañía
            nuevos, leidos, error = [], [], str(e)[:200]
        nuevos += revisar_noticias(rec.get("noticias"), cfg)
        vistos = {_clave(h) for h in hist}
        for h in nuevos:
            if _clave(h) not in vistos:
                h["detectado"] = today.isoformat()
                hist.append(h)
                vistos.add(_clave(h))
        hist.sort(key=lambda h: (h.get("fecha") or "", h.get("oficial", False)), reverse=True)
        hist = hist[:MAX_HALLAZGOS]
        s = {"id": cfg["id"], "titulo": cfg.get("titulo") or cfg["id"], "descripcion": cfg.get("descripcion") or "",
             "desde": cfg.get("desde"), "fuentes_oficiales": cfg.get("fuentes_oficiales") or [],
             "estado": estado(cfg, hist), "hallazgos": hist,
             "documentos_leidos": sorted(ya | set(leidos)),
             "revisado": today.isoformat()}
        if error:
            s["error"] = error
        out.append(s)
        limite = (today - timedelta(days=VENTANA_AVISO)).isoformat()
        for h in hist:
            if h["senal"] != "mencion" and (h.get("fecha") or "") >= limite:
                rec.setdefault("avisos", []).append(warn(
                    "aviso", "seguimiento",
                    f"{s['titulo']}: {ETIQUETA[h['senal']]} en {h['fuente']} del {h['fecha']}. «{h['texto'][:220]}»",
                    seguimiento=cfg["id"], url=h.get("url")))
        if error:
            rec.setdefault("avisos", []).append(warn("info", "seguimiento_error",
                                                     f"{s['titulo']}: no se han podido leer los documentos nuevos ({error})."))
    rec["seguimientos"] = out
    return out
