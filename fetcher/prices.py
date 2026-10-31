"""Proveedores de precio y consenso con API oficial.

Por defecto: Finnhub (plan gratuito, 60 llamadas/minuto).
- Precio: /quote (último cierre o precio actual).
- Consenso: /stock/recommendation (recuento de recomendaciones por mes, gratuito).
  Los precios objetivo de analistas son de pago en Finnhub, así que se dejan
  en /manual/<ticker>.json y la web los marca como «manual».

La clave se lee de la variable de entorno FINNHUB_API_KEY (GitHub Secret).
Para cambiar de proveedor, implementa PriceProvider y regístralo en PROVIDERS.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class PriceProvider:
    nombre = "ninguno"

    def quote(self, ticker: str) -> dict | None:
        return None

    def recommendations(self, ticker: str) -> dict | None:
        return None


class NoPriceProvider(PriceProvider):
    pass


class FinnhubProvider(PriceProvider):
    nombre = "Finnhub"
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, min_interval=1.1, opener=None, sleep=time.sleep):
        self.key = api_key
        self.min_interval = min_interval
        self._last = 0.0
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def _get(self, path, **params):
        params["token"] = self.key
        url = f"{self.BASE}{path}?{urllib.parse.urlencode(params)}"
        for attempt in range(4):
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                with self._open(urllib.request.Request(url, headers={"User-Agent": "valorador"}), timeout=30) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise RuntimeError("Finnhub rechaza la clave (revisa el secret FINNHUB_API_KEY)") from e
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, TimeoutError):
                pass
            self._sleep(2 * (2 ** attempt))
        raise RuntimeError(f"Finnhub no responde: {path}")

    def quote(self, ticker):
        q = self._get("/quote", symbol=ticker)
        if not q or not q.get("c") or not q.get("t"):
            return None
        ts = datetime.fromtimestamp(q["t"], tz=timezone.utc)
        lo52 = hi52 = None
        try:
            m = (self._get("/stock/metric", symbol=ticker, metric="price") or {}).get("metric") or {}
            lo52, hi52 = m.get("52WeekLow"), m.get("52WeekHigh")
        except Exception:  # noqa: BLE001  el rango es secundario
            pass
        return {
            "minimo_52s": lo52,
            "maximo_52s": hi52,
            "valor": q["c"],
            "cierre_anterior": q.get("pc"),
            "moneda": "USD",
            "fecha": ts.date().isoformat(),
            "fuente": "Finnhub (API oficial, plan gratuito)",
            "url": f"https://finnhub.io/",
        }

    def recommendations(self, ticker):
        rows = self._get("/stock/recommendation", symbol=ticker)
        if not rows:
            return None
        last = max(rows, key=lambda r: r.get("period", ""))
        return {
            "periodo": last.get("period"),
            "compra_fuerte": last.get("strongBuy", 0),
            "compra": last.get("buy", 0),
            "mantener": last.get("hold", 0),
            "venta": last.get("sell", 0),
            "venta_fuerte": last.get("strongSell", 0),
            "fuente": "Finnhub · recomendaciones de analistas",
            "url": "https://finnhub.io/docs/api/recommendation-trends",
        }


class TwelveDataHistory:
    """Histórico de cierres diarios (API oficial de Twelve Data, plan gratuito:
    800 consultas al día y 8 por minuto). Ajustado por splits."""
    nombre = "Twelve Data"
    BASE = "https://api.twelvedata.com/time_series"

    def __init__(self, api_key: str, min_interval=8.0, opener=None, sleep=time.sleep):
        self.key = api_key
        self.min_interval = min_interval
        self._last = 0.0
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def history(self, ticker: str, days=1300):
        params = {"symbol": ticker, "interval": "1day", "outputsize": days, "adjust": "splits",
                  "order": "ASC", "apikey": self.key}
        url = f"{self.BASE}?{urllib.parse.urlencode(params)}"
        for attempt in range(4):
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                with self._open(urllib.request.Request(url, headers={"User-Agent": "valorador"}), timeout=60) as r:
                    j = json.loads(r.read())
            except (urllib.error.URLError, TimeoutError):
                self._sleep(5 * (attempt + 1))
                continue
            if j.get("status") == "error":
                if j.get("code") == 429:
                    self._sleep(61)
                    continue
                raise RuntimeError(f"Twelve Data: {j.get('message')}")
            vals = j.get("values") or []
            serie = [[v["datetime"][:10], round(float(v["close"]), 4)] for v in vals if v.get("close")]
            serie.sort()
            if not serie:
                return None
            return {"serie": serie, "fuente": "Twelve Data (API oficial, plan gratuito)",
                    "url": "https://twelvedata.com/", "fecha": serie[-1][0], "ajuste": "splits"}
        raise RuntimeError("Twelve Data no responde")


def history_from_env():
    key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    if key:
        return TwelveDataHistory(key), None
    return None, "Sin histórico de cotizaciones: falta el secret TWELVEDATA_API_KEY (ver README)."


PROVIDERS = {"finnhub": FinnhubProvider}


def from_env() -> tuple[PriceProvider, str | None]:
    """Devuelve (proveedor, aviso). Sin clave: sin precio, con aviso visible."""
    name = os.environ.get("PRICE_PROVIDER", "finnhub").lower()
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if name == "finnhub" and key:
        return FinnhubProvider(key), None
    return NoPriceProvider(), "Sin precio de mercado: falta el secret FINNHUB_API_KEY (ver README, paso 3)."
