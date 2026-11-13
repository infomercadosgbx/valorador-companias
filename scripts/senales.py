"""Qué compañías necesitan hoy la revisión de internet (parte B de la tarea programada).

La parte B corre cada mañana, pero solo para las compañías con alguna señal desde la
revisión de internet anterior; el viernes, para todas (repaso semanal completo).

    python scripts/senales.py            # imprime la lista y el motivo de cada compañía
    python scripts/senales.py --json     # lo mismo en JSON (para la tarea programada)
    python scripts/senales.py --marcar   # tras la revisión: guarda hoy como última revisión

Señales (umbrales en las constantes de abajo):
- movimiento de la cotización de un día ≥ 6 % dentro de la ventana;
- 2 o más titulares nuevos (data/<T>.json → noticias) con sentimiento muy marcado (no se usa
  el número de titulares: Finnhub da casi a diario una decena por compañía grande);
- una nota de prensa de la compañía o un titular de un medio sectorial nuevos;
- un asunto vigilado en seguimientos.json con hallazgos nuevos o estado distinto de «sin_cambios»;
- resultados en los próximos 7 días o en los 3 últimos (reacción y cambios de precio objetivo);
- la compañía nunca ha tenido revisión de internet.

La ventana empieza el día de la revisión anterior (propuestas/_estado.json → internet.<T>);
si no hay ninguna, los 3 últimos días.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ESTADO = ROOT / "propuestas" / "_estado.json"

UMBRAL_MOVIMIENTO = 6.0     # % de un día
UMBRAL_SENTIMIENTO = 0.5    # |puntuación| de un titular
UMBRAL_FUERTES = 2          # titulares con sentimiento muy marcado en la ventana
DIAS_ANTES_RESULTADOS = 7
DIAS_TRAS_RESULTADOS = 3
VENTANA_POR_DEFECTO = 3
DIA_REPASO_COMPLETO = 5     # viernes (isoweekday)


def rd(p: Path, default=None):
    if not p.exists() or not p.read_text(encoding="utf-8").strip():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def fecha(s) -> date | None:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def senales(t: str, data: dict, desde: date, hoy: date) -> list[str]:
    s = []
    serie = (data.get("historico_precio") or {}).get("serie") or []
    for (f0, p0), (f1, p1) in zip(serie, serie[1:]):
        d1 = fecha(f1)
        if d1 and d1 > desde and p0:
            var = (p1 / p0 - 1) * 100
            if abs(var) >= UMBRAL_MOVIMIENTO:
                s.append(f"cotización {var:+.1f} % el {f1}")
    nuevas = [n for n in data.get("noticias") or [] if (fecha(n.get("fecha")) or date.min) > desde]
    fuertes = [n for n in nuevas if abs(((n.get("sentimiento") or {}).get("puntuacion") or 0)) >= UMBRAL_SENTIMIENTO]
    if len(fuertes) >= UMBRAL_FUERTES:
        s.append(f"{len(fuertes)} titular(es) con sentimiento muy marcado")
    propias = [n for n in nuevas if n.get("tipo") in ("nota_prensa", "sectorial")]
    if propias:
        s.append(f"{len(propias)} nota(s) de prensa o noticia(s) sectorial(es)")
    for seg in data.get("seguimientos") or []:
        cod = (seg.get("estado") or {}).get("codigo")
        hall = [h for h in seg.get("hallazgos") or [] if (fecha(h.get("fecha")) or date.min) > desde]
        if hall or (cod and cod != "sin_cambios"):
            s.append(f"seguimiento «{seg.get('titulo', seg.get('id'))}»")
    prox = fecha(((data.get("resultados_previstos") or {}).get("proximos") or {}).get("fecha"))
    if prox and 0 <= (prox - hoy).days <= DIAS_ANTES_RESULTADOS:
        s.append(f"resultados el {prox.isoformat()}")
    ult = fecha((data.get("ultimo_8k_resultados") or {}).get("fecha_presentacion"))
    if ult and 0 <= (hoy - ult).days <= DIAS_TRAS_RESULTADOS:
        s.append(f"resultados presentados el {ult.isoformat()}")
    return s


def lista_companias() -> list[dict]:
    cos = rd(ROOT / "companies.json", []) or []
    return cos if isinstance(cos, list) else next((v for v in cos.values() if isinstance(v, list)), [])


def calcular(hoy: date) -> list[dict]:
    companias = lista_companias()
    estado = (rd(ESTADO, {}) or {}).get("internet", {})
    completo = hoy.isoweekday() == DIA_REPASO_COMPLETO
    out = []
    for c in companias:
        t = c["ticker"]
        data = rd(ROOT / "data" / f"{t}.json", {}) or {}
        ultima = fecha(estado.get(t))
        desde = ultima or hoy - timedelta(days=VENTANA_POR_DEFECTO)
        s = senales(t, data, desde, hoy)
        if ultima is None:
            s.append("sin revisión de internet anterior")
        if completo and not s:
            s.append("repaso semanal completo (viernes)")
        out.append({"ticker": t, "desde": desde.isoformat(), "revisar": bool(s), "senales": s})
    return out


def marcar(hoy: date, tickers: list[str] | None) -> None:
    estado = rd(ESTADO, {}) or {}
    internet = estado.setdefault("internet", {})
    for c in lista_companias():
        if not tickers or c["ticker"] in tickers:
            internet[c["ticker"]] = hoy.isoformat()
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--marcar", nargs="*", metavar="TICKER", help="guardar hoy como última revisión (sin tickers = todas)")
    ap.add_argument("--hoy", help="AAAA-MM-DD (para pruebas)")
    a = ap.parse_args()
    hoy = fecha(a.hoy) if a.hoy else datetime.now(ZoneInfo("Europe/Madrid")).date()
    if a.marcar is not None:
        marcar(hoy, a.marcar)
        return 0
    res = calcular(hoy)
    if a.json:
        json.dump(res, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    for r in res:
        print(f"{r['ticker']:6} {'REVISAR' if r['revisar'] else '—':8} desde {r['desde']}: {'; '.join(r['senales']) or 'sin señales'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
