"""Comparativa con competidores (peers).

Lista: la que pongas en analysis/<TICKER>.json → "peers" (tu criterio) o, si está
vacía, la de Finnhub (/stock/peers, misma industria). Solo entran compañías que
presentan informes en la SEC (10-K/10-Q): las cifras salen de companyfacts con las
mismas reglas que las compañías propias. El precio, de Finnhub.
Las cifras de cada competidor se recalculan una vez por semana; el precio, cada noche.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .build import NoSecData, build_from_sec
from .filings import is_foreign_filer
from .sec_client import cik_10

MAX_PEERS = 6
REFRESH_DAYS = 7
VERSION = 3


def _v(p):
    return p.get("valor") if p else None


def summarize(rec: dict) -> dict:
    """Fundamentales UDM de un registro (propio o de competidor), en USD."""
    R = rec.get("resultados") or {}
    B = rec.get("balance") or {}
    ttm = lambda k: _v((R.get(k) or {}).get("ttm"))  # noqa: E731
    rev = ttm("ingresos")
    gross = ttm("beneficio_bruto")
    if gross is None and rev is not None and ttm("coste_ventas") is not None:
        gross = rev - ttm("coste_ventas")
    op, ni, ocf, capex, da = ttm("beneficio_operativo"), ttm("beneficio_neto"), ttm("caja_operativa"), ttm("capex"), ttm("amortizacion")
    if da is None and ttm("depreciacion") is not None:
        da = ttm("depreciacion") + (ttm("amort_intangibles") or 0)
    q = [p["valor"] for p in (R.get("ingresos") or {}).get("trimestral") or []]
    an = [p["valor"] for p in (R.get("ingresos") or {}).get("anual") or []]
    growth = None
    if len(q) >= 8 and sum(q[-8:-4]) > 0:
        growth = (sum(q[-4:]) / sum(q[-8:-4]) - 1) * 100
    elif len(an) >= 2 and an[-2] > 0:
        growth = (an[-1] / an[-2] - 1) * 100
    cash = _v((B.get("caja") or {}).get("ultimo"))
    debt = _v((B.get("deuda") or {}).get("ultimo"))
    if debt is None and (B.get("deuda") or {}).get("asumido"):
        debt = 0
    shares = _v(rec.get("acciones_en_circulacion"))
    ebitda = op + da if op is not None and da is not None else None
    fcf = ocf - capex if ocf is not None and capex is not None else None
    pct = lambda a: round(a / rev * 100, 2) if a is not None and rev else None  # noqa: E731
    ui = rec.get("ultimo_informe") or {}
    return {
        "ingresos": rev, "crecimiento": round(growth, 2) if growth is not None else None,
        "margen_bruto": pct(gross), "margen_operativo": pct(op), "margen_neto": pct(ni), "margen_fcf": pct(fcf),
        "beneficio_neto": ni, "ebitda": ebitda, "fcf": fcf, "caja": cash, "deuda": debt, "acciones": shares,
        "periodo_fin": ((R.get("ingresos") or {}).get("ttm") or {}).get("periodo_fin"),
        "informe": ui.get("formulario"), "informe_fecha": ui.get("fecha_presentacion"), "url": ui.get("url_indice"),
    }


def with_price(f: dict, price: float | None) -> dict:
    out = dict(f)
    out["precio"] = price
    sh, cash, debt = f.get("acciones"), f.get("caja") or 0, f.get("deuda") or 0
    if not price or not sh:
        return out
    mcap = price * sh
    ev = mcap + debt - cash
    div = lambda a, b: round(a / b, 2) if a is not None and b and b > 0 else None  # noqa: E731
    out.update({"capitalizacion": mcap, "ev": ev,
                "per": div(mcap, f.get("beneficio_neto")), "precio_ventas": div(mcap, f.get("ingresos")),
                "ev_ebitda": div(ev, f.get("ebitda")),
                "rentabilidad_fcf": round(f["fcf"] / mcap * 100, 2) if f.get("fcf") is not None else None,
                "deuda_neta_ebitda": round((debt - cash) / f["ebitda"], 2) if f.get("ebitda") and f["ebitda"] > 0 else None})
    return out


def peer_list(ticker, manual, provider, table_by_ticker):
    if manual:
        src, raw = "manual", manual
    else:
        getp = getattr(provider, "peers", None)
        raw = (getp(ticker) if getp else None) or []
        src = "Finnhub (misma industria)"
    out, seen = [], {ticker.upper()}
    for t in raw:
        t = str(t).upper().strip()
        if not t or t in seen:
            continue
        seen.add(t)
        if t.replace(".", "-") in table_by_ticker or t in table_by_ticker:
            out.append(t)
        if len(out) >= (12 if manual else MAX_PEERS):
            break
    return out, src


class PeerCache:
    """Fundamentales de competidores reutilizables entre compañías y noches."""

    def __init__(self, client, provider, table_by_ticker, previous_items=None, today=None, root=None):
        self.client, self.provider, self.table, self.root = client, provider, table_by_ticker, root
        self.today = today or date.today()
        self.mem = {}
        self.prev = dict(previous_items or {})
        self.prices = {}

    def price(self, t):
        if t not in self.prices:
            try:
                q = self.provider.quote(t)
                self.prices[t] = (q or {}).get("valor")
            except Exception:  # noqa: BLE001
                self.prices[t] = None
        return self.prices[t]

    def fundamentals(self, t):
        if t in self.mem:
            return self.mem[t]
        old = self.prev.get(t)
        if old and old.get("version") == VERSION and old.get("calculado") and (self.today - date.fromisoformat(old["calculado"])).days < REFRESH_DAYS:
            self.mem[t] = old
            return old
        from .add_company import clean_name
        cik, title = self.table.get(t) or self.table.get(t.replace(".", "-")) or (None, t)
        title = clean_name(title)
        item = {"ticker": t, "nombre": title, "cik": cik, "calculado": self.today.isoformat(), "soportada": True, "version": VERSION}
        if self.root is not None:   # logo y perfil (Finnhub), para la comparativa
            try:
                from . import logos
                perfil, _ = logos.update(self.provider, {"ticker": t}, self.root)
                if perfil:
                    item.update({k: perfil[k] for k in ("logo", "industria", "web", "pais") if perfil.get(k)})
            except Exception:  # noqa: BLE001
                pass
        try:
            cf = self.client.companyfacts(cik)
            subs = self.client.submissions(cik)
            if subs and is_foreign_filer(subs):
                item.update({"soportada": False, "motivo": "Emisor extranjero (20-F/IFRS): no soportado"})
            else:
                rec = build_from_sec({"ticker": t, "nombre": title, "cik": cik}, cf, subs)
                item.update(summarize(rec))
        except NoSecData:
            item.update({"soportada": False, "motivo": "Sin datos en la SEC"})
        except Exception as e:  # noqa: BLE001
            item.update({"soportada": False, "motivo": f"Error al leer la SEC: {type(e).__name__}"})
        self.mem[t] = item
        return item


def build(company, rec, manual_peers, cache: PeerCache):
    t = company["ticker"].upper()
    lista, src = peer_list(t, manual_peers, cache.provider, cache.table)
    own = with_price(summarize(rec), _v(rec.get("precio")))
    own.update({"ticker": t, "nombre": company["nombre"], "propia": True})
    items = []
    for p in lista:
        f = cache.fundamentals(p)
        items.append(with_price(f, cache.price(p)) if f.get("soportada") else dict(f))
    return {"fuente_lista": src, "fuente_cifras": "SEC EDGAR (companyfacts, UDM) · precio Finnhub",
            "actualizado": datetime.now(timezone.utc).date().isoformat(), "propia": own, "competidores": items}


def table_by_ticker(client):
    tab = client.company_tickers() or {}
    out = {}
    for v in tab.values():
        out[str(v["ticker"]).upper()] = (cik_10(v["cik_str"]), v.get("title") or v["ticker"])
    return out
