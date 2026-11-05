"""Rehace solo los informes de resultados, sin volver a descargar toda la SEC.

  python -m fetcher.rehacer                 # todas las compañías
  python -m fetcher.rehacer APP AMZN        # solo esas
  python -m fetcher.rehacer --desde-git     # las que tocó el último push (analysis/, manual/, i18n/)

Lo usa el workflow «Rehacer informes» cuando guardas tu resumen de la presentación, una
estimación manual o una traducción: así el informe y su PDF recogen el cambio en un par de
minutos, sin esperar a la actualización nocturna. Parte de data/<T>.json; solo vuelve a leer
la nota de resultados si el lector cambió de versión, y la cotización fuera de horario si hay
claves de Alpaca.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from . import pressrelease as PR
from . import prices
from .main import load_companies, results_report, write_if_changed

ROOT = Path(__file__).resolve().parent.parent


def desde_git(root: Path):
    """Tickers afectados por el último commit (todos si cambió una traducción)."""
    try:
        files = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"], cwd=root, capture_output=True,
                               text=True, check=True).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if any(f.startswith("i18n/") for f in files):
        return None
    out = set()
    for f in files:
        p = Path(f)
        if p.parts and p.parts[0] in ("analysis", "manual") and p.suffix == ".json" and not p.stem.startswith("_"):
            out.add(p.stem.upper())
    return sorted(out)


def main(argv):
    root = ROOT
    only = [a.upper() for a in argv if not a.startswith("--")]
    if "--desde-git" in argv:
        t = desde_git(root)
        if t == []:
            print("El último cambio no afecta a ningún informe.")
            return 0
        only = t or []
    companies = [c for c in load_companies(root) if not only or c["ticker"].upper() in only]
    client = None
    try:
        from .sec_client import SecClient
        client = SecClient()
    except Exception as e:  # noqa: BLE001  sin SEC se rehace con lo que hay
        print(f"Sin cliente de la SEC ({e}); se usa la nota ya guardada.", file=sys.stderr)
    extended = prices.extended_from_env()
    hechos = []
    for c in companies:
        t = c["ticker"].upper()
        path = root / "data" / f"{t}.json"
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        k8 = rec.get("ultimo_8k_resultados")
        if client is not None and k8 and (k8.get("nota_resultados") or {}).get("version") != PR.VERSION:
            PR.attach(client, k8, previous=None)
            if write_if_changed(path, rec):
                hechos.append(f"nota {t}")
        hechos += results_report(root, c, rec, client=None, provider=None, extended=extended)
    print("Cambios: " + (", ".join(hechos) if hechos else "ninguno"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
