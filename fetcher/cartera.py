"""Cartera de acciones de la compañía en otras empresas, del XBRL completo del último
10-Q/10-K (companyfacts no trae dimensiones).

  - Acciones cotizadas (valor razonable): EquitySecuritiesFvNi sin desglose. Alphabet
    las incluye en sus valores negociables a corto, es decir, dentro de la caja.
  - Participaciones con nombre: las que la compañía identifica por empresa participada
    (eje «Investee name»), p. ej. SpaceX en Alphabet. Las no cotizadas suelen ir sin
    nombre (Amazon solo distingue tipos de preferentes).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .bonds import find_files, label_for, parse_instance, parse_labels, target_filings
from .filings import archive_base

VERSION = 1
TIPOS = {
    "EquitySecuritiesFvNi": "cotizada",
    "EquitySecuritiesFvNiCurrentAndNoncurrent": "cotizada",
    "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount": "no_cotizada",
    "EquityMethodInvestments": "metodo_participacion",
}
NEUTRAL = {"FairValueByMeasurementFrequencyAxis"}      # «valor razonable recurrente»: no desglosa nada
NAME_AXIS = re.compile(r"Investee|InvestmentIssuer|InvestmentIdentifier", re.I)
OK_WITH_NAME = {"FinancialInstrumentAxis"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract(inst_xml: bytes, lab_xml: bytes | None):
    """{"fecha", "totales": {tipo: {valor, etiqueta}}, "detalle": [{nombre, tipo, valor, etiqueta}]}
    con la fecha de balance más reciente del informe."""
    facts, ctx, _units = parse_instance(inst_xml)
    labels = parse_labels(lab_xml)
    tot, det = {}, {}
    for f in facts:
        tipo = TIPOS.get(f["c"])
        c = ctx.get(f["ctx"])
        v = _num(f["v"])
        if not tipo or not c or c.get("start") or not c.get("end") or v is None:
            continue
        dims = {k: m for k, m in c["dims"].items() if k not in NEUTRAL}
        end = c["end"]
        if not dims:
            tot.setdefault(end, {})[tipo] = {"valor": v, "etiqueta": f"us-gaap:{f['c']}"}
            continue
        names = [a for a in dims if NAME_AXIS.search(a)]
        if len(names) != 1 or set(dims) - set(names) - OK_WITH_NAME:
            continue
        member = dims[names[0]]
        det.setdefault(end, {})[(member, tipo)] = {"nombre": label_for(member, labels), "tipo": tipo, "valor": v,
                                                   "etiqueta": f"us-gaap:{f['c']}"}
    fechas = sorted(set(tot) | set(det))
    if not fechas:
        return None
    fecha = fechas[-1]
    detalle = sorted((det.get(fecha) or {}).values(), key=lambda x: -x["valor"])
    return {"fecha": fecha, "totales": tot.get(fecha) or {}, "detalle": detalle}


def build(client, cik, subs, previous=None):
    """Bloque «cartera» de data/<T>.json, o None si el informe no trae nada.
    Reutiliza el anterior si el último informe no ha cambiado."""
    fl = target_filings(subs, max_q=0)
    if not fl:
        return None
    r = fl[0]
    if previous and previous.get("accn") == r["accessionNumber"] and previous.get("version") == VERSION:
        return previous
    base = archive_base(cik, r["accessionNumber"])
    inst_name, lab_name = find_files(client.get_json(f"{base}/index.json"))
    if not inst_name:
        return None
    inst = client.get_bytes(f"{base}/{inst_name}")
    lab = client.get_bytes(f"{base}/{lab_name}") if lab_name else None
    try:
        out = extract(inst, lab) if inst else None
    except ET.ParseError:
        return None
    if not out:
        return None
    out.update({"version": VERSION, "accn": r["accessionNumber"],
                "fuente": f"SEC EDGAR · {r['form']} (XBRL)", "formulario": r["form"],
                "fecha_presentacion": r["filingDate"], "url": f"{base}/{r['accessionNumber']}-index.htm"})
    return out
