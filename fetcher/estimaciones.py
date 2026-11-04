"""Foto del consenso de analistas antes de cada presentación de resultados.

Finnhub (plan gratuito) solo enseña el consenso del próximo trimestre: en cuanto
la compañía presenta, esa previsión desaparece del calendario. Para poder comparar
después «reportado frente a estimado», cada noche en que falten 30 días o menos
para los resultados se guarda el consenso en

    data/estimaciones/<TICKER>/<fecha de resultados>.json

con la evolución de las revisiones (una línea cada vez que cambia). El informe de
resultados usa la última foto anterior a la presentación.

Las estimaciones que no da Finnhub gratis (beneficio operativo, segmentos, guía)
se escriben a mano en manual/<TICKER>.json → «estimaciones_resultados».
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

VENTANA_DIAS = 30


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def snapshot(root: Path, ticker: str, rec: dict, today: date | None = None):
    """Escribe o actualiza la foto si hay resultados en los próximos 30 días.
    Devuelve la ruta si el archivo cambió, None si no."""
    today = today or date.today()
    E = ((rec or {}).get("resultados_previstos") or {}).get("proximos") or {}
    if not E.get("fecha"):
        return None
    try:
        fecha = date.fromisoformat(E["fecha"])
    except ValueError:
        return None
    if not 0 <= (fecha - today).days <= VENTANA_DIAS:
        return None
    vals = {"bpa": E.get("bpa_estimado"), "ingresos": E.get("ingresos_estimados")}
    if vals["bpa"] is None and vals["ingresos"] is None:
        return None
    path = root / "data" / "estimaciones" / ticker.upper() / f"{fecha.isoformat()}.json"
    old = _load(path) or {}
    evol = list(old.get("evolucion") or [])
    if not evol or {k: evol[-1].get(k) for k in vals} != vals:
        evol.append({"fecha": today.isoformat(), **vals})
    obj = {
        "_nota": "Consenso de analistas antes de la presentación (Finnhub, plan gratuito). Lo escribe el Action; no se edita a mano.",
        "ticker": ticker.upper(),
        "fecha_resultados": fecha.isoformat(),
        "hora": E.get("hora"),
        "hora_codigo": E.get("hora_codigo"),
        "trimestre": E.get("trimestre"),
        "anio": E.get("anio"),
        "finnhub": {**vals, "capturado": evol[-1]["fecha"],
                    "fuente": "Finnhub · calendario de resultados (consenso)",
                    "url": "https://finnhub.io/docs/api/earnings-calendar"},
        "evolucion": evol[-20:],
    }
    if old == obj:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def for_report(root: Path, ticker: str, fecha_resultados: date, max_dias=7):
    """La foto más cercana a la fecha de la presentación (± 7 días), o None."""
    folder = root / "data" / "estimaciones" / ticker.upper()
    best = None
    for f in folder.glob("*.json") if folder.exists() else []:
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        gap = abs((d - fecha_resultados).days)
        if gap <= max_dias and (best is None or gap < best[0]):
            best = (gap, f)
    return _load(best[1]) if best else None


PLANTILLA_MANUAL = {
    "_nota": ("Estimaciones que no da Finnhub gratis. Rellénalas antes de los resultados (por ejemplo, desde Investing). "
              "Cifras en millones de dólares salvo el BPA (dólares por acción). Lo vacío se deja en null. "
              "«periodo» es el trimestre al que se refieren, como lo escribe la web (p. ej. 4T26). "
              "«segmentos_M» usa los nombres de los segmentos de la web (p. ej. «Amazon Web Services»). "
              "«segmento_clave» elige el segmento del gráfico de run-rate (vacío = el que más crece)."),
    "periodo": "",
    "fuente": "",
    "fecha": "",
    "ingresos_M": None,
    "bpa": None,
    "beneficio_operativo_M": None,
    "segmentos_M": {},
    "guia_ingresos_M": None,
    "guia_beneficio_operativo_M": None,
    "segmento_clave": "",
}


def manual_for(manual: dict | None, periodo: str):
    """Bloque «estimaciones_resultados» de manual/<T>.json para ese trimestre (admite uno o una lista)."""
    blk = (manual or {}).get("estimaciones_resultados")
    items = blk if isinstance(blk, list) else [blk] if isinstance(blk, dict) else []
    for it in items:
        if isinstance(it, dict) and str(it.get("periodo") or "").strip().upper() == periodo.upper():
            return it
    return None


def segmento_clave(manual: dict | None):
    blk = (manual or {}).get("estimaciones_resultados")
    items = blk if isinstance(blk, list) else [blk] if isinstance(blk, dict) else []
    for it in items:
        if isinstance(it, dict) and str(it.get("segmento_clave") or "").strip():
            return str(it["segmento_clave"]).strip()
    return None
