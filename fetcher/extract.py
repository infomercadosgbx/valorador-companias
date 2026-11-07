"""Extracción de series a partir de companyfacts de la SEC.

Reglas (ver README, «Reglas de extracción»):
  R1 Varias etiquetas por concepto; los ingresos se combinan por periodo.
  R2 Se descarta una etiqueta cuyo último dato va >60 días por detrás de los ingresos.
  R3 Un mismo periodo en varios informes: queda el presentado más recientemente.
  R4 Anual = 350–380 días en un 10-K. Trimestre = 80–100 días.
  R5 4T = año − 1T − 2T − 3T; se acepta solo si encaja con los trimestres
     vecinos (ratio 0,6–1,9).
  R6 Balance: solo ~16 meses desde el último informe.
  R7 Sin deuda etiquetada: deuda = 0 marcada como «asumida».
Cada cifra lleva {valor, fuente, url, fecha_presentacion, etiqueta, periodo...}.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import concepts as C

STALE_DAYS = 60
ANNUAL_DAYS = (350, 380)
QUARTER_DAYS = (80, 100)
H1_DAYS = (160, 195)   # 24 semanas (PepsiCo: trimestres de 12 semanas) = 168 días
M9_DAYS = (245, 290)   # 36 semanas = 252 días
Q4_RATIO = (0.6, 1.9)
Q4_RATIO_ESTACIONAL = (0.25, 4.0)   # compañías marcadas "estacional" en companies.json (Moderna)
BALANCE_WINDOW_DAYS = 487  # ~16 meses
DATE_TOL = 4               # días de tolerancia al casar fechas (años de 52/53 semanas)


# ---------------------------------------------------------------- utilidades
def d(s: str) -> date:
    return date.fromisoformat(s)


def duration(f) -> int:
    return (d(f["end"]) - d(f["start"])).days


def filing_index_url(cik, accn: str) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(str(cik))}/"
            f"{accn.replace('-', '')}/{accn}-index.htm")


def fy_label(end: date) -> int:
    """Año fiscal de un cierre. Un año de 52/53 semanas que acaba en los
    primeros días de enero pertenece al año natural anterior."""
    return end.year - 1 if (end.month == 1 and end.day <= 10) else end.year


def quarter_label(end: date, fye_mmdd: str) -> str:
    """Etiqueta «3T26» de un trimestre, según el cierre fiscal (MMDD)."""
    mm, dd = int(fye_mmdd[:2]), int(fye_mmdd[2:])
    anchors = []
    for y in (end.year - 1, end.year, end.year + 1):
        try:
            anchors.append(date(y, mm, dd))
        except ValueError:  # 29 de febrero
            anchors.append(date(y, mm, 28))
    anchor = min(a for a in anchors if a >= end - timedelta(days=10))
    q = 4 - round((anchor - end).days / 91.3)
    q = min(4, max(1, q))
    return f"{q}T{fy_label(anchor) % 100:02d}"


def raw_facts(cf, tag, unit, taxonomy=C.GAAP):
    """«Nombre» = us-gaap; «ns:Nombre» = otra taxonomía; «*:Nombre» = la primera
    taxonomía que lo tenga (extensiones propias, p. ej. amzn:)."""
    if ":" in tag:
        ns, tag = tag.split(":", 1)
        if ns == "*":
            for tx, facts in ((cf or {}).get("facts") or {}).items():
                if tx not in (C.GAAP, C.DEI) and tag in facts:
                    return (facts[tag].get("units") or {}).get(unit, [])
            return []
        taxonomy = ns
    try:
        return cf["facts"][taxonomy][tag]["units"][unit]
    except (KeyError, TypeError):
        return []


def latest_by(facts, keyfn):
    """R3: por cada clave, el hecho presentado más recientemente."""
    out = {}
    for f in facts:
        k = keyfn(f)
        cur = out.get(k)
        if cur is None or (f["filed"], f.get("accn", "")) > (cur["filed"], cur.get("accn", "")):
            out[k] = f
    return out


def last_end(facts) -> date | None:
    return max((d(f["end"]) for f in facts), default=None)


def point(f, cik, tag, taxonomy=C.GAAP, derived=None, value=None):
    form = f.get("form", "")
    p = {
        "valor": f["val"] if value is None else value,
        "fuente": f"SEC EDGAR · {form}" + (" (derivado)" if derived else ""),
        "url": filing_index_url(cik, f["accn"]),
        "fecha_presentacion": f["filed"],
        "etiqueta": tag if ":" in tag else f"{taxonomy}:{tag}",
        "periodo_fin": f["end"],
        "formulario": form,
        "accn": f["accn"],
    }
    if f.get("start"):
        p["periodo_inicio"] = f["start"]
    if derived:
        p["derivado"] = derived
    return p


def warn(nivel, codigo, mensaje, **extra):
    w = {"nivel": nivel, "codigo": codigo, "mensaje": mensaje}
    w.update(extra)
    return w


def find_near(mapping: dict, target: date, tol=DATE_TOL):
    """mapping: {date: x}. Devuelve x con fecha a ±tol días de target."""
    best = None
    for k, v in mapping.items():
        diff = abs((k - target).days)
        if diff <= tol and (best is None or diff < best[0]):
            best = (diff, v)
    return None if best is None else best[1]


# ------------------------------------------------- referencia de frescura (R2)
def revenue_reference_end(cf) -> date | None:
    ends = [last_end(raw_facts(cf, t, "USD")) for t in C.FLOW_CONCEPTS["ingresos"]["tags"]]
    ends = [e for e in ends if e]
    return max(ends, default=None)


def is_stale(tag_last: date | None, ref_end: date | None) -> bool:
    if tag_last is None:
        return True
    if ref_end is None:
        return False
    return tag_last < ref_end - timedelta(days=STALE_DAYS)


# --------------------------------------------------------- conceptos de flujo
def _classify(facts):
    """Separa hechos de duración en anual (10-K), trimestres y acumulados."""
    annual, quarters, h1, m9 = [], [], [], []
    for f in facts:
        if not f.get("start"):
            continue
        n = duration(f)
        if ANNUAL_DAYS[0] <= n <= ANNUAL_DAYS[1] and f.get("form", "").startswith("10-K"):
            annual.append(f)
        elif QUARTER_DAYS[0] <= n <= QUARTER_DAYS[1]:
            quarters.append(f)
        elif H1_DAYS[0] <= n <= H1_DAYS[1]:
            h1.append(f)
        elif M9_DAYS[0] <= n <= M9_DAYS[1]:
            m9.append(f)
    key = lambda f: (f["start"], f["end"])
    return {k: latest_by(v, key) for k, v in
            (("annual", annual), ("q", quarters), ("h1", h1), ("m9", m9))}


def choose_tags(cf, spec, ref_end, concept_key, preferida=None):
    """Ordena las etiquetas por recencia (R1) y aplica la regla de frescura (R2).
    preferida: etiqueta que manda si está al día (companies.json «etiqueta_ingresos»).
    Devuelve (lista ordenada de (tag, facts), avisos)."""
    warnings = []
    cands = []
    for i, tag in enumerate(spec["tags"]):
        facts = raw_facts(cf, tag, spec["unit"])
        if facts and tag.startswith("*:"):
            tx = next((t for t, fs in cf["facts"].items() if t not in (C.GAAP, C.DEI) and tag[2:] in fs), "ext")
            tag = f"{tx}:{tag[2:]}"
        if facts:
            cands.append((last_end(facts), i, tag, facts))
    cands.sort(key=lambda c: (-c[0].toordinal(), c[1]))
    if not cands:
        return [], warnings
    if preferida:
        pref = [c for c in cands if c[2] == preferida and not is_stale(c[0], ref_end)]
        if pref:
            cands = pref + [c for c in cands if c is not pref[0]]
            warnings.append(warn("info", "etiqueta_preferida",
                f"{spec['nombre']}: se usa «{preferida}» por ajuste de la compañía (companies.json), "
                "porque es el total de su cuenta de resultados; las demás etiquetas solo rellenan huecos.",
                concepto=concept_key, etiqueta=preferida))
        else:
            warnings.append(warn("aviso", "etiqueta_preferida_no_disponible",
                f"{spec['nombre']}: companies.json pide «{preferida}», pero no existe o está obsoleta; "
                "se usa la regla general.", concepto=concept_key, etiqueta=preferida))
    if spec.get("combine"):
        # Las obsoletas solo rellenan periodos antiguos que no cubren las frescas.
        for le, _, tag, _ in cands:
            if is_stale(le, ref_end) and concept_key != "ingresos":
                warnings.append(warn("info", "etiqueta_obsoleta",
                    f"{spec['nombre']}: «{tag}» termina el {le}; solo se usa para años antiguos.",
                    concepto=concept_key, etiqueta=tag))
        return [(t, f) for _, _, t, f in cands], warnings
    fresh = [(t, f) for le, _, t, f in cands if not is_stale(le, ref_end)]
    for le, _, tag, _ in cands:
        if is_stale(le, ref_end):
            warnings.append(warn("info" if (fresh or spec.get("opcional")) else "aviso", "etiqueta_obsoleta",
                f"{spec['nombre']}: se descarta «{tag}», su último dato ({le}) va más de "
                f"{STALE_DAYS} días por detrás de los ingresos ({ref_end}).",
                concepto=concept_key, etiqueta=tag))
    return fresh[:1], warnings


def _merge_tagged(tagged):
    """Une periodos de varias etiquetas: para cada periodo manda la primera
    etiqueta de la lista (la más reciente). Devuelve dicts {(start,end): (tag, fact)}."""
    out = {b: {} for b in ("annual", "q", "h1", "m9")}
    for tag, facts in tagged:
        cls = _classify(facts)
        for b in out:
            for k, f in cls[b].items():
                out[b].setdefault(k, (tag, f))
    return out


def _drop_mislabeled_quarters(m, spec, concept_key, fye_mmdd):
    """Errores de etiquetado XBRL: algún 10-K presenta la cifra ANUAL con un
    contexto de 3 meses (Oracle, «Revenues» en los 10-K de 2020 a 2022: el total
    del año con inicio 1-mar). Un «trimestre» que repite el valor del año que
    cierra en la misma fecha se descarta, y el 4T se deriva por la regla R5."""
    if spec.get("no_sum"):
        return []
    annual_by_end = {d(e): f["val"] for (_s, e), (_t, f) in m["annual"].items()}
    bad, tags = [], []
    for key, (tag, f) in sorted(m["q"].items()):
        a = find_near(annual_by_end, d(f["end"]))
        if a and abs(f["val"] - a) <= 0.005 * abs(a):
            del m["q"][key]
            bad.append(quarter_label(d(f["end"]), fye_mmdd))
            if tag not in tags:
                tags.append(tag)
    if not bad:
        return []
    return [warn("info", "trimestre_mal_etiquetado",
        f"{spec['nombre']} {', '.join(bad)}: la compañía etiquetó en XBRL el total del año como si fuera "
        f"un trimestre («{'», «'.join(tags)}»). Se descarta y el 4T se calcula como año − 1T − 2T − 3T.",
        concepto=concept_key, etiqueta=tags[0], periodos=bad)]


def build_flow(cf, cik, concept_key, ref_end, fye_mmdd, max_years=8, max_quarters=12, q4_state=None, estacional=False,
               preferida=None):
    """estacional: el 4T se compara solo con el 3T y con un rango más amplio (ventas
    concentradas en otoño-invierno: vacunas de Moderna); el 1T siguiente no sirve de referencia.
    q4_state: dict compartido entre conceptos. Los ingresos deciden qué 4T son
    coherentes (regla del ratio); el resto de conceptos sigue esa decisión, porque
    el ratio no sirve para magnitudes estacionales o con extraordinarios (caja de
    Amazon, beneficio neto con ganancias en participaciones)."""
    spec = C.FLOW_CONCEPTS[concept_key]
    if q4_state is None:
        q4_state = {"aceptados": set(), "rechazados": set()}
    warn_from = ref_end - timedelta(days=3 * 366) if ref_end else date.min
    tagged, warnings = choose_tags(cf, spec, ref_end, concept_key, preferida)
    result = {"nombre": spec["nombre"], "unidad": spec["unit"], "anual": [],
              "trimestral": [], "ttm": None, "etiquetas_usadas": []}
    if not tagged:
        return result, warnings
    m = _merge_tagged(tagged)
    no_sum = spec.get("no_sum", False)
    warnings += _drop_mislabeled_quarters(m, spec, concept_key, fye_mmdd)

    # --- anual
    annual = sorted(m["annual"].values(), key=lambda tf: tf[1]["end"])
    for tag, f in annual:
        pt = point(f, cik, tag)
        pt["periodo"] = str(fy_label(d(f["end"])))
        pt["dias"] = duration(f)
        result["anual"].append(pt)

    # --- trimestres: discretos + derivados de acumulados (R4, R5)
    q_by_end = {}   # date -> (pt)
    for (s, e), (tag, f) in m["q"].items():
        q_by_end[d(e)] = point(f, cik, tag)

    if not no_sum:
        starts = {d(s) for (s, _e) in list(m["annual"]) + list(m["h1"]) + list(m["m9"])}
        def ladder_for(start):
            lad = {}
            for b, n in (("h1", 6), ("m9", 9), ("annual", 12)):
                for (s, e), tf in m[b].items():
                    if abs((d(s) - start).days) <= DATE_TOL:
                        lad[n] = tf
            q1 = None
            for (s, e), tf in m["q"].items():
                if abs((d(s) - start).days) <= DATE_TOL:
                    q1 = tf
            if q1:
                lad[3] = q1
            return lad

        for start in sorted(starts):
            lad = ladder_for(start)
            # 2T y 3T a partir de acumulados, si no hay dato discreto.
            for n, prev in ((6, 3), (9, 6)):
                if n in lad and prev in lad:
                    end = d(lad[n][1]["end"])
                    if find_near(q_by_end, end) is None:
                        tag, f = lad[n]
                        val = f["val"] - lad[prev][1]["val"]
                        q_by_end[end] = point(f, cik, tag, value=val,
                            derived=f"Acumulado {n} meses − acumulado {prev} meses")
                        q_by_end[end]["periodo_inicio"] = (d(lad[prev][1]["end"]) + timedelta(days=1)).isoformat()
            # 4T = año − 1T − 2T − 3T
            if 12 in lad:
                tag, fa = lad[12]
                a_end, a_start = d(fa["end"]), d(fa["start"])
                if find_near(q_by_end, a_end) is None:
                    inside = sorted([(e, p) for e, p in q_by_end.items()
                                     if a_start - timedelta(days=DATE_TOL) <= d(p.get("periodo_inicio", e.isoformat())) and e < a_end - timedelta(days=45)],
                                    key=lambda x: x[0])
                    if len(inside) == 3:
                        val = fa["val"] - sum(p["valor"] for _, p in inside)
                        q4 = point(fa, cik, tag, value=val, derived="Año − 1T − 2T − 3T")
                        q4["periodo_inicio"] = (inside[-1][0] + timedelta(days=1)).isoformat()
                        if concept_key == "ingresos":
                            ok, motivo = _q4_fits(val, inside[-1][1]["valor"], q_by_end, a_end, spec, estacional)
                            q4_state["aceptados" if ok else "rechazados"].add(a_end)
                        else:
                            ok = not any(abs((a_end - e).days) <= DATE_TOL for e in q4_state["rechazados"])
                            motivo = "el 4T de ingresos de ese año tampoco encaja"
                        if ok:
                            q_by_end[a_end] = q4
                        elif a_end >= warn_from and concept_key == "ingresos":
                            warnings.append(warn("aviso", "4t_descartado",
                                f"{spec['nombre']} {quarter_label(a_end, fye_mmdd)}: el 4T derivado "
                                f"({val/1e6:,.0f} M) no encaja con los trimestres vecinos ({motivo}); se descarta, "
                                f"y con él el 4T del resto de conceptos de ese año.",
                                concepto=concept_key, periodo=quarter_label(a_end, fye_mmdd)))

    quarters = sorted(q_by_end.items())
    for end, pt in quarters:
        pt["periodo"] = quarter_label(end, fye_mmdd)
    result["trimestral"] = [pt for _, pt in quarters][-max_quarters:]

    # --- últimos 12 meses (4 trimestres consecutivos)
    if not no_sum and len(quarters) >= 4:
        last4 = [pt for _, pt in quarters[-4:]]
        span = (d(last4[-1]["periodo_fin"]) - d(last4[0].get("periodo_inicio", last4[0]["periodo_fin"]))).days
        if 350 <= span <= 380:
            result["ttm"] = {
                "valor": sum(p["valor"] for p in last4),
                "fuente": "SEC EDGAR (suma de 4 trimestres)",
                "url": last4[-1]["url"],
                "fecha_presentacion": max(p["fecha_presentacion"] for p in last4),
                "etiqueta": last4[-1]["etiqueta"],
                "periodo_inicio": last4[0].get("periodo_inicio"),
                "periodo_fin": last4[-1]["periodo_fin"],
                "derivado": " + ".join(p["periodo"] for p in last4),
            }
    result["anual"] = result["anual"][-max_years:]
    used = []
    for p in result["anual"] + result["trimestral"]:
        if p["etiqueta"] not in used:
            used.append(p["etiqueta"])
    result["etiquetas_usadas"] = used
    return result, warnings


def _q4_fits(q4, q3, q_by_end, a_end, spec, estacional=False):
    """R5: el 4T derivado se compara con 3T y con el 1T siguiente (ratio 0,6–1,9).
    Compañías estacionales: solo con el 3T y ratio 0,25–4."""
    neighbors = [q3]
    nxt = [p for e, p in q_by_end.items() if a_end < e <= a_end + timedelta(days=110)]
    if nxt and not estacional:
        neighbors.append(nxt[0]["valor"])
    lo, hi = Q4_RATIO_ESTACIONAL if estacional else Q4_RATIO
    if q4 > 0 and all(n > 0 for n in neighbors):
        ratios = [q4 / n for n in neighbors]
        bad = [r for r in ratios if not (lo <= r <= hi)]
        if bad:
            return False, "ratio " + ", ".join(f"{r:.2f}" for r in ratios)
        return True, ""
    # Con valores negativos el ratio no tiene sentido: solo se descartan
    # magnitudes desproporcionadas.
    scale = max(abs(n) for n in neighbors) or 1
    if abs(q4) > 3 * scale or (q4 <= 0 and all(n > 0 for n in neighbors) and spec["nombre"] == "Ingresos"):
        return False, "magnitud o signo incoherente"
    return True, ""


# ------------------------------------------------------- conceptos de balance
def _strategy_value_at(cf, strat, end, maps_cache):
    """Valor de una estrategia (componente principal + opcionales) a una fecha."""
    key = id(strat)
    if key not in maps_cache:
        def mp(tag):
            tf = raw_facts(cf, tag, "USD")
            return {d(k): v for k, v in latest_by(tf, lambda f: f["end"]).items()} if tf else {}
        maps_cache[key] = (mp(strat["required"][0]), [[(t, mp(t)) for t in g] for g in strat["optional"]])
    main, opts = maps_cache[key]
    f = find_near(main, end)
    if f is None:
        return None
    total, parts, newest = f["val"], [strat["required"][0]], f
    for group in opts:
        for t, mp_ in group:
            v = find_near(mp_, end)
            if v is not None:
                total += v["val"]; parts.append(t)
                if v["filed"] > newest["filed"]:
                    newest = v
                break
    return total, parts, newest, f["end"]


def year_end_series(cf, cik, concept_key, year_ends):
    """Saldos al cierre de cada ejercicio (de los 10-K), para ver la evolución de
    varios años. Se prueba cada estrategia en orden, también las de etiquetas
    antiguas, para no dejar huecos en años viejos."""
    spec = C.INSTANT_CONCEPTS[concept_key]
    cache, out = {}, []
    for ye in year_ends:
        for strat in spec["strategies"]:
            r = _strategy_value_at(cf, strat, ye, cache)
            if r:
                total, parts, newest, end_s = r
                pt = point(newest, cik, " + ".join(f"us-gaap:{p}" for p in parts), value=total,
                           derived=("Suma: " + " + ".join(parts)) if len(parts) > 1 else None)
                pt["periodo_fin"] = end_s
                pt.pop("periodo_inicio", None)
                pt["periodo"] = str(fy_label(d(end_s)))
                out.append(pt)
                break
    return out


def debt_maturities(cf, cik):
    """Calendario de vencimientos del último informe que lo publica."""
    rows = []
    for tag, label in C.DEBT_MATURITY_TAGS:
        for f in raw_facts(cf, tag, "USD"):
            rows.append((f["filed"], f["end"], tag, label, f))
    if not rows:
        return None
    newest_end = max(r[1] for r in rows)
    sel = {}
    for filed, end, tag, label, f in rows:
        if end == newest_end and (tag not in sel or filed > sel[tag][0]):
            sel[tag] = (filed, label, f)
    tramos = []
    for tag, label in C.DEBT_MATURITY_TAGS:
        if tag in sel:
            _, lab, f = sel[tag]
            pt = point(f, cik, tag)
            pt["tramo"] = lab
            tramos.append(pt)
    return {"fecha": newest_end, "tramos": tramos}


def build_instant(cf, cik, concept_key, ref_end):
    spec = C.INSTANT_CONCEPTS[concept_key]
    warnings = []
    obsoletas_con_saldo = []   # etiquetas descartadas por antiguas que aún tenían saldo
    for strat in spec["strategies"]:
        req = strat["required"][0]
        facts = raw_facts(cf, req, "USD")
        if not facts:
            continue
        le = last_end(facts)
        if is_stale(le, ref_end):
            ult = latest_by(facts, lambda f: f["end"]).get(le.isoformat())
            if ult and ult.get("val"):
                obsoletas_con_saldo.append((req, le, ult["val"]))
            warnings.append(warn("info", "etiqueta_obsoleta",
                f"{spec['nombre']}: se descarta «{req}» (último dato {le}, ingresos hasta {ref_end}).",
                concepto=concept_key, etiqueta=req))
            continue
        main = latest_by(facts, lambda f: f["end"])
        window_start = le - timedelta(days=BALANCE_WINDOW_DAYS)
        opt_maps = []
        for group in strat["optional"]:
            gm = []
            for t in group:
                tf = raw_facts(cf, t, "USD")
                if tf:
                    gm.append((t, {d(k): v for k, v in latest_by(tf, lambda f: f["end"]).items()}))
            opt_maps.append((group, gm))
        hist = []
        for end_s, f in sorted(main.items()):
            end = d(end_s)
            if end < window_start:
                continue
            total = f["val"]
            parts = [req]
            missing = []
            newest = f
            for group, gm in opt_maps:
                found = None
                for t, mp in gm:
                    v = find_near(mp, end)
                    if v is not None:
                        found = (t, v)
                        break
                if found:
                    total += found[1]["val"]
                    parts.append(found[0])
                    if found[1]["filed"] > newest["filed"]:
                        newest = found[1]
                else:
                    missing.append(" / ".join(group))
            pt = point(newest, cik, " + ".join(f"us-gaap:{p}" for p in parts), value=total,
                       derived=("Suma: " + " + ".join(parts)) if len(parts) > 1 else None)
            pt["periodo_fin"] = end_s
            pt.pop("periodo_inicio", None)
            if missing:
                pt["componentes_no_etiquetados"] = missing
            hist.append(pt)
        if not hist:
            continue
        latest = hist[-1]
        if latest.get("componentes_no_etiquetados"):
            warnings.append(warn("info", "componente_no_etiquetado",
                f"{spec['nombre']} a {latest['periodo_fin']}: no hay dato de "
                f"{', '.join(latest['componentes_no_etiquetados'])}; cuenta como 0.",
                concepto=concept_key))
        return {"nombre": spec["nombre"], "unidad": "USD", "ultimo": latest,
                "historico": hist, "asumido": False}, warnings

    if spec.get("assume_zero_if_missing") and obsoletas_con_saldo:
        # Había deuda y la etiqueta ha desaparecido: no es «sin deuda», es un cambio de etiquetas.
        tag, le, val = max(obsoletas_con_saldo, key=lambda x: x[1])
        warnings.append(warn("aviso", "deuda_no_encontrada",
            f"{spec['nombre']}: el último informe no trae ninguna etiqueta de deuda reconocida, pero el "
            f"{le.isoformat()} había {val / 1e6:,.0f} M$ en «{tag}». Probable cambio de etiquetas; se asume 0 "
            f"hasta revisarlo. Comprueba el balance del informe.".replace(",", "."),
            concepto=concept_key, etiqueta=tag))
        return {"nombre": spec["nombre"], "unidad": "USD", "asumido": True, "historico": [],
                "ultimo": {"valor": 0, "fuente": "Asumido (etiqueta de deuda no reconocida en el último informe)",
                           "url": None, "fecha_presentacion": None, "etiqueta": None,
                           "periodo_fin": ref_end.isoformat() if ref_end else None,
                           "asumido": True, "revisar": True}}, warnings
    if spec.get("assume_zero_if_missing"):
        warnings.append(warn("aviso", "deuda_asumida_cero",
            f"{spec['nombre']}: no hay ninguna etiqueta vigente; se asume 0.",
            concepto=concept_key))
        return {"nombre": spec["nombre"], "unidad": "USD", "asumido": True, "historico": [],
                "ultimo": {"valor": 0, "fuente": "Asumido (sin deuda etiquetada en XBRL)",
                           "url": None, "fecha_presentacion": None, "etiqueta": None,
                           "periodo_fin": ref_end.isoformat() if ref_end else None,
                           "asumido": True}}, warnings
    if not spec.get("opcional"):
        warnings.append(warn("aviso", "concepto_no_encontrado",
            f"{spec['nombre']}: no se ha encontrado ninguna etiqueta vigente.", concepto=concept_key))
    return {"nombre": spec["nombre"], "unidad": "USD", "ultimo": None,
            "historico": [], "asumido": False}, warnings


def shares_outstanding(cf, cik):
    """Acciones en circulación de la portada (dei). Con varias clases (Alphabet
    A/B/C) se suman los valores del mismo informe y fecha."""
    tax, tag = C.SHARES_OUTSTANDING_TAG
    facts = raw_facts(cf, tag, "shares", taxonomy=tax)
    if not facts:
        return None
    newest_filed = max(f["filed"] for f in facts)
    accn = max(f["accn"] for f in facts if f["filed"] == newest_filed)
    group = [f for f in facts if f["accn"] == accn]
    end = max(f["end"] for f in group)
    group = [f for f in group if f["end"] == end]
    total = sum(f["val"] for f in group)
    p = point(group[0], cik, f"{tax}:{tag}", taxonomy=tax, value=total,
              derived=f"Suma de {len(group)} clases" if len(group) > 1 else None)
    p["clases"] = len(group)
    return p
