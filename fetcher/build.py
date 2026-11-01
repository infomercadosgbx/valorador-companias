"""Ensambla /data/<ticker>.json para una compañía."""
from __future__ import annotations

from datetime import datetime, timezone

from . import concepts as C
from . import extract as X
from . import filings as F
from . import bonds as BONDS
from . import insiders as INS
from . import riskfactors as RISK
from . import segments as SEG
from . import pressrelease as PR
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


def _da_from_components(R, ref_end):
    """Si la etiqueta combinada de amortizaciones falta o está obsoleta, D&A =
    depreciación + amortización de intangibles, periodo a periodo."""
    da, dep, am = R["amortizacion"], R["depreciacion"], R["amort_intangibles"]
    last = max((p["periodo_fin"] for p in da["anual"] + da["trimestral"]), default=None)
    if last and not X.is_stale(X.d(last), ref_end):
        return []
    if not (dep["anual"] or dep["trimestral"]):
        return []

    # Se considera que la compañía publica la amortización de intangibles si la
    # etiqueta cubre al menos el 75% de los periodos con depreciación (Broadcom sí;
    # Alphabet solo la etiqueta en algún trimestre suelto).
    published = {b: len(am[b]) >= 0.75 * max(1, len(dep[b])) for b in ("anual", "trimestral")}
    gaps = []
    cur_bucket = ["anual"]

    def combine(dp, ap):
        if published[cur_bucket[0]] and (ap is None or ap.get("periodo_fin") != dp.get("periodo_fin")):
            gaps.append(dp["periodo"])
            return None  # la compañía tiene amortización de intangibles, pero no etiquetada este periodo
        if published[cur_bucket[0]] and ap is not None and ap.get("periodo_fin") == dp.get("periodo_fin"):
            q = dict(dp, valor=dp["valor"] + ap["valor"],
                     etiqueta=f"{dp['etiqueta']} + {ap['etiqueta']}",
                     derivado="Depreciación + amortización de intangibles")
            q["fecha_presentacion"] = max(dp["fecha_presentacion"], ap["fecha_presentacion"])
        else:
            q = dict(dp, derivado="Depreciación: la compañía no publica por separado la amortización de intangibles")
        return q

    out = {}
    for b in ("anual", "trimestral"):
        cur_bucket[0] = b
        am_by = {p["periodo"]: p for p in am[b]}
        merged = {p["periodo"]: p for p in da[b]}           # años antiguos con la etiqueta combinada
        for p in dep[b]:
            q = combine(p, am_by.get(p["periodo"]))
            if q is None:
                merged.pop(p["periodo"], None)
            else:
                merged[p["periodo"]] = q
        out[b] = sorted(merged.values(), key=lambda p: p["periodo_fin"])
    da["anual"], da["trimestral"] = out["anual"][-8:], out["trimestral"][-12:]
    if dep["ttm"]:
        cur_bucket[0] = "trimestral"
        dt = dict(dep["ttm"], periodo="UDM")
        da["ttm"] = combine(dt, am["ttm"])
        if da["ttm"]:
            da["ttm"]["fuente"] = "SEC EDGAR (suma de 4 trimestres)"
    used = []
    for p in da["anual"] + da["trimestral"]:
        if p["etiqueta"] not in used:
            used.append(p["etiqueta"])
    da["etiquetas_usadas"] = used
    da["por_componentes"] = True
    extra = []
    gy = sorted({g for g in gaps if g and g.isdigit()})
    if not published["anual"] and not published["trimestral"]:
        da["solo_depreciacion"] = True
    if gy:
        extra.append(X.warn("aviso", "amortizacion_incompleta",
            f"Amortizaciones (D&A) {', '.join(gy)}: la amortización de intangibles de esos años no está en una etiqueta "
            f"estándar de la SEC; se dejan vacíos (y el EBITDA de esos años) en lugar de mostrar solo la depreciación.",
            concepto="amortizacion"))
    return extra + [X.warn("info", "amortizacion_por_componentes",
                   "Amortizaciones (D&A): la compañía no usa la etiqueta combinada; se suman depreciación "
                   "(us-gaap:Depreciation) y amortización de intangibles (us-gaap:AmortizationOfIntangibleAssets).",
                   concepto="amortizacion")]


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
    q4_state = {"aceptados": set(), "rechazados": set()}
    for key in C.FLOW_CONCEPTS:  # «ingresos» va primero: decide qué 4T son coherentes
        flow, w = X.build_flow(cf, cik, key, ref_end, fye, max_quarters=24, q4_state=q4_state)
        rec["resultados"][key] = flow
        avisos += w

    avisos += _da_from_components(rec["resultados"], ref_end)

    rec["balance"] = {}
    year_ends = [X.d(p["periodo_fin"]) for p in rec["resultados"]["ingresos"]["anual"]][-7:]
    for key in C.INSTANT_CONCEPTS:
        inst, w = X.build_instant(cf, cik, key, ref_end)
        inst["anual"] = X.year_end_series(cf, cik, key, year_ends)
        if key == "deuda" and inst.get("asumido") and not inst["anual"]:
            inst["anual"] = [{"valor": 0, "asumido": True, "periodo": str(X.fy_label(ye)),
                              "periodo_fin": ye.isoformat(), "fuente": "Asumido (sin deuda etiquetada en XBRL)",
                              "url": None, "fecha_presentacion": None, "etiqueta": None} for ye in year_ends]
        rec["balance"][key] = inst
        avisos += w
    rec["vencimientos_deuda"] = X.debt_maturities(cf, cik)
    rec["acciones_en_circulacion"] = X.shares_outstanding(cf, cik)
    if rec["acciones_en_circulacion"] is None:
        dil = rec["resultados"]["acciones_diluidas_media"]["trimestral"]
        if dil:
            p = dict(dil[-1])
            p["derivado"] = (f"Acciones diluidas medias del {p['periodo']}: la portada da el número "
                             f"por clase de acción y la API de la SEC no lo publica")
            rec["acciones_en_circulacion"] = p
            avisos.append(X.warn("info", "acciones_diluidas",
                f"Acciones: se usan las diluidas medias del {p['periodo']} ({p['valor']/1e6:,.0f} M)."))
        else:
            avisos.append(X.warn("aviso", "concepto_no_encontrado", "No se encuentra el número de acciones."))

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


