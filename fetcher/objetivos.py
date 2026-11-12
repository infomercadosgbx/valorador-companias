"""Precio objetivo medio de los analistas, automático cada noche.

Fuente: Alpha Vantage, función OVERVIEW (ficha de la empresa), campo AnalystTargetPrice.
Plan gratuito: 25 consultas al día y 5 por minuto; se hace una consulta por compañía.
Solo da la media: el rango (mínimo y máximo) sigue en manual/<T>.json.

Se guarda en data/<T>.json → objetivo_analistas:
  {valor, fecha, fuente, url, analistas, historial: [[fecha, valor], ...]}
El historial guarda un punto cada vez que la media cambia, para compararla en la web con tu valor.
Si la consulta falla (cuota, plan de pago, sin dato), se conserva el último dato y se avisa.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from datetime import date

from .news import _http_get

MAX_HIST = 400


class AlphaVantageTargets:
    nombre = "Alpha Vantage"
    URL = "https://www.alphavantage.co/query"
    DOC = "https://www.alphavantage.co/documentation/#company-overview"

    def __init__(self, key, opener=None, min_intervalo=13.0, sleep=time.sleep):
        self.key, self._open, self.min_intervalo, self._sleep, self._ultima = key, opener, min_intervalo, sleep, None

    def target(self, ticker):
        if self._ultima is not None:
            espera = self.min_intervalo - (time.monotonic() - self._ultima)
            if espera > 0:
                self._sleep(espera)
        self._ultima = time.monotonic()
        q = {"function": "OVERVIEW", "symbol": ticker, "apikey": self.key}
        j = json.loads(_http_get(f"{self.URL}?{urllib.parse.urlencode(q)}", opener=self._open))
        if not isinstance(j, dict) or "Symbol" not in j:
            msg = (j or {}).get("Information") or (j or {}).get("Note") or (j or {}).get("Error Message") or "respuesta sin datos"
            raise RuntimeError(str(msg)[:200])
        try:
            v = float(j.get("AnalystTargetPrice"))
        except (TypeError, ValueError):
            return None
        if not v > 0:
            return None
        n = 0
        for k in ("AnalystRatingStrongBuy", "AnalystRatingBuy", "AnalystRatingHold", "AnalystRatingSell", "AnalystRatingStrongSell"):
            try:
                n += int(j.get(k) or 0)
            except (TypeError, ValueError):
                pass
        return {"valor": round(v, 2), "analistas": n or None}


def from_env():
    k = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    return AlphaVantageTargets(k) if k else None


# Lo prepara main.run en la ejecución real; en los tests queda en None
PROVIDER = None


def actualizar(rec, ticker, previous, provider=None, today=None, warn=None):
    """Rellena rec["objetivo_analistas"]. Nunca lanza: si falla, conserva el anterior."""
    provider = provider if provider is not None else PROVIDER
    prev = (previous or {}).get("objetivo_analistas")
    if provider is None:
        if prev:
            rec["objetivo_analistas"] = prev
        return
    hoy = (today or date.today()).isoformat()
    if prev and prev.get("fecha") == hoy:   # una consulta al día por compañía basta (cuota gratuita: 25/día)
        rec["objetivo_analistas"] = prev
        return
    try:
        t = provider.target(ticker)
    except Exception as e:  # noqa: BLE001  dato secundario
        if prev:
            rec["objetivo_analistas"] = prev
        if warn:
            rec.setdefault("avisos", []).append(warn("info", "sin_objetivo_analistas",
                f"Precio objetivo de analistas no disponible ({provider.nombre}): {e}. Se mantiene el último dato."))
        return
    if not t:
        if prev:
            rec["objetivo_analistas"] = prev
        return
    hist = list((prev or {}).get("historial") or [])
    if not hist or abs(hist[-1][1] - t["valor"]) > 0.005:
        hist.append([hoy, t["valor"]])
    rec["objetivo_analistas"] = {
        "valor": t["valor"], "fecha": hoy, "analistas": t.get("analistas"),
        "fuente": f"{provider.nombre} · precio objetivo medio de los analistas", "url": provider.DOC,
        "historial": hist[-MAX_HIST:],
    }
