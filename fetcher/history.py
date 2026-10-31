"""Historial de veredictos: cada versión de analysis/<TICKER>.json guardada en git.

Se escribe en data/historial/<TICKER>.json con la fecha del commit, la fecha
«Análisis a», la recomendación, la convicción, el precio de compra y los
supuestos del DCF de entonces (la web recalcula el valor con ellos).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _git(root: Path, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def versions(root: Path, ticker: str, limit=60):
    rel = f"analysis/{ticker}.json"
    try:
        log = _git(root, "log", "--format=%H|%cI", "--follow", "--", rel)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    out, last = [], None
    for line in reversed(log.strip().splitlines()[:limit]):
        sha, when = line.split("|", 1)
        try:
            a = json.loads(_git(root, "show", f"{sha}:{rel}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        ver = a.get("verdict") or a.get("veredicto") or {}
        v = a.get("v") or {}
        rec = {"fecha_commit": when[:10], "commit": sha[:10],
               "analisis_a": (a.get("meta") or {}).get("asOf"),
               "recomendacion": ver.get("rating"), "conviccion": ver.get("conviction"),
               "comprar_por_debajo": ver.get("buyBelow"), "horizonte": ver.get("horizon"),
               "resumen": (ver.get("summary") or "")[:400], "supuestos": v}
        sig = json.dumps({k: rec[k] for k in ("analisis_a", "recomendacion", "conviccion", "comprar_por_debajo", "supuestos")}, sort_keys=True)
        if sig == last:
            continue
        last = sig
        out.append(rec)
    return out
