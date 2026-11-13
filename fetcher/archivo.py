"""Archivar y reactivar compañías sin borrarlas.

  python -m fetcher.archivo archivar CVX --motivo "Ya no la sigo"
  python -m fetcher.archivo reactivar CVX

Una compañía archivada sigue en companies.json con «archivada»: {desde, motivo}. El robot nocturno,
la tarea programada y aplicar_cambios.py se la saltan (no se gasta nada en ella), y sus datos, su análisis,
sus propuestas y su cola se quedan como estaban. La web la quita de las listas y la enseña en
Ajustes → Compañías, con el botón «Reactivar».

Al reactivarla se quita «archivada», se anota «reactivada» con la fecha (la tarea programada le hace el
repaso completo con las mismas reglas que a una compañía nueva: ACTUALIZACION_COMPLETA.md, apartado 0)
y se descargan sus datos al momento.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .add_company import dump_companies  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class NoEncontrada(Exception):
    pass


def _leer(root: Path):
    f = root / "companies.json"
    return f, json.loads(f.read_text(encoding="utf-8"))


def _buscar(cj, ticker):
    t = ticker.strip().upper()
    c = next((x for x in cj["companies"] if x["ticker"].upper() == t), None)
    if not c:
        raise NoEncontrada(f"{t} no está en companies.json.")
    return c


def archivar(ticker: str, motivo: str = "", root: Path = ROOT, hoy: date | None = None) -> dict:
    f, cj = _leer(root)
    c = _buscar(cj, ticker)
    if c.get("archivada"):
        return c
    c["archivada"] = {"desde": (hoy or date.today()).isoformat(), "motivo": (motivo or "").strip()}
    f.write_text(dump_companies(cj), encoding="utf-8")
    return c


def reactivar(ticker: str, root: Path = ROOT, hoy: date | None = None, descargar=True, client=None) -> dict:
    f, cj = _leer(root)
    c = _buscar(cj, ticker)
    if not c.get("archivada"):
        return c
    c.pop("archivada", None)
    c["reactivada"] = (hoy or date.today()).isoformat()
    if not c.get("repaso"):
        from .add_company import dia_repaso
        c["repaso"] = dia_repaso(cj)
    f.write_text(dump_companies(cj), encoding="utf-8")
    if descargar:
        from . import main as M
        M.run(only=[c["ticker"]], root=root, client=client)
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("accion", choices=["archivar", "reactivar"])
    ap.add_argument("ticker")
    ap.add_argument("--motivo", default="")
    ap.add_argument("--sin-descarga", action="store_true", help="al reactivar, no descargar los datos ahora")
    a = ap.parse_args(argv)
    try:
        if a.accion == "archivar":
            c = archivar(a.ticker, a.motivo)
            print(f"Archivada: {c['nombre']} ({c['ticker']}) desde {c['archivada']['desde']}")
        else:
            c = reactivar(a.ticker, descargar=not a.sin_descarga)
            print(f"Reactivada: {c['nombre']} ({c['ticker']}) el {c.get('reactivada')}")
    except NoEncontrada as e:
        print(str(e), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
