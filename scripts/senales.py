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
- una publicación nueva en la sala de prensa o el blog de la compañía (companies.json → newsroom);
- una presentación a la SEC que no es 8-K/10-Q/10-K (formulario 3, 13D, junta, emisión, OPA…;
  data/<T>.json → presentaciones_sec);
  (si la sala publica mucho, como un blog, solo cuentan las publicaciones con palabras de novedad material);
- un asunto vigilado en seguimientos.json con hallazgos nuevos o estado distinto de «sin_cambios»;
- resultados en los próximos 7 días o en los 3 últimos (reacción y cambios de precio objetivo);
- la compañía nunca ha tenido revisión de internet.

Los titulares de precio objetivo o recomendación de analistas no abren la revisión: se listan aparte
(«precio_objetivo») para actualizar manual/<T>.json, que es barato.

La ventana empieza el día de la revisión anterior (propuestas/_estado.json → internet.<T>);
si no hay ninguna, los 3 últimos días.
"""
from __future__ import annotations

import argparse
import json
import re
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
# Titulares de cambios de precio objetivo o de recomendación («Price Target», «Upgrades», «Initiates»…)
PRECIO_OBJETIVO = re.compile(r"price target|\bPT\b|upgrade|downgrade|initiat\w* coverage|initiates|"
                             r"reiterat\w*|maintains (buy|sell|hold|neutral|overweight|underweight|outperform)|"
                             r"precio objetivo|consensus price", re.I)
VIA_SALA = "Sala de prensa de la compañía"
SALA_POCAS = 3              # salas con pocas publicaciones: cualquiera es señal; con muchas (blogs), solo las materiales
MATERIAL = re.compile(r"acqui|merger|agreement|partnership|appoint|names .*(chief|officer|ceo|cfo)|resign|steps down|"
                      r"guidance|outlook|dividend|repurchase|buyback|offering|notes due|lawsuit|settlement|investigation|"
                      r"layoff|restructur|recall|fda|approval|contract|price increase|tests? ads|advertis", re.I)


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
    propias = [n for n in nuevas if n.get("tipo") in ("nota_prensa", "sectorial") and n.get("via") != VIA_SALA]
    if propias:
        s.append(f"{len(propias)} nota(s) de prensa o noticia(s) sectorial(es)")
    sala = [n for n in nuevas if n.get("via") == VIA_SALA]
    sala_mat = [n for n in sala if MATERIAL.search(n.get("titular") or "")]
    if sala and (len(sala) <= SALA_POCAS or sala_mat):
        s.append(f"{len(sala_mat) or len(sala)} publicación(es) en la sala de prensa de la compañía")
    sec = [p for p in data.get("presentaciones_sec") or [] if (fecha(p.get("fecha_presentacion")) or date.min) > desde]
    if sec:
        s.append("SEC: " + "; ".join(sorted({f"{p['formulario']} ({p['descripcion']})" for p in sec})))
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


def objetivos(data: dict, desde: date) -> list[str]:
    """Titulares de la ventana sobre precio objetivo o recomendación: no abren la revisión de internet,
    pero la tarea actualiza con ellos manual/<T>.json (apartado 5 bis), que es barato."""
    return [n["titular"] for n in data.get("noticias") or []
            if (fecha(n.get("fecha")) or date.min) > desde and PRECIO_OBJETIVO.search(n.get("titular") or "")]


def lista_companias() -> list[dict]:
    cos = rd(ROOT / "companies.json", []) or []
    cos = cos if isinstance(cos, list) else next((v for v in cos.values() if isinstance(v, list)), [])
    return [c for c in cos if not c.get("archivada")]   # las archivadas no se revisan


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
        out.append({"ticker": t, "desde": desde.isoformat(), "revisar": bool(s), "senales": s,
                    "precio_objetivo": objetivos(data, desde)})
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
        po = f" · precio objetivo: {len(r['precio_objetivo'])} titular(es)" if r["precio_objetivo"] else ""
        print(f"{r['ticker']:6} {'REVISAR' if r['revisar'] else '—':8} desde {r['desde']}: {'; '.join(r['senales']) or 'sin señales'}{po}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
