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

    def profile(self, ticker: str) -> dict | None:
        return None

    def earnings(self, ticker: str) -> dict | None:
        return None

    def news(self, ticker: str) -> list | None:
        return None

    def peers(self, ticker: str) -> list | None:
        return None

    def earnings_on(self, ticker: str, day) -> dict | None:
        """Consenso y cifra real de una presentación concreta (para el informe de resultados)."""
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
        lo52 = hi52 = beta = None
        try:
            m = (self._get("/stock/metric", symbol=ticker, metric="all") or {}).get("metric") or {}
            lo52, hi52, beta = m.get("52WeekLow"), m.get("52WeekHigh"), m.get("beta")
        except Exception:  # noqa: BLE001  el rango es secundario
            pass
        return {
            "minimo_52s": lo52,
            "maximo_52s": hi52,
            "beta": beta,
            "valor": q["c"],
            "cierre_anterior": q.get("pc"),
            "moneda": "USD",
            "fecha": ts.date().isoformat(),
            "fuente": "Finnhub (API oficial, plan gratuito)",
            "url": f"https://finnhub.io/",
        }

    def profile(self, ticker):
        return self._get("/stock/profile2", symbol=ticker) or None

    def earnings(self, ticker, today=None):
        """Próxima fecha de resultados con previsiones y las sorpresas de los últimos trimestres."""
        from datetime import date, timedelta
        today = today or date.today()
        out = {"fuente": "Finnhub · calendario de resultados y sorpresas", "url": "https://finnhub.io/docs/api/earnings-calendar"}
        cal = (self._get("/calendar/earnings", symbol=ticker, **{"from": today.isoformat(),
               "to": (today + timedelta(days=120)).isoformat()}) or {}).get("earningsCalendar") or []
        cal = sorted([c for c in cal if c.get("date")], key=lambda c: c["date"])
        if cal:
            c = cal[0]
            out["proximos"] = {"fecha": c.get("date"), "hora": {"bmo": "antes de la apertura", "amc": "tras el cierre",
                               "dmh": "durante la sesión"}.get(c.get("hour"), c.get("hour") or None),
                               "hora_codigo": c.get("hour") or None,
                               "trimestre": c.get("quarter"), "anio": c.get("year"),
                               "bpa_estimado": c.get("epsEstimate"), "ingresos_estimados": c.get("revenueEstimate")}
        rows = self._get("/stock/earnings", symbol=ticker) or []
        out["sorpresas"] = [{"periodo": r.get("period"), "trimestre": r.get("quarter"), "anio": r.get("year"),
                             "bpa_real": r.get("actual"), "bpa_estimado": r.get("estimate"),
                             "sorpresa_pct": r.get("surprisePercent")}
                            for r in sorted(rows, key=lambda r: r.get("period") or "")][-8:]
        return out if (out.get("proximos") or out["sorpresas"]) else None

    def earnings_on(self, ticker, day):
        """Calendario de resultados alrededor de «day» (date): BPA e ingresos esperados y reales.
        El plan gratuito cubre el último mes; fuera de ese plazo devuelve None."""
        from datetime import timedelta
        cal = (self._get("/calendar/earnings", symbol=ticker, **{"from": (day - timedelta(days=4)).isoformat(),
               "to": (day + timedelta(days=4)).isoformat()}) or {}).get("earningsCalendar") or []
        cal = [c for c in cal if c.get("date")]
        if not cal:
            return None
        c = min(cal, key=lambda c: abs((datetime.fromisoformat(c["date"]).date() - day).days))
        return {"fecha": c.get("date"), "hora": c.get("hour"), "trimestre": c.get("quarter"), "anio": c.get("year"),
                "bpa_estimado": c.get("epsEstimate"), "ingresos_estimados": c.get("revenueEstimate"),
                "bpa_real": c.get("epsActual"), "ingresos_reales": c.get("revenueActual")}

    def peers(self, ticker):
        rows = self._get("/stock/peers", symbol=ticker) or []
        return [r for r in rows if isinstance(r, str)]

    def news(self, ticker, today=None, days=21, limit=20):
        from datetime import date, timedelta
        today = today or date.today()
        rows = self._get("/company-news", symbol=ticker, **{"from": (today - timedelta(days=days)).isoformat(),
                         "to": today.isoformat()}) or []
        seen, out = set(), []
        for r in sorted(rows, key=lambda r: -(r.get("datetime") or 0)):
            h = (r.get("headline") or "").strip()
            if not h or h.lower() in seen or not r.get("url"):
                continue
            seen.add(h.lower())
            out.append({"titular": h, "medio": r.get("source"), "url": r.get("url"),
                        "fecha": datetime.fromtimestamp(r["datetime"], tz=timezone.utc).date().isoformat() if r.get("datetime") else None,
                        "resumen": (r.get("summary") or "")[:280]})
            if len(out) >= limit:
                break
        return out

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
            "historial": [{"periodo": r.get("period"), "compra_fuerte": r.get("strongBuy", 0), "compra": r.get("buy", 0),
                           "mantener": r.get("hold", 0), "venta": r.get("sell", 0), "venta_fuerte": r.get("strongSell", 0)}
                          for r in sorted(rows, key=lambda r: r.get("period", ""))[-6:]],
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

    def history(self, ticker: str, days=1320):
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


