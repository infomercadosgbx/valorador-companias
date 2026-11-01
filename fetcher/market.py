"""Datos de mercado para la referencia del WACC.

Tipo sin riesgo: rentabilidad del bono del Tesoro de EE. UU. a 10 años, de la curva
diaria oficial del Departamento del Tesoro (CSV público, sin clave). La prima de
riesgo del mercado no tiene fuente oficial: se toma de manual/_mercado.json.
"""
from __future__ import annotations

import csv
import io
import time
import urllib.error
import urllib.request
from datetime import date

URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
       "daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
PAGE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"


def parse_csv(text: str):
    """Devuelve (fecha ISO, rentabilidad a 10 años en %) del día más reciente."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    best = None
    for r in rows:
        v, dt = (r.get("10 Yr") or "").strip(), (r.get("Date") or "").strip()
        if not v or not dt:
            continue
        try:
            m, d_, y = dt.split("/")
            iso = date(int(y), int(m), int(d_)).isoformat()
            val = float(v)
        except ValueError:
            continue
        if best is None or iso > best[0]:
            best = (iso, val)
    return best


def _get(url, opener=urllib.request.urlopen, sleep=time.sleep):
    for attempt in range(3):
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": "valorador"}), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError):
            sleep(2 * (attempt + 1))
    return None


def treasury_10y(today=None, opener=urllib.request.urlopen, sleep=time.sleep):
    today = today or date.today()
    for y in (today.year, today.year - 1):   # a primeros de enero puede no haber datos del año
        txt = _get(URL.format(y=y), opener, sleep)
        got = parse_csv(txt) if txt else None
        if got:
            return {"valor": got[1], "fecha": got[0], "fuente": "Departamento del Tesoro de EE. UU. · curva diaria (10 años)", "url": PAGE}
    return None
