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

from . import prices
from .build import NoSecData, build_company
from .extract import warn
from .sec_client import SecClient, SecError, cik_10

ROOT = Path(__file__).resolve().parent.parent
VOLATILE = ("generado",)


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
}


def ensure_companion_files(company, root=ROOT):
    created = []
    slug = company["ticker"].upper()
    for folder, blank in (("analysis", BLANK_ANALYSIS), ("manual", BLANK_MANUAL)):
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


def run(only=None, report=None, root=ROOT, client=None, provider=None, price_warning=None):
    companies = load_companies(root)
    if only:
        wanted = {t.upper() for t in only}
        companies = [c for c in companies if c["ticker"].upper() in wanted]
    client = client or SecClient()
    if provider is None:
        provider, price_warning = prices.from_env()
    cik_issues = check_ciks(client, companies)

    failures, changed, index = [], [], []
    for c in companies:
        ensure_companion_files(c, root)
        path = root / "data" / f"{c['ticker'].upper()}.json"
        try:
            rec = build_company(client, c, provider, price_warning)
            if c["ticker"] in cik_issues:
                rec["avisos"].insert(0, warn("aviso", "cik", cik_issues[c["ticker"]]))
            if write_if_changed(path, rec):
                changed.append(path.name)
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
                "monograma": c.get("monograma"), "soportada": rec.get("soportada", True),
                "avisos": sum(1 for w in rec.get("avisos", []) if w["nivel"] != "info"),
                "ultimo_informe": ui.get("fecha_presentacion"),
                "datos_hasta": rec.get("referencia_fecha_datos"),
                "precio": (rec.get("precio") or {}).get("valor"),
            })

    if not only:
        idx = {"esquema": 1, "companias": index,
               "generado": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if write_if_changed(root / "data" / "index.json", idx):
            changed.append("index.json")

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
        failures = run(only=a.only, report=a.report)
    except SecError as e:
        print(f"✗ {e}", file=sys.stderr)
        print(f"::error title=SEC::{e}")
        if a.report:
            Path(a.report).write_text(f"# Fallo de la actualización\n\n```\n{e}\n```\n", encoding="utf-8")
        return 2
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