def _id_from_extension(rec):
    """Sin I+D en companyfacts (Amazon): usa el gasto de tecnología de su etiqueta
    propia, leído del XBRL completo de los últimos informes."""
    R = rec.get("resultados") or {}
    cur = R.get("investigacion_desarrollo") or {}
    tech = (rec.get("segmentos") or {}).get("gasto_tecnologia")
    if cur.get("anual") or cur.get("trimestral") or not tech or not (tech.get("anual") or tech.get("trimestral")):
        return
    tri, anu = tech.get("trimestral") or [], tech.get("anual") or []
    ttm = None
    last4 = tri[-4:]
    if len(last4) == 4 and (X.d(last4[-1]["periodo_fin"]) - X.d(last4[0]["periodo_inicio"])).days <= 380:
        ttm = dict(last4[-1], valor=sum(p["valor"] for p in last4), periodo_inicio=last4[0]["periodo_inicio"],
                   derivado=" + ".join(p["periodo"] for p in last4), periodo="UDM")
    elif anu:
        ttm = dict(anu[-1], periodo="UDM")
    ref = (R.get("ingresos") or {}).get("ttm") or {}
    if ttm and ref.get("periodo_fin") and ttm["periodo_fin"] != ref["periodo_fin"]:
        ttm = None
    R["investigacion_desarrollo"] = dict(cur, nombre="Tecnología e infraestructura (en lugar de I+D)", anual=anu, trimestral=tri, ttm=ttm,
                                         etiquetas_usadas=sorted({p["etiqueta"] for p in tri + anu}),
                                         nota="La compañía no publica I+D: se usa su gasto de tecnología (etiqueta propia, XBRL completo de los últimos informes).")
    rec.setdefault("avisos", []).append(X.warn("info", "id_tecnologia",
        f"I+D: la compañía no lo publica; se usa «{tech.get('concepto')}» de sus últimos informes (XBRL completo), solo los últimos años."))


