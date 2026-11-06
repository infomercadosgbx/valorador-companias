"""Validaciones que generan avisos visibles en la web (nunca fallan en silencio)."""
from __future__ import annotations

from datetime import date, timedelta

from .extract import warn

SUM_TOLERANCE = 0.01   # 1 %
DROP_THRESHOLD = 0.25  # caída anual de ingresos que hace sospechar de discontinuadas
QOQ_UP, QOQ_DOWN = 0.60, -0.35
YOY_UP, YOY_DOWN = 1.50, -0.60   # compañías estacionales: mismo trimestre del año anterior


def _d(s):
    return date.fromisoformat(s)


def check_quarters_vs_annual(flow, concept_key):
    out = []
    quarters = flow.get("trimestral", [])
    for a in flow.get("anual", []):
        a_start, a_end = _d(a["periodo_inicio"]), _d(a["periodo_fin"])
        inside = [q for q in quarters
                  if a_start - timedelta(days=5) <= _d(q.get("periodo_inicio", q["periodo_fin"]))
                  and _d(q["periodo_fin"]) <= a_end + timedelta(days=5)]
        if len(inside) != 4 or inside[-1].get("derivado") == "Año − 1T − 2T − 3T":
            continue  # incompleto, o 4T derivado (suma igual por construcción)
        total = sum(q["valor"] for q in inside)
        if a["valor"] and abs(total - a["valor"]) / abs(a["valor"]) > SUM_TOLERANCE:
            out.append(warn("aviso", "trimestres_no_suman",
                f"{flow['nombre']} {a['periodo']}: los 4 trimestres suman {total/1e6:,.0f} M "
                f"y el anual es {a['valor']/1e6:,.0f} M.", concepto=concept_key, periodo=a["periodo"]))
    return out


def check_revenue_drop(flow):
    out = []
    an = flow.get("anual", [])
    for prev, cur in zip(an, an[1:]):
        if prev["valor"] and prev["valor"] > 0:
            ch = cur["valor"] / prev["valor"] - 1
            if ch < -DROP_THRESHOLD:
                out.append(warn("aviso", "posible_discontinuada",
                    f"Ingresos {cur['periodo']}: caen un {abs(ch):.0%} frente a {prev['periodo']}. "
                    f"Posible operación discontinuada o reclasificación (como AppLovin 2023); "
                    f"compara años con cuidado.", concepto="ingresos", periodo=cur["periodo"]))
    return out


def check_jumps(flow, estacional=False):
    if estacional:
        return _check_jumps_yoy(flow)
    out = []
    q = flow.get("trimestral", [])
    def per_day(p):   # trimestres de distinta duración (PepsiCo: 12 y 16 semanas) se comparan por día
        try:
            d = (_d(p["periodo_fin"]) - _d(p["periodo_inicio"])).days + 1
            return p["valor"] / d if d > 0 else p["valor"]
        except (KeyError, TypeError, ValueError):
            return p["valor"]
    for prev, cur in zip(q, q[1:]):
        if prev["valor"] and prev["valor"] > 0:
            ch = per_day(cur) / per_day(prev) - 1
            if ch > QOQ_UP or ch < QOQ_DOWN:
                out.append(warn("aviso", "salto_raro",
                    f"Ingresos {cur['periodo']}: {ch:+.0%} frente a {prev['periodo']}. Revisa el informe.",
                    concepto="ingresos", periodo=cur["periodo"]))
    return out


def _check_jumps_yoy(flow):
    """Estacionales: un trimestre se compara con el mismo trimestre del año anterior, no con el anterior."""
    out = []
    q = {p["periodo"]: p for p in flow.get("trimestral", []) if p.get("periodo")}
    for per, cur in q.items():
        try:
            prev = q.get(f"{per[:2]}{int(per[2:]) - 1:02d}")
        except ValueError:
            continue
        if prev and prev["valor"] and prev["valor"] > 0:
            ch = cur["valor"] / prev["valor"] - 1
            if ch > YOY_UP or ch < YOY_DOWN:
                out.append(warn("aviso", "salto_raro",
                    f"Ingresos {per}: {ch:+.0%} frente a {prev['periodo']} (mismo trimestre del año anterior; "
                    f"compañía estacional). Revisa el informe.", concepto="ingresos", periodo=per))
    out.append(warn("info", "estacional",
        "Compañía estacional: los saltos de ingresos se comparan con el mismo trimestre del año anterior "
        "y el 4T derivado solo se contrasta con el 3T (ratio 0,25–4)."))
    return out


def check_fiscal_calendar(flow):
    dias = sorted({a.get("dias") for a in flow.get("anual", []) if a.get("dias")})
    if dias and any(x not in (364, 365, 366) for x in dias):
        return [warn("info", "anio_52_53_semanas",
            f"Año fiscal de 52/53 semanas (duraciones: {', '.join(map(str, dias))} días); "
            f"los trimestres se etiquetan por su fecha de cierre.")]
    return []


def check_latest_filing(ref_end, latest_periodic):
    if latest_periodic and latest_periodic.get("fecha_periodo") and ref_end:
        rep = _d(latest_periodic["fecha_periodo"])
        if rep > ref_end + timedelta(days=10):
            return [warn("aviso", "informe_sin_xbrl",
                f"El último {latest_periodic['formulario']} (periodo {rep}) todavía no aparece en "
                f"los datos XBRL de la SEC; las cifras llegan hasta {ref_end}.")]
    return []
