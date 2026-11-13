"""Registro diario de fuentes de noticias: qué ha traído cada una, para revisarlo semana a semana.

Añade una entrada con la fecha de hoy al principio de propuestas/registro_fuentes.md (la más reciente
arriba). Lo ejecuta la tarea programada de la mañana al terminar, con lo que ha leído en Gmail.

    python scripts/registro_fuentes.py \
        --gmail "Bloomberg=3,Investing=1,FT=0,Reuters=0,CNBC=0" \
        --gmail-companias "AMZN=1,ORCL=2" \
        --nota "Primera prueba completa"

Lee de data/<T>.json: noticias_fuentes.proveedores (estado de cada fuente en la última
actualización), noticias (titulares de las últimas 24 h por vía) y redes (StockTwits, Reddit).
Las señales salen de scripts/senales.py.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
REGISTRO = ROOT / "propuestas" / "registro_fuentes.md"
CABECERA = ("# Registro de fuentes de noticias\n\n"
            "Una entrada por día (la más reciente arriba). La escribe la tarea programada de la mañana con "
            "`python scripts/registro_fuentes.py`. Sirve para ver qué aporta cada fuente y decidir qué quitar o añadir.\n")
VIAS = [("Finnhub", "Finnhub"), ("Google News", "Google News"), ("Seeking Alpha", "RSS de Seeking Alpha"),
        ("Marketaux", "Marketaux"), ("Medios sectoriales y agencias", "RSS del medio")]


def kv(s: str | None) -> dict:
    out = {}
    for par in (s or "").split(","):
        if "=" in par:
            k, v = par.split("=", 1)
            try:
                out[k.strip()] = int(v)
            except ValueError:
                out[k.strip()] = v.strip()
    return out


def companias() -> list[str]:
    cos = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
    cos = cos if isinstance(cos, list) else next(v for v in cos.values() if isinstance(v, list))
    return [c["ticker"] for c in cos]


def entrada(hoy, gmail: dict, gmail_cos: dict, nota: str | None) -> str:
    desde = (hoy - timedelta(days=1)).isoformat()
    filas, totales, caidas = [], collections.Counter(), collections.Counter()
    for t in companias():
        p = ROOT / "data" / f"{t}.json"
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        recientes = [n for n in d.get("noticias") or [] if (n.get("fecha") or "") >= desde]
        por_via = collections.Counter(n.get("via") or ("SEC" if n.get("oficial") else "?") for n in recientes)
        prov = (d.get("noticias_fuentes") or {}).get("proveedores") or {}
        for nombre, e in prov.items():
            if not e.get("ok"):
                caidas[nombre] += 1
        redes = d.get("redes") or {}
        st, rd = redes.get("stocktwits") or {}, redes.get("reddit") or {}
        celdas = [str(por_via.get(v, 0)) for _, v in VIAS]
        for (n, v) in VIAS:
            totales[n] += por_via.get(v, 0)
        stt = f"{st['pct_alcista']} % alc." if st.get("pct_alcista") is not None else ("sin etiquetas" if st else "—")
        rdd = f"{rd.get('publicaciones_7d', 0)} publ." if rd else "—"
        filas.append(f"| {t} | {len(recientes)} | " + " | ".join(celdas) + f" | {stt} | {rdd} | {gmail_cos.get(t, 0)} |")
    # señales
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import senales as S
        sen = [r for r in S.calcular(hoy) if r["revisar"]]
        sen_txt = "; ".join(f"{r['ticker']} ({', '.join(r['senales'])})" for r in sen) or "ninguna"
    except Exception as e:  # noqa: BLE001
        sen_txt = f"no se pudo calcular ({type(e).__name__})"
    gm = ", ".join(f"{k} {v}" for k, v in gmail.items()) if gmail else "no se consultó"
    lines = [f"## {hoy.isoformat()}", ""]
    if nota:
        lines += [f"_{nota}_", ""]
    lines += [f"- **Alertas en Gmail** (infomercados.gbx@gmail.com, últimas 24 h): {gm}.",
              f"- **Titulares nuevos en 24 h (todas las compañías):** " + ", ".join(f"{n} {totales[n]}" for n, _ in VIAS) + ".",
              f"- **Fuentes con fallo** (nº de compañías): " + (", ".join(f"{k} {v}" for k, v in caidas.items()) or "ninguna") + ".",
              f"- **Compañías con señal para la revisión de internet:** {sen_txt}.",
              "",
              "| Compañía | Titulares 24 h | " + " | ".join(n for n, _ in VIAS) + " | StockTwits | Reddit 7 d | Alertas Gmail |",
              "|---|---:|" + "---:|" * len(VIAS) + "---|---|---:|",
              *filas, ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gmail", help="alertas leídas por medio, p. ej. «Bloomberg=3,Investing=1»")
    ap.add_argument("--gmail-companias", help="alertas que nombran a cada compañía, p. ej. «AMZN=1»")
    ap.add_argument("--nota")
    ap.add_argument("--hoy", help="AAAA-MM-DD (para pruebas)")
    ap.add_argument("--imprimir", action="store_true", help="solo imprime la entrada, sin guardarla")
    a = ap.parse_args()
    hoy = datetime.strptime(a.hoy, "%Y-%m-%d").date() if a.hoy else datetime.now(ZoneInfo("Europe/Madrid")).date()
    e = entrada(hoy, kv(a.gmail), kv(a.gmail_companias), a.nota)
    if a.imprimir:
        print(e)
        return 0
    previo = REGISTRO.read_text(encoding="utf-8") if REGISTRO.exists() else CABECERA
    cuerpo = previo[len(CABECERA):] if previo.startswith(CABECERA) else previo
    marca = f"## {hoy.isoformat()}\n"
    if marca in cuerpo:                       # la entrada de hoy se sustituye, no se duplica
        i = cuerpo.index(marca)
        j = cuerpo.find("\n## ", i + 1)
        cuerpo = cuerpo[:i] + cuerpo[j + 1:] if j != -1 else cuerpo[:i]
    REGISTRO.write_text(CABECERA + "\n" + e + "\n" + cuerpo.lstrip("\n"), encoding="utf-8")
    print(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
