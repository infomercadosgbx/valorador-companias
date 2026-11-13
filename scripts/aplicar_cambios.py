"""Aplica lo verificado de una propuesta y deja el resto para el usuario.

Lo ejecuta la tarea programada «Valorador · revisión tras resultados y novedades»
(propuestas/INSTRUCCIONES.md, apartado 8), DESPUÉS de que el segundo agente haya
rellenado `verificacion` en cada cambio.

    python scripts/aplicar_cambios.py VST                 # una compañía
    python scripts/aplicar_cambios.py --todas             # todas las de companies.json
    python scripts/aplicar_cambios.py --todas --sabado    # además publica la cola semanal

Qué hace, por compañía:
1. Quita los ajustes por hechos posteriores caducados (hay un 10-Q/10-K nuevo).
2. Aprueba los avisos de calidad del dato que el robot ha explicado (`avisos_resueltos`).
3. Aplica a analysis/<T>.json los cambios de HECHOS y de TEXTOS de las pestañas
   (tesis, negocio, MOAT, crecimiento, directiva, riesgos) con `verificacion.ok = true`
   y los anota en `cambios_auto` (la web los enseña y permite deshacerlos). Una
   puntuación que salta más de un punto espera al usuario.
4. Los cambios de CRITERIO (DCF, veredicto, notas, comparables):
   - v.* (supuestos del DCF): solo siguen si mueven el valor por acción ≥ 5 %.
   - Con resultados o novedad grave (`urgente`, o impacto ≥ 10 %): quedan en la
     propuesta para hoy. Si no, van a la cola semanal propuestas/_cola/<T>.json,
     que se publica el sábado (--sabado).
5. Los hechos que no superan la verificación quedan en la propuesta de hoy, con el motivo.

Nunca toca data/, los supuestos del DCF ni el veredicto de analysis/.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
PROP = ROOT / "propuestas"
COLA = PROP / "_cola"

# Hechos que el robot puede aplicar solo (si pasan la verificación). Todo lo que
# no esté aquí es criterio del usuario y nunca se aplica automáticamente.
HECHOS = [
    r"overview\.(keyFacts|catalysts|summary)(\..*)?",
    r"meta\.(asOf|nextEarnings|employees|hq|founded)",
    r"business\.(model|customers|customerTypes|clients|segments|segNote)(\..*)?",
    r"growth\.(guidance|tam)(\..*)?",
    r"mgmt\.(call|people|vote|alloc)(\..*)?",
    r"fin_manual(\..*)?",
    r"sources\.(docs|news)(\..*)?",
    r"social\.(pulse|videos|pulseFuente)(\..*)?",
    r"ajustes_posteriores",
]
# Textos y puntuaciones de las pestañas que el robot también aplica solo, tras la misma
# verificación independiente (el usuario lo pidió el 13-nov-2026). Desde el 13-nov-2026 también
# los textos del veredicto (resumen, a favor, en contra, qué vigilar). Quedan siempre para el
# usuario: los supuestos del DCF (v.*), la recomendación, el precio de compra, la convicción y
# el horizonte (verdict.rating, buyBelow, conviction, horizon…), sus notas (notes) y los
# comparables de la valoración (peers).
TEXTOS = [
    r"overview\.thesis",
    r"verdict\.(summary|bull|bear|watch)(\..*)?",
    r"business\.(quality|phase|phaseNote)(\..*)?",
    r"moat(\..*)?",
    r"growth\.(score|scoreNote|drivers)(\..*)?",
    r"mgmt\.(note|scores)(\..*)?",
    r"risks(\..*)?",
    r"sources\.(web|ir)(\..*)?",
]
PROHIBIDOS = {"cambios_auto", "avisos_aprobados", "veredictos"}
SALTO_MAX = 1         # una puntuación (1-5) que se mueve más que esto espera al usuario
UMBRAL_DCF = 5.0      # % mínimo de cambio en el valor para proponer supuestos del DCF
UMBRAL_GRAVE = 10.0   # % a partir del cual no se espera al sábado
MAX_REGISTRO = 120


def es_hecho(campo: str) -> bool:
    return any(re.fullmatch(p, campo) for p in HECHOS)


def es_texto(campo: str) -> bool:
    return any(re.fullmatch(p, campo) for p in TEXTOS)


def _puntos(v, ruta="") -> dict:
    """Puntuaciones numéricas (s, p, i, threat, score) de un valor, indexadas por nombre."""
    out = {}
    if isinstance(v, (int, float)) and not isinstance(v, bool) and ruta:
        out[ruta] = float(v)
    elif isinstance(v, dict):
        for k, x in v.items():
            if k in ("s", "p", "i", "threat", "score") and isinstance(x, (int, float, str)):
                try:
                    out[f"{ruta}.{k}"] = float(x)
                except ValueError:
                    pass
    elif isinstance(v, list):
        for j, x in enumerate(v):
            nombre = x.get("n", j) if isinstance(x, dict) else j
            out.update(_puntos(x, f"{ruta}[{nombre}]"))
    return out


def salto_grande(antes, despues) -> str | None:
    """Devuelve la puntuación que se mueve más de SALTO_MAX puntos, si la hay."""
    a, d = _puntos(antes, "·"), _puntos(despues, "·")
    for k, x in d.items():
        if k in a and abs(x - a[k]) > SALTO_MAX:
            return f"{k.lstrip('·.')} pasa de {a[k]:g} a {x:g}"
    return None


def rd(p: Path, default=None):
    if not p.exists() or not p.read_text(encoding="utf-8").strip():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def wr(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def get_path(o, campo):
    for k in campo.split("."):
        if o is None:
            return None
        o = o[int(k)] if isinstance(o, list) and k.isdigit() and int(k) < len(o) else (o.get(k) if isinstance(o, dict) else None)
    return o


def set_path(o, campo, valor):
    ks = campo.split(".")
    for i, k in enumerate(ks[:-1]):
        nxt = ks[i + 1]
        if isinstance(o, list):
            o = o[int(k)]
            continue
        if o.get(k) is None:
            o[k] = [] if nxt.isdigit() else {}
        o = o[k]
    last = ks[-1]
    if isinstance(o, list):
        idx = int(last)
        while len(o) <= idx:
            o.append(None)
        o[idx] = valor
    else:
        o[last] = valor


def w_id(codigo: str, mensaje: str) -> str:
    """Mismo identificador que la web (wId en valorador.html)."""
    return (codigo or "") + "." + re.sub(r"\d[\d.,]*", "#", mensaje or "")[:80]


def impacto(t: str, cambios: list) -> float | None:
    v = [c for c in cambios if c["campo"].startswith("v.") or c["campo"] == "ajustes_posteriores"]
    if not v:
        return None
    tmp = COLA / f".impacto_{t}.json"
    wr(tmp, {"cambios": v})
    try:
        out = subprocess.run(["node", str(ROOT / "scripts" / "impacto_dcf.mjs"), t, str(tmp)],
                             capture_output=True, text=True, timeout=60, check=True).stdout
        return json.loads(out).get("cambio_pct")
    except Exception as e:  # sin node o sin modelo: no se filtra, decide el usuario
        print(f"  ! {t}: no se pudo calcular el impacto en el DCF ({e})", file=sys.stderr)
        return None
    finally:
        tmp.unlink(missing_ok=True)


def fusionar(dst: dict | None, src: dict, hoy: str) -> dict:
    """Une dos propuestas: si un campo se repite, gana el de src (más reciente)."""
    if not dst:
        out = copy.deepcopy(src)
        out["creada"] = hoy
        return out
    out = copy.deepcopy(dst)
    campos = {c["campo"] for c in src.get("cambios", [])}
    out["cambios"] = [c for c in out.get("cambios", []) if c["campo"] not in campos] + copy.deepcopy(src.get("cambios", []))
    urls = {f.get("u") for f in out.get("fuentes", [])}
    out.setdefault("fuentes", []).extend(f for f in src.get("fuentes", []) if f.get("u") not in urls)
    if src.get("resumen") and src["resumen"] not in (out.get("resumen") or ""):
        out["resumen"] = ((out.get("resumen") or "") + " " + src["resumen"]).strip()
    out["creada"] = hoy
    return out


def procesar(t: str, hoy: str, sabado: bool) -> dict:
    res = {"ticker": t, "aplicados": [], "fallos": [], "cola": [], "hoy": [], "descartados": [],
           "avisos": 0, "caducados": 0}
    pa = ROOT / "analysis" / f"{t}.json"
    an = rd(pa)
    data = rd(ROOT / "data" / f"{t}.json", {}) or {}
    if an is None:
        return res
    prop = rd(PROP / f"{t}.json")
    cola = rd(COLA / f"{t}.json")
    registro = an.setdefault("cambios_auto", [])
    cambiado = False

    def anotar(campo, antes, despues, c=None, motivo=None):
        c = c or {}
        registro.append({k: v for k, v in {
            "fecha": hoy, "campo": campo, "antes": antes, "despues": despues,
            "porque": c.get("porque"), "fuente": c.get("fuente"),
            "verificacion": (c.get("verificacion") or {}).get("nota"),
            "motivo": motivo or (prop or {}).get("motivo"),
        }.items() if v is not None})

    # 1. Ajustes por hechos posteriores caducados
    accn = (data.get("ultimo_informe") or {}).get("accn")
    aj = an.get("ajustes_posteriores") or []
    vivos = [a for a in aj if not (a.get("base_accn") and accn and a["base_accn"] != accn)]
    if len(vivos) != len(aj):
        res["caducados"] = len(aj) - len(vivos)
        anotar("ajustes_posteriores", aj, vivos, {"porque": "El nuevo informe de la SEC ya recoge esos hechos: el modelo vuelve al dato de la SEC.",
               "fuente": {"t": (data.get("ultimo_informe") or {}).get("formulario", "Informe"), "u": (data.get("ultimo_informe") or {}).get("url_documento"),
                          "d": (data.get("ultimo_informe") or {}).get("fecha_presentacion")},
               "verificacion": {"nota": "Caducidad automática por informe nuevo"}}, motivo="Informe nuevo de la SEC")
        if vivos:
            an["ajustes_posteriores"] = vivos
        else:
            an.pop("ajustes_posteriores", None)
        cambiado = True

    if prop:
        # 2. Avisos de calidad del dato explicados por el robot
        aprob = an.setdefault("avisos_aprobados", [])
        ids = {a.get("id") for a in aprob}
        for a in prop.pop("avisos_resueltos", []) or []:
            i = a.get("id") or w_id(a.get("codigo", ""), a.get("mensaje", ""))
            if i in ids:
                continue
            aprob.append({k: v for k, v in {"id": i, "fecha": hoy, "nivel": a.get("nivel", "aviso"), "mensaje": a.get("mensaje"),
                          "por": "robot", "comprobacion": a.get("comprobacion"), "fuente": a.get("fuente")}.items() if v is not None})
            ids.add(i)
            res["avisos"] += 1
            cambiado = True

        # 3-5. Cambios
        nuevos = [c for c in prop.get("cambios", []) if not c.get("procesado")]
        previos = [c for c in prop.get("cambios", []) if c.get("procesado")]
        quedan_hoy, a_cola = [], []
        criterio = []
        for c in nuevos:
            campo = c.get("campo", "")
            if campo in PROHIBIDOS:
                res["descartados"].append(f"{campo} (no se propone)")
                continue
            ver = c.get("verificacion") or {}
            hecho = c.get("tipo") == "hecho" and es_hecho(campo)
            texto = es_texto(campo)
            salto = salto_grande(get_path(an, campo), c.get("valor")) if texto else None
            if salto:
                c["espera_usuario"] = f"Cambio grande de puntuación: {salto}"
                criterio.append(c)
            elif hecho or texto:
                if ver.get("ok") is True:
                    antes = copy.deepcopy(get_path(an, campo))
                    if json.dumps(antes, sort_keys=True, ensure_ascii=False) == json.dumps(c.get("valor"), sort_keys=True, ensure_ascii=False):
                        continue
                    set_path(an, campo, copy.deepcopy(c.get("valor")))
                    anotar(campo, antes, c.get("valor"), c)
                    res["aplicados"].append(campo)
                    cambiado = True
                else:
                    c["fallo_verificacion"] = ver.get("nota") or "Sin verificar"
                    quedan_hoy.append(c)
                    res["fallos"].append(f"{campo}: {c['fallo_verificacion']}")
            else:
                criterio.append(c)

        imp = impacto(t, criterio)
        urgente = bool(prop.get("urgente")) or (imp is not None and abs(imp) >= UMBRAL_GRAVE)
        for c in criterio:
            if c["campo"].startswith("v.") and imp is not None and abs(imp) < UMBRAL_DCF:
                res["descartados"].append(f"{c['campo']} (mueve el valor {imp:+.1f} %, menos del {UMBRAL_DCF:.0f} %)")
                continue
            (quedan_hoy if urgente else a_cola).append(c)
        if imp is not None:
            res["impacto_dcf"] = imp

        for c in quedan_hoy:
            c["procesado"] = hoy
        res["hoy"] = [c["campo"] for c in quedan_hoy]
        res["cola"] = [c["campo"] for c in a_cola]

        base = {k: v for k, v in prop.items() if k not in ("cambios", "urgente")}
        if a_cola:
            cola = fusionar(cola, dict(base, cambios=a_cola), hoy)
        prop = dict(base, cambios=previos + quedan_hoy) if (previos or quedan_hoy) else None
        if prop and quedan_hoy:
            prop["creada"] = hoy

    # Sábado: la cola semanal pasa a la propuesta
    if sabado and cola and cola.get("cambios"):
        for c in cola["cambios"]:
            c["procesado"] = hoy
        cola.setdefault("motivo", "Revisión semanal de criterio")
        cola["motivo"] = "Revisión semanal: " + cola["motivo"] if not cola["motivo"].startswith("Revisión semanal") else cola["motivo"]
        prop = fusionar(prop, cola, hoy)
        res["publicada_cola"] = len(cola["cambios"])
        cola = None

    if cambiado:
        an["cambios_auto"] = registro[-MAX_REGISTRO:]
        if not an["cambios_auto"]:
            an.pop("cambios_auto")
        wr(pa, an)
    pp, pc = PROP / f"{t}.json", COLA / f"{t}.json"
    if prop:
        wr(pp, prop)
    elif pp.exists():
        pp.unlink()
    if cola and cola.get("cambios"):
        wr(pc, cola)
    elif pc.exists():
        pc.unlink()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--todas", action="store_true")
    ap.add_argument("--sabado", action="store_true", help="publica la cola semanal en las propuestas")
    ap.add_argument("--hoy", help="fecha AAAA-MM-DD (por defecto, hoy en Madrid)")
    a = ap.parse_args()
    hoy = a.hoy or datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
    cos = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
    cos = cos if isinstance(cos, list) else next(v for v in cos.values() if isinstance(v, list))
    ts = [c["ticker"].upper() for c in cos] if a.todas else [t.upper() for t in a.tickers]
    if not ts:
        ap.error("indica un ticker o --todas")
    out = [procesar(t, hoy, a.sabado) for t in ts]
    out = [r for r in out if any(r[k] for k in ("aplicados", "fallos", "cola", "hoy", "descartados", "avisos", "caducados")) or r.get("publicada_cola")]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
