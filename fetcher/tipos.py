"""«Tipos de interés»: la Reserva Federal para el menú principal.

Se guarda dentro de data/_mercado_hoy.json (clave «tipos»). Fuentes oficiales:
- FRED: rango objetivo de los fondos federales (DFEDTARL/DFEDTARU), tipo efectivo (EFFR) y
  mediana del diagrama de puntos de la Fed (FEDTARMD y FEDTARMDLR).
- Tesoro de EE. UU.: letras y bonos a 3 y 6 meses, 1, 2 y 10 años, para lo que descuenta el mercado
  y la pendiente de la curva.
- Calendario de reuniones del FOMC publicado por la Fed (lista de abajo; la Fed lo publica con
  más de un año de antelación).
Las probabilidades de CME FedWatch no tienen fuente gratuita: se apuntan a mano en manual/_mercado.json.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

FED_CAL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_COMUNICADO = "https://www.federalreserve.gov/newsevents/pressreleases/monetary{d}a.htm"
FED_RUEDA = "https://www.federalreserve.gov/monetarypolicy/fomcpresconf{d}.htm"
FED_ACTAS = "https://www.federalreserve.gov/monetarypolicy/fomcminutes{d}.htm"
FED_SEP = "https://www.federalreserve.gov/monetarypolicy/fomcprojtabl{d}.htm"
FRED_PAGE = "https://fred.stlouisfed.org/series/{}"
TESORO_PAGE = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               "TextView?type=daily_treasury_yield_curve")

# Calendario oficial del FOMC (inicio, fin, con proyecciones económicas y diagrama de puntos)
FOMC = [
    ("2026-01-27", "2026-01-28", False), ("2026-03-17", "2026-03-18", True),
    ("2026-04-28", "2026-04-29", False), ("2026-06-16", "2026-06-17", True),
    ("2026-07-28", "2026-07-29", False), ("2026-09-15", "2026-09-16", True),
    ("2026-10-27", "2026-10-28", False), ("2026-12-08", "2026-12-09", True),
    ("2027-01-26", "2027-01-27", False), ("2027-03-16", "2027-03-17", True),
    ("2027-04-27", "2027-04-28", False), ("2027-06-08", "2027-06-09", True),
    ("2027-07-27", "2027-07-28", False), ("2027-09-14", "2027-09-15", True),
    ("2027-10-26", "2027-10-27", False), ("2027-12-07", "2027-12-08", True),
    ("2028-01-25", "2028-01-26", False),
]

# Plazos del Tesoro para lo que descuenta el mercado
PLAZOS = [("3 Mo", "3 meses"), ("6 Mo", "6 meses"), ("1 Yr", "1 año"), ("2 Yr", "2 años")]
UMBRAL_PB = 15     # diferencias menores se leen como «sin cambios»


def hora_decision(fin: str) -> str:
    """El comunicado sale a las 14:00 de Nueva York; se devuelve la hora de Madrid (cambia con los horarios de verano)."""
    d = date.fromisoformat(fin)
    ny = datetime.combine(d, dtime(14, 0), tzinfo=ZoneInfo("America/New_York"))
    return ny.astimezone(ZoneInfo("Europe/Madrid")).strftime("%H:%M")


def _reunion(r, hoy):
    ini, fin, sep = r
    d = fin.replace("-", "")
    o = {"inicio": ini, "fin": fin, "proyecciones": sep, "hora_madrid": hora_decision(fin),
         "dias": (date.fromisoformat(fin) - hoy).days, "comunicado": FED_COMUNICADO.format(d=d),
         "rueda_prensa": FED_RUEDA.format(d=d)}
    actas = date.fromisoformat(fin) + timedelta(days=21)
    o["actas_fecha"] = actas.isoformat()
    if hoy >= actas:
        o["actas"] = FED_ACTAS.format(d=d)
    if sep:
        o["diagrama"] = FED_SEP.format(d=d)
    return o


def calendario(hoy: date):
    pasadas = [r for r in FOMC if date.fromisoformat(r[1]) < hoy]
    futuras = [r for r in FOMC if date.fromisoformat(r[1]) >= hoy]
    out = {"url": FED_CAL, "proximas": [_reunion(r, hoy) for r in futuras[:4]]}
    if pasadas:
        out["ultima"] = _reunion(pasadas[-1], hoy)
    sep = [r for r in pasadas if r[2]]
    if sep:
        out["ultima_proyeccion"] = sep[-1][1]
    return out


def _en(serie, d):
    """Último valor de la serie en o antes de la fecha d (serie ordenada de (fecha, valor))."""
    v = None
    for f, x in serie:
        if f > d:
            break
        v = x
    return v


def decision(rango_sup, reunion):
    """Qué decidió la Fed en una reunión: cambio del techo del rango entre la víspera y dos días después."""
    if not reunion or not rango_sup:
        return None
    antes = _en(rango_sup, (date.fromisoformat(reunion["inicio"]) - timedelta(days=1)).isoformat())
    despues = _en(rango_sup, (date.fromisoformat(reunion["fin"]) + timedelta(days=2)).isoformat())
    if antes is None or despues is None or rango_sup[-1][0] < reunion["fin"]:
        return None
    pb = round((despues - antes) * 100)
    return {"pb": pb, "texto": "Mantuvo los tipos" if pb == 0 else f"{'Subió' if pb > 0 else 'Bajó'} {abs(pb)} pb"}


def ultimo_cambio(rango_sup):
    for i in range(len(rango_sup) - 1, 0, -1):
        if rango_sup[i][1] != rango_sup[i - 1][1]:
            return {"fecha": rango_sup[i][0], "pb": round((rango_sup[i][1] - rango_sup[i - 1][1]) * 100)}
    return None


def lectura(pb):
    if pb is None:
        return None
    if pb <= -UMBRAL_PB:
        return "bajadas"
    if pb >= UMBRAL_PB:
        return "subidas"
    return "sin cambios"


def build(f, fred, avisos, old=None):
    """f: Fuentes (para el Tesoro); fred: función serie -> [(fecha, valor)] con caché y errores."""
    old = old or {}
    hoy = f.hoy
    out = {"calendario": calendario(hoy)}
    if len(out["calendario"]["proximas"]) < 2:
        avisos.append("Tipos: el calendario del FOMC se acaba; añade las reuniones nuevas en fetcher/tipos.py (FOMC).")

    # rango objetivo y tipo efectivo
    try:
        lo, hi = fred("DFEDTARL"), fred("DFEDTARU")
        fed = {"inferior": lo[-1][1], "superior": hi[-1][1], "fecha": hi[-1][0],
               "fuente": "Reserva Federal vía FRED", "url": FRED_PAGE.format("DFEDTARU")}
        try:
            ef = fred("EFFR")
            fed["efectivo"] = {"valor": ef[-1][1], "fecha": ef[-1][0], "url": FRED_PAGE.format("EFFR")}
        except RuntimeError as e:
            avisos.append(f"Tipo efectivo de los fondos federales: no disponible ({e}).")
        fed["ultimo_cambio"] = ultimo_cambio(hi)
        cal = out["calendario"]
        if cal.get("ultima"):
            cal["ultima"]["decision"] = decision(hi, cal["ultima"])
        out["fed"] = fed
    except RuntimeError as e:
        avisos.append(f"Tipos de la Fed: no disponibles ({e}).")
        if old.get("fed"):
            out["fed"] = dict(old["fed"], desactualizado=True)

    # diagrama de puntos (mediana)
    try:
        md = [(d, v) for d, v in fred("FEDTARMD") if int(d[:4]) >= hoy.year]
        if md:
            p = {"anios": [{"anio": int(d[:4]), "mediana": v} for d, v in md],
                 "fuente": "Reserva Federal (proyecciones del FOMC) vía FRED", "url": FRED_PAGE.format("FEDTARMD"),
                 "reunion": out["calendario"].get("ultima_proyeccion")}
            try:
                lr = fred("FEDTARMDLR")
                if lr:
                    p["largo_plazo"] = lr[-1][1]
            except RuntimeError:
                pass
            out["diagrama"] = p
    except RuntimeError as e:
        avisos.append(f"Diagrama de puntos de la Fed: no disponible ({e}).")
        if old.get("diagrama"):
            out["diagrama"] = old["diagrama"]

    # lo que descuenta el mercado y pendiente de la curva (Tesoro)
    try:
        base = (out.get("fed") or {}).get("efectivo", {}).get("valor")
        if base is None and out.get("fed"):
            base = (out["fed"]["inferior"] + out["fed"]["superior"]) / 2
        curva = {}
        for col, _ in PLAZOS + [("10 Yr", "10 años")]:
            s = f.tesoro(col)
            if s:
                curva[col] = s
        plazos = []
        for col, nom in PLAZOS:
            if col in curva:
                v = curva[col][-1][1]
                pb = round((v - base) * 100) if base is not None else None
                plazos.append({"plazo": nom, "valor": v, "fecha": curva[col][-1][0], "dif_pb": pb, "lectura": lectura(pb)})
        if plazos:
            out["mercado"] = {"plazos": plazos, "base": base, "fuente": "Tesoro de EE. UU.", "url": TESORO_PAGE}

        def pend(a, b):
            if a in curva and b in curva:
                d = curva[a][-1][0]
                ahora = round((curva[a][-1][1] - curva[b][-1][1]) * 100)
                ref = (date.fromisoformat(d) - timedelta(days=30)).isoformat()
                va, vb = _en(curva[a], ref), _en(curva[b], ref)
                return {"pb": ahora, "hace_1m": round((va - vb) * 100) if va is not None and vb is not None else None, "fecha": d}
            return None
        pc = {k: v for k, v in (("10a_2a", pend("10 Yr", "2 Yr")), ("10a_3m", pend("10 Yr", "3 Mo"))) if v}
        if pc:
            out["pendiente"] = dict(pc, fuente="Tesoro de EE. UU.", url=TESORO_PAGE)
    except RuntimeError as e:
        avisos.append(f"Curva del Tesoro: no disponible ({e}).")
        for k in ("mercado", "pendiente"):
            if old.get(k):
                out[k] = old[k]
    return out
