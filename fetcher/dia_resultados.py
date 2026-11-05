"""Qué compañías actualizar en las pasadas del día de resultados.

  python -m fetcher.dia_resultados manana   # presentan hoy antes de la apertura, o ayer tras el cierre
  python -m fetcher.dia_resultados tarde    # presentan hoy tras el cierre

Lee la próxima fecha de resultados de data/<T>.json (calendario de Finnhub) y escribe los
tickers separados por espacios (vacío si no toca ninguna). La hora es la de Nueva York.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def _prev_habil(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def elegir(root: Path, franja: str, hoy: date | None = None):
    hoy = hoy or datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
    ayer = _prev_habil(hoy)
    out = []
    for f in sorted((root / "data").glob("*.json")):
        if f.name.startswith("_") or f.name == "index.json":
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        p = (d.get("resultados_previstos") or {}).get("proximos") or {}
        k8 = (d.get("ultimo_8k_resultados") or {}).get("fecha_presentacion")
        try:
            fecha = date.fromisoformat(str(p.get("fecha"))[:10])
        except ValueError:
            fecha = None
        hora = p.get("hora_codigo")
        t = d.get("ticker") or f.stem
        if franja == "manana":
            # hoy antes de la apertura (o sin hora conocida), o ayer tras el cierre (reacción en premercado)
            if (fecha == hoy and hora != "amc") or (fecha == ayer and hora in ("amc", None)) or k8 in (hoy.isoformat(), ayer.isoformat()):
                out.append(t)
        elif franja == "tarde":
            if (fecha == hoy and hora in ("amc", "dmh", None)) or k8 == hoy.isoformat():
                out.append(t)
    return sorted(set(out))


if __name__ == "__main__":
    print(" ".join(elegir(ROOT, (sys.argv[1:] or ["manana"])[0])))