class AlpacaExtendedHours:
    """Cotización fuera de horario (after-hours y premercado) para la reacción a resultados.

    API oficial de Alpaca Markets, plan gratuito «Basic»: barras históricas del SIP (todas las
    bolsas de EE. UU., sesiones de 4:00 a 20:00 ET) con al menos 15 minutos de retraso.
    Claves en los secrets ALPACA_API_KEY_ID y ALPACA_API_SECRET_KEY (cuenta gratuita, sin
    depósito). Es secundario: si falla, la reacción queda «pendiente» hasta el cierre."""
    nombre = "Alpaca"
    BASE = "https://data.alpaca.markets/v2/stocks/bars"
    RETRASO_MIN = 16

    def __init__(self, key_id: str, secret: str, opener=None, sleep=time.sleep):
        self.key_id, self.secret = key_id, secret
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def _bars(self, ticker, start, end):
        params = {"symbols": ticker, "timeframe": "5Min", "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "feed": "sip", "adjustment": "raw", "limit": 10000, "sort": "asc"}
        url = f"{self.BASE}?{urllib.parse.urlencode(params)}"
        hdr = {"APCA-API-KEY-ID": self.key_id, "APCA-API-SECRET-KEY": self.secret, "Accept": "application/json",
               "User-Agent": "valorador"}
        for attempt in range(3):
            try:
                with self._open(urllib.request.Request(url, headers=hdr), timeout=30) as r:
                    j = json.loads(r.read())
                return (j.get("bars") or {}).get(ticker) or []
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise RuntimeError("Alpaca rechaza las claves (revisa ALPACA_API_KEY_ID y ALPACA_API_SECRET_KEY)") from e
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except (urllib.error.URLError, TimeoutError):
                pass
            self._sleep(3 * (attempt + 1))
        raise RuntimeError("Alpaca no responde")

    @staticmethod
    def sesion(ts_utc):
        """«after-hours», «premercado» o «sesión» según la hora de Nueva York."""
        from zoneinfo import ZoneInfo
        ny = ts_utc.astimezone(ZoneInfo("America/New_York"))
        m = ny.hour * 60 + ny.minute
        if m < 9 * 60 + 30:
            return "premercado", ny
        if m >= 16 * 60:
            return "after-hours", ny
        return "sesión", ny

    def extended(self, ticker, day, amc=True, now=None):
        """Última cotización desde el cierre previo a los resultados (día «day», date) hasta ahora − 16 min.
        Devuelve {ultimo: {...}, after_hours: {...}} o None si no hay operaciones."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        now = now or datetime.now(timezone.utc)
        ref = day if amc else day - timedelta(days=1)
        while not amc and ref.weekday() >= 5:
            ref -= timedelta(days=1)
        start = datetime(ref.year, ref.month, ref.day, 16, 0, tzinfo=ny).astimezone(timezone.utc)
        end = now - timedelta(minutes=self.RETRASO_MIN)
        if end <= start:
            return None
        bars = [b for b in self._bars(ticker, start, end) if b.get("c") and b.get("t")]
        if not bars:
            return None

        def pt(b):
            ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
            ses, loc = self.sesion(ts)
            return {"precio": round(float(b["c"]), 4), "hora_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "hora_ny": loc.strftime("%Y-%m-%d %H:%M"), "sesion": ses}
        out = {"ultimo": pt(bars[-1]), "fuente": "Alpaca Markets (API oficial, plan gratuito) · SIP con 15 min de retraso",
               "url": "https://docs.alpaca.markets/docs/historical-stock-data-1",
               "volumen": int(sum(b.get("v") or 0 for b in bars))}
        ah = [b for b in bars if self.sesion(datetime.fromisoformat(b["t"].replace("Z", "+00:00")))[1].date() == ref
              and self.sesion(datetime.fromisoformat(b["t"].replace("Z", "+00:00")))[0] == "after-hours"]
        if ah:
            out["after_hours"] = pt(ah[-1])
        return out


def extended_from_env():
    kid, sec = os.environ.get("ALPACA_API_KEY_ID", "").strip(), os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
    if kid and sec:
        return AlpacaExtendedHours(kid, sec)
    return None


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
