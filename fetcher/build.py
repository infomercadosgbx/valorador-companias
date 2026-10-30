"""Ensambla /data/<ticker>.json para una compañía."""
from __future__ import annotations

from datetime import datetime, timezone

from . import concepts as C
from . import extract as X
from . import filings as F
from . import validate as V

ESQUEMA = 1


class NoSecData(RuntimeError):
    """La SEC no devuelve nada utilizable: el Action debe fallar y abrir un Issue."""


def base_record(company):
    return {
        "esquema": ESQUEMA,
        "ticker": company["ticker"],
        "nombre": company["nombre"],
        "cik": company["cik"],
        "color": company.get("color"),
        "monograma": company.get("monograma"),
        "unidades": "USD salvo BPA (USD/acción) y acciones (número)",
    }


def build_from_sec(company, cf, subs):
    """Lógica pura (sin red): companyfacts + submissions -> registro y avisos."""
    cik = company["cik"]
    rec = base_record(company)
    avisos = []
    if not cf and not subs:
        raise NoSecData(f"{company['ticker']}: la SEC no devuelve companyfacts ni submissions (CIK {cik}).")

    rec["sec"] = {
        "nombre_registrado": (subs or {}).get("name") or (cf or {}).get("entityName"),
        "fin_ejercicio": (subs or {}).get("fiscalYearEnd"),
        "sic": (subs or {}).get("sic"),
        "sic_descripcion": (subs or {}).get("sicDescription"),
        "url_empresa": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(str(cik))}&type=&dateb=&owner=include&count=40",
    }
    rec["ultimo_informe"] = F.latest_periodic(cik, subs) if subs else None
    rec["ultimo_8k_resultados"] = F.latest_earnings_8k(cik, subs) if subs else None

    facts = (cf or {}).get("facts", {})
    if C.GAAP not in facts:
        if "ifrs-full" in facts or (subs and F.is_foreign_filer(subs)):
            rec["soportada"] = False
            avisos.append(X.warn("error", "no_soportada",
                "Compañía extranjera (20-F / IFRS): todavía no está soportada. No se muestran cifras."))
            rec["avisos"] = avisos
            return rec
        raise NoSecData(f"{company['ticker']}: companyfacts sin datos US-GAAP.")
    rec["soportada"] = True

    ref_end = X.revenue_reference_end(cf)
    if ref_end is None:
        raise NoSecData(f"{company['ticker']}: no hay ingresos en ninguna etiqueta conocida.")
    fye = (subs or {}).get("fiscalYearEnd") or None
    if not fye:
        ann = [f for t in C.FLOW_CONCEPTS["ingresos"]["tags"] for f in X.raw_facts(cf, t, "USD")
               if f.get("start") and f.get("form", "").startswith("10-K")]
        fye = max(ann, key=lambda f: f["end"])["end"][5:].replace("-", "") if ann else "1231"
    rec["referencia_fecha_datos"] = ref_end.isoformat()

    rec["resultados"] = {}
    for key in C.FLOW_CONCEPTS:
        flow, w = X.build_flow(cf, cik, key, ref_end, fye)
        rec["resultados"][key] = flow
        avisos += w

    rec["balance"] = {}
    for key in C.INSTANT_CONCEPTS:
        inst, w = X.build_instant(cf, cik, key, ref_end)
        rec["balance"][key] = inst
        avisos += w
    rec["acciones_en_circulacion"] = X.shares_outstanding(cf, cik)

    rev = rec["resultados"]["ingresos"]
    if not rev["anual"] and not rev["trimestral"]:
        raise NoSecData(f"{company['ticker']}: no se ha podido construir la serie de ingresos.")
    avisos += V.check_revenue_drop(rev)
    avisos += V.check_jumps(rev)
    avisos += V.check_fiscal_calendar(rev)
    for key in ("ingresos", "beneficio_operativo", "beneficio_neto"):
        avisos += V.check_quarters_vs_annual(rec["resultados"][key], key)
    avisos += V.check_latest_filing(ref_end, rec["ultimo_informe"])
    rec["avisos"] = avisos
    return rec


def build_company(client, company, price_provider, price_warning=None):
    cik = company["cik"]
    cf = client.companyfacts(cik)
    subs = client.submissions(cik)
    rec = build_from_sec(company, cf, subs)
    if rec.get("ultimo_8k_resultados"):
        F.attach_exhibit(client, rec["ultimo_8k_resultados"])
    # Precio y recomendaciones (secundarios: un fallo solo genera aviso)
    rec["precio"] = None
    rec["consenso_automatico"] = None
    if price_warning:
        rec["avisos"].append(X.warn("aviso", "sin_precio", price_warning))
    else:
        try:
            rec["precio"] = price_provider.quote(company["ticker"])
            if rec["precio"] is None:
                rec["avisos"].append(X.warn("aviso", "sin_precio",
                    f"{price_provider.nombre} no devuelve precio para {company['ticker']}."))
        except Exception as e:  # noqa: BLE001
            rec["avisos"].append(X.warn("aviso", "sin_precio", f"Error del proveedor de precios: {e}"))
        try:
            rec["consenso_automatico"] = price_provider.recommendations(company["ticker"])
        except Exception as e:  # noqa: BLE001
            rec["avisos"].append(X.warn("info", "sin_consenso", f"Recomendaciones no disponibles: {e}"))
    rec["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return rec