class Memo:
    """Envuelve el cliente de la SEC y recuerda las descargas durante una compañía
    (bonos y segmentos leen los mismos informes XBRL)."""

    def __init__(self, client):
        self._c, self._cache = client, {}

    def __getattr__(self, name):
        return getattr(self._c, name)

    def _memo(self, kind, url):
        k = (kind, url)
        if k not in self._cache:
            self._cache[k] = getattr(self._c, kind)(url)
        return self._cache[k]

    def get_bytes(self, url):
        return self._memo("get_bytes", url)

    def get_json(self, url):
        return self._memo("get_json", url)

    def get_text(self, url):
        return self._c.get_text(url)

    def clear(self):
        self._cache.clear()


def build_company(client, company, price_provider, price_warning=None, previous=None, history_provider=None, history_warning=None):
    cik = company["cik"]
    cf = client.companyfacts(cik)
    subs = client.submissions(cik)
    rec = build_from_sec(company, cf, subs)
    if rec.get("ultimo_8k_resultados"):
        F.attach_exhibit(client, rec["ultimo_8k_resultados"])
        try:
            PR.attach(client, rec["ultimo_8k_resultados"], (previous or {}).get("ultimo_8k_resultados"))
        except Exception as e:  # noqa: BLE001  extra
            rec["avisos"].append(X.warn("info", "nota_no_disponible", f"No se pudo leer la nota de resultados: {type(e).__name__}"))
    client = Memo(client)
    rec["bonos"] = None
    if rec.get("soportada") and subs:
        try:
            rec["bonos"] = BONDS.build(client, company["cik"], subs, (previous or {}).get("bonos"))
        except Exception as e:  # noqa: BLE001  el detalle de bonos es un extra
            rec["avisos"].append(X.warn("info", "bonos_no_disponibles", f"No se pudo leer el detalle de bonos: {e}"))
    prev = previous or {}
    if rec.get("soportada") and subs:
        fyem = 12
        an = rec["resultados"]["ingresos"]["anual"]
        if an:
            fyem = X.d(an[-1]["periodo_fin"]).month
        for key, mod, args, nombre in (("segmentos", SEG, {"fye_month": fyem}, "segmentos"),
                                       ("directivos", INS, {}, "operaciones de directivos"),
                                       ("riesgos_10k", RISK, {}, "cambios en los riesgos del 10-K")):
            try:
                rec[key] = mod.build(client, company["cik"], subs, prev.get(key), **args)
            except Exception as e:  # noqa: BLE001  extras: un fallo solo genera aviso
                rec[key] = prev.get(key)
                rec["avisos"].append(X.warn("info", f"{key}_no_disponible", f"No se pudo leer {nombre}: {type(e).__name__}: {e}"))
    client.clear()
    _id_from_extension(rec)
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
        for key, fn in (("resultados_previstos", "earnings"), ("noticias", "news")):
            try:
                rec[key] = getattr(price_provider, fn)(company["ticker"])
            except Exception as e:  # noqa: BLE001
                rec[key] = prev.get(key)
                rec["avisos"].append(X.warn("info", f"sin_{key}", f"{key.replace('_', ' ').capitalize()} no disponibles: {e}"))
        try:
            rec["consenso_automatico"] = price_provider.recommendations(company["ticker"])
        except Exception as e:  # noqa: BLE001
            rec["avisos"].append(X.warn("info", "sin_consenso", f"Recomendaciones no disponibles: {e}"))
    # Histórico de cotizaciones (secundario: si falla, se conserva el anterior y se avisa)
    rec["historico_precio"] = (previous or {}).get("historico_precio")
    if history_provider is None:
        if history_warning:
            rec["avisos"].append(X.warn("info", "sin_historico", history_warning))
    else:
        try:
            h = history_provider.history(company["ticker"])
            if h:
                rec["historico_precio"] = h
        except Exception as e:  # noqa: BLE001
            rec["avisos"].append(X.warn("info", "sin_historico", f"Histórico de cotizaciones no disponible: {e}"))
    rec["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return rec
