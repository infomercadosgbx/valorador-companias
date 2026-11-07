"""Avisos que piden acción, para enviarlos como Issue de GitHub (llega por email).

  python -m fetcher.alerts --out avisos.md

Compara los datos recién descargados con los del último commit (git HEAD) y con
el estado guardado en data/_avisos_estado.json, para no repetir avisos:
  - la cotización entra en tu zona de compra («comprar por debajo de»);
  - la compañía presenta un 10-Q/10-K o el 8-K de resultados;
  - un directivo o consejero compra acciones en mercado;
  - movimiento fuerte de la cotización en el día (±8%);
  - resultados en los próximos 2 días;
  - tu análisis tiene más de 90 días;
  - un seguimiento (seguimientos.json) encuentra una novedad en un 8-K/10-Q/10-K o en las noticias.
Si no hay nada nuevo no escribe el archivo y el workflow no abre ningún Issue.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

from .main import ROOT, load_companies

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
STATE = "data/_avisos_estado.json"
MOVE = 8.0
STALE_DAYS = 90


def fecha(iso):
    try:
        d = date.fromisoformat(iso[:10])
        return f"{d.day}-{MESES[d.month - 1]}-{str(d.year)[2:]}"
    except (TypeError, ValueError):
        return iso or ""


def parse_es(t):
    t = str(t or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{1,2})[\s\-/]+([a-záéíóú]{3,})[a-z]*[\s\-/]+(\d{2,4})", t, re.I)
    if not m or m[2][:3].lower() not in MESES:
        return None
    y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
    try:
        return date(y, MESES.index(m[2][:3].lower()) + 1, int(m[1]))
    except ValueError:
        return None


def git_json(root, rel):
    try:
        out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root, capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return None


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def usd(v):
    if v is None:
        return "–"
    if abs(v) >= 1e9:
        return f"{v / 1e9:,.2f} mil M USD".replace(",", "X").replace(".", ",").replace("X", ".")
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.1f} M USD".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{v:,.0f} USD".replace(",", ".")


def num(v, d=2):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def company_alerts(c, data, prev, analysis, state, today):
    t, name = c["ticker"].upper(), c["nombre"]
    out = []
    P = data.get("precio") or {}
    price = P.get("valor")
    # 1. zona de compra (con margen del 3% para no avisar cada vez que roza el umbral)
    bb = ((analysis or {}).get("verdict") or {}).get("buyBelow")
    k = f"{t}:zona_compra"
    if isinstance(bb, (int, float)) and bb > 0 and price:
        if price <= bb and not state.get(k):
            out.append(("🟢", f"**{name} ({t}) entra en tu zona de compra**: cotiza a {num(price)} USD y tu precio de compra es {num(bb)} USD."))
            state[k] = today.isoformat()
        elif price > bb * 1.03 and state.get(k):
            state.pop(k, None)
    # 2. informes nuevos
    for key, label in (("ultimo_8k_resultados", "resultados (8-K)"), ("ultimo_informe", None)):
        new, old = data.get(key) or {}, (prev or {}).get(key) or {}
        if new.get("accn") and old.get("accn") and new["accn"] != old["accn"]:
            lab = label or new.get("formulario", "informe")
            link = new.get("url_ex99_1") or new.get("url_documento") or new.get("url_indice")
            out.append(("📄", f"**{name} ({t}) ha presentado {lab}** el {fecha(new.get('fecha_presentacion'))}"
                               f"{f' · [ver documento]({link})' if link else ''}. Revisa la tesis y los supuestos."))
    # 3. compras de directivos en mercado
    seen = {(o.get("persona"), o.get("fecha"), o.get("acciones")) for o in ((prev or {}).get("directivos") or {}).get("operaciones") or []}
    for o in ((data.get("directivos") or {}).get("operaciones") or []):
        if o.get("codigo") == "P" and (o.get("persona"), o.get("fecha"), o.get("acciones")) not in seen and (prev or {}).get("directivos") is not None:
            out.append(("👤", f"**Compra de un directivo en {name} ({t})**: {o.get('persona')} ({o.get('cargo') or 'insider'}) compró "
                               f"{num(o.get('acciones') or 0, 0)} acciones a {num(o.get('precio') or 0)} USD ({usd(o.get('importe'))}) el {fecha(o.get('fecha'))}"
                               + (f" · [formulario 4]({o['url']})" if o.get("url") else "") + "."))
    # 4. movimiento fuerte
    pc = P.get("cierre_anterior")
    if price and pc:
        mv = (price / pc - 1) * 100
        k = f"{t}:movimiento:{P.get('fecha')}"
        if abs(mv) >= MOVE and not state.get(k):
            out.append(("📉" if mv < 0 else "📈", f"**{name} ({t}) se ha movido un {'+' if mv > 0 else '−'}{num(abs(mv), 1)}%** en la sesión del {fecha(P.get('fecha'))} (cierre {num(price)} USD)."))
            state[k] = today.isoformat()
    # 5. resultados inminentes
    E = ((data.get("resultados_previstos") or {}).get("proximos") or {})
    if E.get("fecha"):
        try:
            d = (date.fromisoformat(E["fecha"]) - today).days
        except ValueError:
            d = None
        k = f"{t}:proximos:{E['fecha']}"
        if d is not None and 0 <= d <= 2 and not state.get(k):
            cuando = "hoy" if d == 0 else "mañana" if d == 1 else "pasado mañana"
            est = f" Previsión: BPA {num(E['bpa_estimado'])} USD" if E.get("bpa_estimado") is not None else ""
            out.append(("🗓️", f"**{name} ({t}) presenta resultados {cuando}** ({fecha(E['fecha'])}{', ' + E['hora'] if E.get('hora') else ''}).{est}"))
            state[k] = today.isoformat()
    # 6. análisis antiguo
    as_of = parse_es(((analysis or {}).get("meta") or {}).get("asOf"))
    if as_of and (today - as_of).days > STALE_DAYS:
        k = f"{t}:antiguo:{as_of.isoformat()}"
        if not state.get(k):
            out.append(("⏱️", f"**Tu análisis de {name} ({t}) tiene {(today - as_of).days} días** (del {fecha(as_of.isoformat())}). Toca revisarlo."))
            state[k] = today.isoformat()
    # 7. seguimientos: cada hallazgo nuevo (oficial siempre; prensa solo con señal)
    SEN = {"cierre": ("✅", "posible cierre definitivo"), "cancelacion": ("⛔", "posible cancelación"),
           "riesgo": ("⚠️", "señal de riesgo"), "mencion": ("🔎", "nueva mención")}
    for sg in data.get("seguimientos") or []:
        for h in sg.get("hallazgos") or []:
            if h.get("senal") == "mencion" and not h.get("oficial"):
                continue
            if (h.get("detectado") or "") < (today - timedelta(days=7)).isoformat():
                continue   # ya avisado (o anterior al seguimiento); evita repetir al limpiar el estado
            k = f"{t}:seguimiento:{sg.get('id')}:{h.get('accn') or h.get('url')}:{h.get('senal')}"
            if state.get(k):
                continue
            e, lab = SEN.get(h.get("senal"), SEN["mencion"])
            txt = (h.get("texto") or "")[:400]
            out.append((e, f"**{name} ({t}) · {sg.get('titulo')}: {lab}** en {h.get('fuente')} del {fecha(h.get('fecha'))}"
                           + (f" · [ver documento]({h['url']})" if h.get("url") else "") + f".\n\n> {txt}"))
            state[k] = today.isoformat()
    return out


def run(root=ROOT, out=None, today=None, owner=None, site=None):
    today = today or date.today()
    state = read(root / STATE) or {}
    lines = []
    for c in load_companies(root):
        t = c["ticker"].upper()
        data = read(root / "data" / f"{t}.json")
        if not data:
            continue
        prev = git_json(root, f"data/{t}.json")
        analysis = read(root / "analysis" / f"{t}.json")
        lines += company_alerts(c, data, prev, analysis, state, today)
        prop = read(root / "propuestas" / f"{t}.json")
        if prop and prop.get("cambios"):
            k = f"{t}:propuesta:{prop.get('creada')}|{prop.get('informe_accn', '')}" + (f"|{prop['alcance']}" if prop.get("alcance") else "")
            if not state.get(k):
                lines.append(("📝", f"**Propuesta de actualización de {c['nombre']} ({t})**: {prop.get('motivo', '')} · "
                                    f"{len(prop['cambios'])} cambios para revisar en la web."))
                state[k] = today.isoformat()
    # limpia estados de más de 120 días
    for k in [k for k, v in state.items() if isinstance(v, str) and len(v) == 10 and (today - date.fromisoformat(v)).days > 120
              and ":zona_compra" not in k]:
        state.pop(k)
    (root / STATE).write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if not lines or not out:
        return lines
    body = [f"{e} {txt}" for e, txt in lines]
    foot = []
    if site:
        foot.append(f"Abre el valorador: {site}")
    if owner:
        foot.append(f"@{owner}")
    Path(out).write_text("\n\n".join(body) + ("\n\n---\n" + " · ".join(foot) if foot else "") + "\n", encoding="utf-8")
    return lines


def main(argv=None):
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or (repo.split("/")[0] if repo else None)
    site = f"https://{owner}.github.io/{repo.split('/')[1]}/valorador.html#seguimiento" if "/" in repo else None
    lines = run(out=a.out, owner=owner, site=site)
    print(f"Avisos nuevos: {len(lines)}")
    for e, t in lines:
        print(" ", e, t)


if __name__ == "__main__":
    main()
