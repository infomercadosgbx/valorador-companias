"""Punto de entrada del Action.

  python -m fetcher.main                 # todas las compañías de companies.json
  python -m fetcher.main --only APP GOOGL
  python -m fetcher.main --report informe.md

Escribe /data/<ticker>.json y /data/index.json solo si su contenido cambia
(se ignora el sello «generado»). Sale con código 2 si alguna compañía no
obtiene datos de la SEC; el workflow abre entonces un Issue.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import estimaciones as EST
from . import logos, prices
from . import resultados as RES
from . import peers as PEERS
from . import seguimientos as SEG
from . import news as NEWS
from .build import NoSecData, build_company
from .extract import warn
from .sec_client import SecClient, SecError, cik_10

ROOT = Path(__file__).resolve().parent.parent
VOLATILE = ("generado",)



def _client_tickers(root, ticker):
    """Tickers de clientes conocidos del análisis (business.clients.conocidos[].t)."""
    try:
        an = json.loads((root / "analysis" / f"{ticker.upper()}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for x in ((an.get("business") or {}).get("clients") or {}).get("conocidos") or []:
        t = str((x or {}).get("t") or "").strip().upper()
        if t and t.replace(".", "").replace("-", "").isalnum() and len(t) <= 8 and t not in out:
            out.append(t)
    return out

def load_companies(root=ROOT):
    return json.loads((root / "companies.json").read_text(encoding="utf-8"))["companies"]


def _stable(obj):
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    return obj


def write_if_changed(path: Path, obj) -> bool:
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if _stable(old) == _stable(obj):
                return False
        except json.JSONDecodeError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


BLANK_ANALYSIS = {
    "_nota": "Supuestos y textos propios. Se editan a mano y se versionan en git; el Action nunca los toca.",
    "esquema": 1,
    "meta": {"sector": "", "sede": "", "fundada": "", "empleados": "", "proximos_resultados": "", "favorita": False},
    "overview": {"tesis": "", "resumen": "", "datos_clave": [], "catalizadores": []},
    "negocio": {"modelo": "", "clientes": "", "segmentos": [], "tipos_cliente": [], "calidad": [], "fase": None, "nota_fase": ""},
    "moat": {"anchura": "", "tendencia": "", "nota": "", "fuentes": [], "competidores": []},
    "crecimiento": {"puntuacion": None, "nota": "", "tam": "", "guia": "", "palancas": []},
    "directiva": {"nota": "", "personas": [], "puntuaciones": []},
    "ultima_presentacion_resultados": {"fecha": "", "resumen": "", "guia": ""},
    "riesgos": [],
    "dcf": {"ingresos_base": None, "anio_base": None, "crecimiento": [None] * 5, "margen_ebitda_1": None,
            "margen_ebitda_5": None, "da": None, "sbc": None, "capex": None, "capital_circulante": None,
            "impuestos": None, "wacc": None, "g_terminal": None, "multiplo_salida": None, "metodo": "blend",
            "deuda_modelo": None, "caja_modelo": None, "acciones_modelo": None,
            "escenarios": [{"n": "Bajista", "dg": -10, "dm": -3, "p": 25}, {"n": "Base", "dg": 0, "dm": 0, "p": 50},
                           {"n": "Alcista", "dg": 6, "dm": 1, "p": 25}]},
    "veredicto": {"rating": "", "conviccion": None, "comprar_por_debajo": None, "horizonte": "", "resumen": "",
                  "alcista": [], "bajista": [], "vigilar": []},
    "notas": "",
}

BLANK_MANUAL = {
    "_nota": "Consenso de analistas introducido a mano (no hay fuente gratuita fiable de precios objetivo). La web lo marca como «manual».",
    "precio_objetivo_medio": None, "precio_objetivo_bajo": None, "precio_objetivo_alto": None,
    "num_analistas": None, "fuente": "", "fecha": "",
    "historial_objetivo": [],
    "estimaciones_resultados": [],
}


def ensure_companion_files(company, root=ROOT):
    created = []
    slug = company["ticker"].upper()
    tpl = root / "analysis" / "_plantilla.json"
    analysis_blank = json.loads(tpl.read_text(encoding="utf-8")) if tpl.exists() else BLANK_ANALYSIS
    for folder, blank in (("analysis", analysis_blank), ("manual", BLANK_MANUAL)):
        p = root / folder / f"{slug}.json"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(blank, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            created.append(str(p.relative_to(root)))
    return created


def check_ciks(client, companies):
    """Compara el CIK de companies.json con el oficial; devuelve {ticker: aviso}."""
    out = {}
    try:
        table = client.company_tickers() or {}
    except SecError as e:
        return {c["ticker"]: f"No se pudo comprobar el CIK: {e}" for c in companies}
    by_ticker = {v["ticker"].upper(): cik_10(v["cik_str"]) for v in table.values()}
    for c in companies:
        official = by_ticker.get(c["ticker"].upper())
        if official and official != cik_10(c["cik"]):
            out[c["ticker"]] = f"El CIK de companies.json ({c['cik']}) no coincide con el de la SEC ({official})."
    return out


def _json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def results_report(root, company, rec, client=None, provider=None, extended=None):
    """Foto del consenso antes de resultados e informe de la última presentación.
    Es secundario: un fallo deja un aviso en el log y no detiene la actualización."""
    t = company["ticker"].upper()
    out = []
    try:
        if EST.snapshot(root, t, rec):
            out.append(f"estimaciones {t}")
        an = _json(root / "analysis" / f"{t}.json")
        man = _json(root / "manual" / f"{t}.json")
        rep, hist_changed = RES.build(root, company, rec, an, man, client=client, provider=provider, extended=extended)
        if hist_changed:
            out.append(f"segmentos {t}")
        if rep:
            if write_if_changed(root / "data" / "resultados" / t / f"{rep['periodo']}.json", rep):
                out.append(f"resultados {t} {rep['periodo']}")
            if RES.write_index(root, t):
                out.append(f"índice resultados {t}")
    except Exception as e:  # noqa: BLE001
        print(f"Informe de resultados de {t} no disponible: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
    return out


def run(only=None, report=None, root=ROOT, client=None, provider=None, price_warning=None, history=None, market=False):
    companies = load_companies(root)
    if only:
        wanted = {t.upper() for t in only}
        companies = [c for c in companies if c["ticker"].upper() in wanted]
    client = client or SecClient()
    real = provider is None            # ejecución real (Action): APIs de noticias y feeds RSS; en los tests, no
    if provider is None:
        provider, price_warning = prices.from_env()
    NEWS.APIS = NEWS.apis_from_env() if real else []
    NEWS.FEEDS_CACHE = NEWS.FeedCache() if real else None
    NEWS.REDES = real
    hist, hist_warning = (history if history is not None else prices.history_from_env())
    extended = prices.extended_from_env()
    cik_issues = check_ciks(client, companies)

    failures, changed, index = [], [], []
    peer_cache = None
    try:
        prev_items = {}
        for f in (root / "data").glob("*.json") if (root / "data").exists() else []:
            try:
                for it in (json.loads(f.read_text(encoding="utf-8")).get("peers") or {}).get("competidores") or []:
                    prev_items.setdefault(it["ticker"], it)
            except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
                pass
        peer_cache = PEERS.PeerCache(client, provider, PEERS.table_by_ticker(client), prev_items, root=root)
    except Exception as e:  # noqa: BLE001  la comparativa es secundaria
        print(f"Comparativa con competidores no disponible: {e}", file=sys.stderr)
    for c in companies:
        ensure_companion_files(c, root)
        path = root / "data" / f"{c['ticker'].upper()}.json"
        try:
            previous = None
            if path.exists():
                try:
                    previous = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    previous = None
            rec = build_company(client, c, provider, price_warning, previous, hist, hist_warning)
            if peer_cache is not None and rec.get("soportada", True):
                try:
                    an = json.loads((root / "analysis" / f"{c['ticker'].upper()}.json").read_text(encoding="utf-8"))
                    manual = [str(x).upper() for x in (an.get("peers") or []) if str(x).strip()]
                except (OSError, json.JSONDecodeError):
                    manual = []
                try:
                    rec["peers"] = PEERS.build(c, rec, manual, peer_cache)
                except Exception as e:  # noqa: BLE001
                    rec["peers"] = (previous or {}).get("peers")
                    rec["avisos"].append(warn("info", "peers_no_disponible", f"Comparativa con competidores no disponible: {e}"))
            if rec.get("soportada", True):
                try:
                    SEG.actualizar(client, c, rec, previous, root)
                except Exception as e:  # noqa: BLE001  el seguimiento es secundario
                    if (previous or {}).get("seguimientos"):
                        rec["seguimientos"] = previous["seguimientos"]
                    print(f"Seguimientos de {c['ticker']} no disponibles: {e}", file=sys.stderr)
            perfil, logo_changed = logos.update(provider, c, root)
            if perfil:
                rec["perfil"] = perfil
            if logo_changed:
                changed.append(f"logo {c['ticker']}")
            for ct in _client_tickers(root, c["ticker"]):   # logos de los clientes cotizados (campo "t" del análisis)
                if not any((root / "logos").glob(f"{ct}.*")):
                    _, ch = logos.update(provider, {"ticker": ct}, root)
                    if ch:
                        changed.append(f"logo {ct}")
            if c["ticker"] in cik_issues:
                rec["avisos"].insert(0, warn("aviso", "cik", cik_issues[c["ticker"]]))
            if write_if_changed(path, rec):
                changed.append(path.name)
            changed += results_report(root, c, rec, client, provider, extended)
            print(f"✓ {c['ticker']}: {len(rec.get('avisos', []))} avisos")
        except (NoSecData, SecError) as e:
            failures.append((c["ticker"], str(e)))
            print(f"✗ {c['ticker']}: {e}", file=sys.stderr)
            print(f"::error title={c['ticker']}::{str(e)[:500]}")
            rec = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except Exception as e:  # noqa: BLE001  error de programa: también abre Issue
            failures.append((c["ticker"], f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
            print(f"✗ {c['ticker']}: {e}", file=sys.stderr)
            rec = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if rec:
            ui = rec.get("ultimo_informe") or {}
            index.append({
                "ticker": c["ticker"].upper(), "nombre": c["nombre"], "color": c.get("color"),
                "monograma": c.get("monograma"), "logo": (rec.get("perfil") or {}).get("logo"), "soportada": rec.get("soportada", True),
                "avisos": sum(1 for w in rec.get("avisos", []) if w["nivel"] != "info"),
                "ultimo_informe": ui.get("fecha_presentacion"),
                "datos_hasta": rec.get("referencia_fecha_datos"),
                "precio": (rec.get("precio") or {}).get("valor"),
            })

    # El historial de veredictos ya no sale de git: vive en analysis/<T>.json → "veredictos"
    # y se crea con «Registrar veredicto» en la web (ver scripts/migrar_veredictos.py).

    if hist is not None:
        try:
            h = hist.history("SPY")
            if h:
                h["nombre"] = "S&P 500 (ETF SPY)"
                if write_if_changed(root / "data" / "_indice.json", h):
                    changed.append("_indice.json")
        except Exception as e:  # noqa: BLE001  la referencia es secundaria
            print(f"Índice de referencia no disponible: {e}", file=sys.stderr)

    if market:   # referencia del WACC: bono a 10 años (oficial)
        try:
            from . import market as MK
            b = MK.treasury_10y()
            if b:
                old = {}
                try:
                    old = json.loads((root / "data" / "_mercado.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
                if write_if_changed(root / "data" / "_mercado.json", dict(old, bono_10a=b)):
                    changed.append("_mercado.json")
        except Exception as e:  # noqa: BLE001  secundario
            print(f"Bono a 10 años no disponible: {e}", file=sys.stderr)

    if only:   # se conserva lo ya publicado del resto y se respeta el orden de companies.json
        old = {}
        try:
            old = {c["ticker"]: c for c in json.loads((root / "data" / "index.json").read_text(encoding="utf-8"))["companias"]}
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        new = {c["ticker"]: c for c in index}
        index = [new.get(c["ticker"].upper()) or old.get(c["ticker"].upper()) for c in load_companies(root)]
        index = [c for c in index if c]
    idx = {"esquema": 1, "companias": index,
           "generado": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if write_if_changed(root / "data" / "index.json", idx):
        changed.append("index.json")

    if NEWS.FEEDS_CACHE is not None and NEWS.FEEDS_CACHE.estado:
        prev_est = {}
        try:
            prev_est = json.loads((root / "data" / "_noticias_estado.json").read_text(encoding="utf-8")).get("medios") or {}
        except (OSError, json.JSONDecodeError):
            pass
        est = {"esquema": 1, "medios": dict(prev_est, **NEWS.FEEDS_CACHE.estado),
               "apis": [a.nombre for a in NEWS.APIS],
               "generado": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if write_if_changed(root / "data" / "_noticias_estado.json", est):
            changed.append("_noticias_estado.json")

    if report:
        lines = [f"# Fallo de la actualización de datos ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)", ""]
        for t, msg in failures:
            lines += [f"## {t}", "", "```", msg.strip(), "```", ""]
        if not failures:
            lines.append("Sin errores.")
        Path(report).write_text("\n".join(lines), encoding="utf-8")
    print(f"Archivos cambiados: {', '.join(changed) or 'ninguno'}; peticiones a la SEC: {client.requests_made}")
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(description="Descarga datos oficiales de la SEC y precios.")
    ap.add_argument("--only", nargs="*", help="tickers a actualizar")
    ap.add_argument("--report", help="ruta del informe de errores (Markdown)")
    a = ap.parse_args(argv)
    try:
        failures = run(only=a.only, report=a.report, market=True)
    except SecError as e:
        print(f"✗ {e}", file=sys.stderr)
        print(f"::error title=SEC::{e}")
        if a.report:
            Path(a.report).write_text(f"# Fallo de la actualización\n\n```\n{e}\n```\n", encoding="utf-8")
        return 2
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
