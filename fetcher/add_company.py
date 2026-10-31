"""Alta de una compañía nueva (workflow «Añadir compañía»).

  python -m fetcher.add_company TICKER [--nombre "Nombre"] [--color "#RRGGBB"]

1. Resuelve el CIK con https://www.sec.gov/files/company_tickers.json.
2. Comprueba que presenta 10-K/10-Q (las extranjeras con 20-F/IFRS no están soportadas).
3. La añade a companies.json con nombre, color (del logo si no se indica) y monograma.
4. Descarga sus datos (SEC, precio, histórico) y crea analysis/ y manual/.
5. Rellena el punto de partida del DCF con las cifras reales de la SEC, para que la
   valoración funcione desde el primer día (supuestos marcados como automáticos).
Sale con código 0 si todo va bien, 3 si la compañía no se puede añadir.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from . import colors, main as M
from .filings import is_foreign_filer, recent_rows
from .sec_client import SecClient, SecError, cik_10

ROOT = M.ROOT
SUFFIX = re.compile(r"[,\s]+(inc\.?|incorporated|corp\.?|corporation|co\.|ltd\.?|limited|plc|n\.v\.|s\.a\.|l\.p\.|ag|se)$", re.I)


class NoSoportada(Exception):
    pass


def summary(msg: str):
    print(msg)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def clean_name(title: str) -> str:
    name = title.strip()
    name = SUFFIX.sub("", name).strip(" ,")
    if name.isupper() and len(name) > 4:
        name = name.title()
    return name or title


def monogram(name: str) -> str:
    words = [w for w in re.split(r"[\s\-&]+", name) if w and w[0].isalnum()]
    return (words[0][0] + words[1][0]).upper() if len(words) > 1 else name[:2].upper()


INDUSTRIAS = {"Technology": "Tecnología", "Media": "Medios e internet", "Retail": "Comercio minorista", "Utilities": "Eléctricas y servicios públicos",
    "Semiconductors": "Semiconductores", "Banking": "Banca", "Pharmaceuticals": "Farmacéuticas", "Biotechnology": "Biotecnología",
    "Insurance": "Seguros", "Real Estate": "Inmobiliario", "Energy": "Energía", "Oil & Gas": "Petróleo y gas", "Financial Services": "Servicios financieros",
    "Health Care": "Salud", "Life Sciences Tools & Services": "Equipos y servicios para ciencias de la vida", "Software": "Software",
    "Communications": "Comunicaciones", "Telecommunication": "Telecomunicaciones", "Automobiles": "Automoción", "Aerospace & Defense": "Aeroespacial y defensa",
    "Machinery": "Maquinaria", "Chemicals": "Química", "Beverages": "Bebidas", "Food Products": "Alimentación", "Hotels, Restaurants & Leisure": "Hoteles, restauración y ocio",
    "Road & Rail": "Transporte terrestre", "Airlines": "Aerolíneas", "Logistics & Transportation": "Logística y transporte", "Textiles, Apparel & Luxury Goods": "Moda y lujo",
    "Commercial Services & Supplies": "Servicios a empresas", "Professional Services": "Servicios profesionales", "Electrical Equipment": "Equipos eléctricos",
    "Building": "Construcción", "Construction": "Construcción", "Metals & Mining": "Metales y minería", "Consumer products": "Productos de consumo", "Tobacco": "Tabaco",
    "Trading Companies & Distributors": "Distribución", "Diversified Consumer Services": "Servicios al consumidor", "Industrial Conglomerates": "Conglomerados industriales"}


def dump_companies(cj) -> str:
    """Mantiene companies.json con una compañía por línea, como lo escribe una persona."""
    rows = ",\n".join("    " + json.dumps(c, ensure_ascii=False) for c in cj["companies"])
    return (json.dumps({"_nota": cj.get("_nota", "")}, ensure_ascii=False, indent=2)[:-2]
            + ',\n  "companies": [\n' + rows + "\n  ]\n}\n")


def resolve(client, ticker: str):
    table = client.company_tickers() or {}
    want = {ticker.upper(), ticker.upper().replace(".", "-"), ticker.upper().replace("-", ".")}
    for v in table.values():
        if str(v.get("ticker", "")).upper() in want:
            return str(v["ticker"]).upper(), cik_10(v["cik_str"]), v.get("title") or ""
    raise NoSoportada(f"El ticker {ticker} no aparece en la lista oficial de la SEC (company_tickers.json). "
                      f"Solo se pueden añadir compañías que presentan informes en EE. UU.")


def check_filer(subs, ticker):
    if not subs:
        raise NoSoportada(f"La SEC no devuelve datos de {ticker}.")
    if is_foreign_filer(subs):
        raise NoSoportada(f"{ticker} presenta 20-F/40-F (emisor extranjero, normalmente IFRS). "
                          f"Todavía no está soportado: no se añade para no mostrar datos incompletos.")
    if not any(r["form"] in ("10-K", "10-Q") for r in recent_rows(subs)):
        raise NoSoportada(f"{ticker} no tiene informes 10-K ni 10-Q en la SEC.")


def _r(x, d=1):
    return None if x is None else round(x, d)


def seed_dcf(data: dict, tpl_v: dict):
    """Punto de partida del DCF con cifras reales (UDM). Lo que falte queda con la plantilla."""
    R = data.get("resultados") or {}
    ttm = lambda k: ((R.get(k) or {}).get("ttm") or {}).get("valor")  # noqa: E731
    anual = lambda k: [p["valor"] for p in (R.get(k) or {}).get("anual") or []]  # noqa: E731
    v = dict(tpl_v)
    for k in ("shares", "cash", "debt"):
        v.pop(k, None)                                   # acciones, caja y deuda siguen a la SEC
    rev = ttm("ingresos")
    if not rev or rev <= 0:
        return v, []
    hechos = []
    end = ((R.get("ingresos") or {}).get("ttm") or {}).get("periodo_fin") or date.today().isoformat()
    v["rev0"] = round(rev / 1e6)
    v["year0"] = int(end[:4])
    a = anual("ingresos")
    if len(a) >= 4 and a[-4] > 0 and a[-1] > 0:
        cagr = ((a[-1] / a[-4]) ** (1 / 3) - 1) * 100
        g1 = max(-5.0, min(40.0, cagr))
        g5 = max(3.0, min(g1, g1 / 2 if g1 > 6 else g1))
        v["g"] = [_r(g1 + (g5 - g1) * i / 4, 1) for i in range(5)]
        hechos.append(f"crecimiento: CAGR de ingresos de 3 años ({cagr:.1f}%) que se modera hasta {g5:.1f}%")
    op, da = ttm("beneficio_operativo"), ttm("amortizacion")
    if op is not None:
        e = (op + (da or 0)) / rev * 100
        v["m1"] = v["m5"] = _r(e)
        hechos.append(f"margen EBITDA real de los últimos 12 meses ({e:.1f}%)")
    if da:
        v["da"] = v["da5"] = _r(da / rev * 100)
    sbc = ttm("remuneracion_acciones")
    if sbc:
        v["sbc"] = _r(sbc / rev * 100)
    cx = ttm("capex")
    if cx is not None:
        v["capex"] = v["capex5"] = _r(cx / rev * 100)
        ca, ra = anual("capex"), anual("ingresos")
        hist = [c / r * 100 for c, r in zip(ca[-3:], ra[-3:]) if r] if len(ca) >= 3 and len(ra) >= 3 else []
        if hist and sum(hist) / len(hist) < v["capex"]:
            v["capex5"] = _r(sum(hist) / len(hist))           # un pico de inversión no se proyecta para siempre
            hechos.append(f"capex del {v['capex']}% que vuelve a su media de 3 años ({v['capex5']}%)")
    tx, pbt = ttm("impuestos"), ttm("beneficio_antes_impuestos")
    if tx is not None and pbt and pbt > 0:
        v["tax"] = _r(min(25.0, max(15.0, tx / pbt * 100)))
    ni = ttm("beneficio_neto")
    sh = (data.get("acciones_en_circulacion") or {}).get("valor")
    if ni and sh:
        v["eps"] = round(ni / sh, 2)
    v.update({"wacc": 9, "tg": 3, "exit": 12, "pe": 20, "evm": 12, "nwc": 5})
    return v, hechos


def add(ticker: str, nombre=None, color=None, root=ROOT, client=None):
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,9}", ticker):
        raise NoSoportada(f"Ticker no válido: «{ticker}».")
    client = client or SecClient()
    cfile = root / "companies.json"
    cj = json.loads(cfile.read_text(encoding="utf-8"))
    sec_ticker, cik, title = resolve(client, ticker)
    exists = next((c for c in cj["companies"] if c["ticker"].upper() in (ticker, sec_ticker) or c["cik"] == cik), None)
    if exists:
        summary(f"ℹ️ **{exists['nombre']} ({exists['ticker']})** ya estaba en la lista. Se actualizan sus datos.")
        M.run(only=[exists["ticker"]], root=root, client=client)
        return exists, False
    subs = client.submissions(cik)
    check_filer(subs, ticker)
    name = nombre or clean_name(title or subs.get("name", ticker))
    comp = {"ticker": ticker, "slug": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), "nombre": name, "cik": cik,
            "color": color or None, "monograma": monogram(name)}
    cj["companies"].append(comp)
    cfile.write_text(dump_companies(cj), encoding="utf-8")

    failures = M.run(only=[ticker], root=root, client=client)
    if failures:
        raise SecError(f"No se pudieron descargar los datos de {ticker}: {failures[0][1][:300]}")
    data = json.loads((root / "data" / f"{ticker}.json").read_text(encoding="utf-8"))

    # color del logo si no se indicó
    if not color:
        logo = (data.get("perfil") or {}).get("logo")
        dom = colors.dominant((root / logo).read_bytes()) if logo and logo.endswith(".png") and (root / logo).exists() else None
        comp["color"] = dom or colors.fallback(ticker)
        cfile.write_text(dump_companies(cj), encoding="utf-8")

    # análisis inicial: datos de la ficha y punto de partida del DCF
    apath = root / "analysis" / f"{ticker}.json"
    an = json.loads(apath.read_text(encoding="utf-8"))
    perfil = data.get("perfil") or {}
    addr = ((subs.get("addresses") or {}).get("business") or {})
    meta = an.setdefault("meta", {})
    ind = perfil.get("industria")
    meta["sector"] = meta.get("sector") or INDUSTRIAS.get(ind, ind) or subs.get("sicDescription") or ""
    if not meta.get("hq") and addr.get("city"):
        meta["hq"] = f"{str(addr['city']).title()}, {addr.get('stateOrCountryDescription') or addr.get('stateOrCountry') or ''}".strip(", ")
    meta["autogenerado"] = date.today().isoformat()
    src = an.setdefault("sources", {})
    if perfil.get("web") and not src.get("web"):
        src["web"] = perfil["web"]
    ver = an.setdefault("verdict", {})
    ver.update({"rating": "", "conviction": None})          # sin recomendación hasta que la escribas
    v, hechos = seed_dcf(data, an.get("v") or {})
    an["v"] = v
    an["_nota"] = ("Supuestos y textos propios. Creado automáticamente en el alta: el punto de partida del DCF sale de "
                   "las cifras reales de la SEC; revísalo y completa tesis, negocio, MOAT, directiva y riesgos.")
    apath.write_text(json.dumps(an, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    avisos = [w for w in data.get("avisos", []) if w["nivel"] != "info"]
    summary(f"✅ **{name} ({ticker})** añadida · CIK {cik} · color {comp['color']}\n\n"
            f"- Datos de la SEC hasta {data.get('referencia_fecha_datos')}; precio {((data.get('precio') or {}).get('valor'))}\n"
            f"- DCF inicial: {'; '.join(hechos) or 'plantilla'}\n"
            f"- Avisos de datos: {len(avisos)}\n"
            f"- Siguiente paso: abre la web, elige {name} y pulsa «Editar» para escribir tu análisis.")
    return comp, True


def cli(argv=None):
    ap = argparse.ArgumentParser(description="Añade una compañía al valorador.")
    ap.add_argument("ticker")
    ap.add_argument("--nombre", default="")
    ap.add_argument("--color", default="")
    a = ap.parse_args(argv)
    color = a.color.strip()
    if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        color = ""
    try:
        add(a.ticker, a.nombre.strip() or None, color or None)
    except NoSoportada as e:
        summary(f"❌ {e}")
        print(f"::error title=Alta no realizada::{e}")
        return 3
    except SecError as e:
        summary(f"❌ Error de la SEC: {e}")
        print(f"::error title=SEC::{e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(cli())
