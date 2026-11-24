"""Comprueba la web en un navegador real antes de publicarla.

Abre valorador.html con los archivos del repositorio (sin servidor: el navegador los pide y este script
se los da desde el disco) y, para cada compañía activa de companies.json:

1. La web funciona: ninguna pestaña da error de JavaScript ni se queda en blanco; el Inicio también carga.
2. Los datos llegan a la pantalla tal y como están en los archivos:
   - data/<T>.json: la web ha cargado la última actualización (fecha «generado» y último informe de la SEC),
     el precio de la cabecera es el de ese archivo y la franja dice «Cifras SEC hasta <fecha>».
   - analysis/<T>.json: tus supuestos del DCF (v.*), tu recomendación y el número de veredictos registrados
     son los del archivo.
   - El valor del DCF que muestra la web coincide con el que calcula scripts/impacto_dcf.mjs desde los
     mismos archivos (dos caminos independientes de lectura).
   - Los cambios aplicados automáticamente por el robot (analysis → cambios_auto) aparecen en el registro
     de la pestaña Fuentes.

Uso:  python scripts/comprobar_web.py [--solo VST AMZN] [--chart ruta/chart.umd.js] [--capturas carpeta]
Sale con código 1 y escribe la lista de fallos (también en $GITHUB_STEP_SUMMARY si existe).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://valorador.test/"
TABS = ["resumen", "negocio", "finanzas", "moat", "crecimiento", "directiva", "riesgos", "valoracion", "veredicto", "fuentes"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def nf(v: float, d: int = 0) -> str:
    """Mismo formato que la web: 1.234,56"""
    s = f"{v:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fecha(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{int(d)}-{MESES[int(m) - 1]}-{y[2:]}"


def activas(root: Path) -> list[dict]:
    cj = json.loads((root / "companies.json").read_text(encoding="utf-8"))
    lista = cj if isinstance(cj, list) else cj.get("companies", [])
    return [c for c in lista if not c.get("archivada")]


def dcf_script(root: Path, t: str) -> float | None:
    try:
        r = subprocess.run(["node", str(root / "scripts" / "impacto_dcf.mjs"), t],
                           capture_output=True, text=True, timeout=60, cwd=root)
        return json.loads(r.stdout).get("antes")
    except Exception:  # noqa: BLE001
        return None


def igual(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def comprobar(root: Path, solo=None, chart=None, capturas=None) -> list[str]:
    from playwright.sync_api import sync_playwright

    fallos: list[str] = []
    comps = [c for c in activas(root) if not solo or c["ticker"].upper() in solo]

    def servir(route):
        ruta = route.request.url[len(BASE):].split("#")[0].split("?")[0] or "valorador.html"
        f = (root / ruta).resolve()
        if root in f.parents and f.is_file():
            route.fulfill(path=str(f), content_type=mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        else:
            route.fulfill(status=404, body="")

    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page(viewport={"width": 1300, "height": 900}, locale="es-ES", timezone_id="Europe/Madrid")
        errores: list[str] = []
        pg.on("pageerror", lambda e: errores.append(str(e)[:300]))
        pg.route(BASE + "**", servir)
        pg.route("**/*.workers.dev/**", lambda r: r.abort())          # sin precio en vivo: se compara con data/
        pg.route("https://api.github.com/**", lambda r: r.abort())
        if chart:
            pg.route("https://cdnjs.cloudflare.com/**", lambda r: r.fulfill(path=chart, content_type="application/javascript"))

        def abrir(hash_):
            errores.clear()
            pg.goto(BASE + "valorador.html#" + hash_, wait_until="networkidle")
            pg.reload(wait_until="networkidle")
            pg.wait_for_timeout(600)

        abrir("inicio")
        if errores:
            fallos.append(f"Inicio: error de JavaScript: {errores[0]}")
        if len(pg.inner_text("body")) < 300:
            fallos.append("Inicio: la página sale casi vacía")

        for c in comps:
            t = c["ticker"].upper()
            data = json.loads((root / "data" / f"{t}.json").read_text(encoding="utf-8"))
            an = json.loads((root / "analysis" / f"{t}.json").read_text(encoding="utf-8"))
            if data.get("soportada") is False:
                continue
            for tab in TABS:
                abrir(f"{t}/{tab}")
                actual = pg.evaluate("()=>store.current")
                if actual != t:
                    fallos.append(f"{t}/{tab}: la web abrió {actual} en lugar de {t}")
                    continue
                if errores:
                    fallos.append(f"{t}/{tab}: error de JavaScript: {errores[0]}")
                txt = pg.inner_text("#main")
                if len(txt.strip()) < 150:
                    fallos.append(f"{t}/{tab}: la pestaña sale vacía")
                if "undefined" in txt or "[object Object]" in txt:
                    fallos.append(f"{t}/{tab}: aparece «undefined» u «[object Object]» en pantalla")
                if capturas:
                    Path(capturas).mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(Path(capturas) / f"{t}_{tab}.png"))

                if tab == "resumen":
                    st = pg.evaluate("""()=>({generado:cur._data&&cur._data.generado, accn:cur._data&&cur._data.ultimo_informe&&cur._data.ultimo_informe.accn,
                        price:cur.v.price, v:cur.v, rating:cur.verdict&&cur.verdict.rating, veredictos:(cur.veredictos||[]).length,
                        w:valuation(cur).w, px:(document.querySelector('#priceBox .px')||{}).textContent||'',
                        strip:(document.getElementById('hdrStrip')||{}).textContent||''})""")
                    if st["generado"] != data.get("generado"):
                        fallos.append(f"{t}: la web no muestra la última actualización de data/ ({st['generado']} frente a {data.get('generado')})")
                    if (data.get("ultimo_informe") or {}).get("accn") and st["accn"] != data["ultimo_informe"]["accn"]:
                        fallos.append(f"{t}: el último informe de la SEC en pantalla no es el de data/")
                    pv = (data.get("precio") or {}).get("valor")
                    if pv is not None:
                        if not igual(st["price"], pv):
                            fallos.append(f"{t}: precio en la web {st['price']} frente a {pv} en data/")
                        elif nf(pv, 2) not in st["px"]:
                            fallos.append(f"{t}: la cabecera no enseña el precio {nf(pv, 2)} (muestra «{st['px'].strip()}»)")
                    ref = data.get("referencia_fecha_datos")
                    if ref and f"Cifras SEC hasta {fecha(ref)}" not in st["strip"]:
                        fallos.append(f"{t}: la franja no dice «Cifras SEC hasta {fecha(ref)}»")
                    for k, val in (an.get("v") or {}).items():
                        if k.startswith("_") or k == "comentario":
                            continue
                        if not igual(st["v"].get(k), val):
                            fallos.append(f"{t}: supuesto v.{k} en la web {st['v'].get(k)!r} frente a {val!r} en analysis/")
                    if (an.get("verdict") or {}).get("rating") and st["rating"] != an["verdict"]["rating"]:
                        fallos.append(f"{t}: recomendación en la web {st['rating']!r} frente a {an['verdict']['rating']!r}")
                    if st["veredictos"] != len(an.get("veredictos") or []):
                        fallos.append(f"{t}: {st['veredictos']} veredictos en la web frente a {len(an.get('veredictos') or [])} en analysis/")
                    ref_w = dcf_script(root, t)
                    # La web redondea caja, deuda y acciones de la SEC a millones con un decimal y el script no:
                    # se admite una diferencia de hasta el 0,05 % (unos céntimos por acción).
                    if ref_w is not None and st["w"] is not None and abs(round(st["w"], 2) - ref_w) > max(0.011, abs(ref_w) * 5e-4):
                        fallos.append(f"{t}: valor del DCF en la web {st['w']:.2f} frente a {ref_w:.2f} calculado desde los archivos")

                if tab == "fuentes":
                    n = sum(1 for x in an.get("cambios_auto") or [] if not x.get("deshecho"))
                    if n:
                        card = pg.inner_text("#autoCard") if pg.query_selector("#autoCard") else ""
                        if f"{n} aplicado" not in card:
                            fallos.append(f"{t}: el registro de cambios automáticos no enseña los {n} aplicados de analysis/")
        nav.close()
    return fallos


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--solo", nargs="*", help="Solo estos tickers")
    ap.add_argument("--chart", help="Chart.js local (si no hay acceso a cdnjs)")
    ap.add_argument("--capturas", help="Carpeta donde guardar una captura por pestaña")
    a = ap.parse_args(argv)
    solo = {t.upper() for t in a.solo} if a.solo else None
    fallos = comprobar(ROOT, solo, a.chart, a.capturas)
    n = len([c for c in activas(ROOT) if not solo or c["ticker"].upper() in solo])
    if fallos:
        texto = f"## ❌ La web no ha pasado la comprobación ({len(fallos)} fallos)\n\n" + "\n".join(f"- {f}" for f in fallos)
    else:
        texto = f"## ✅ Web comprobada: {n} compañías × {len(TABS)} pestañas, datos y supuestos en pantalla iguales que en los archivos"
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
