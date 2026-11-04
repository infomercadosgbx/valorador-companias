"""Genera el PDF de cada informe de resultados que haya cambiado.

  python scripts/pdf_resultados.py --pendientes   # solo cuenta (sale 0 si no hay nada que hacer, 3 si hay)
  python scripts/pdf_resultados.py                # genera los que falten o hayan cambiado

Sirve el repositorio en local, abre resultados.html?t=<T>&p=<periodo>&pdf=1 con
Chromium (Playwright) y lo imprime en A4. Cada PDF lleva en el índice la huella
del JSON del que sale («pdf_de»): solo se regenera si el informe cambió, así el
repositorio no acumula PDF iguales.
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "resultados"


def huella(path: Path) -> str:
    """Huella del informe sin los campos internos que no se ven en el PDF."""
    obj = json.loads(path.read_text(encoding="utf-8"))
    for k in ("_calendario_finnhub", "_cifras_nota", "generado"):
        obj.pop(k, None)
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def pendientes():
    out = []
    for idx_path in sorted(BASE.glob("*/index.json")):
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        for it in idx.get("informes") or []:
            js = idx_path.parent / it["json"]
            if not js.exists():
                continue
            h = huella(js)
            if it.get("pdf_de") != h or not (idx_path.parent / f"{it['periodo']}.pdf").exists():
                out.append((idx_path, it["periodo"], h))
    return out


def main(argv):
    todo = pendientes()
    if "--pendientes" in argv:
        print(f"Informes de resultados sin PDF actualizado: {len(todo)}")
        for p, per, _ in todo:
            print(f"  {p.parent.name} {per}")
        return 3 if todo else 0
    if not todo:
        print("Todos los PDF están al día.")
        return 0
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hechos, fallos = 0, []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for idx_path, per, h in todo:
            t = idx_path.parent.name
            try:
                page.goto(f"http://127.0.0.1:{port}/resultados.html?t={t}&p={per}&pdf=1", wait_until="networkidle")
                page.wait_for_function("window.__listo === true", timeout=30000)
                page.emulate_media(media="print")
                out = idx_path.parent / f"{per}.pdf"
                page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
                idx = json.loads(idx_path.read_text(encoding="utf-8"))
                for it in idx.get("informes") or []:
                    if it["periodo"] == per:
                        it["pdf"], it["pdf_de"] = out.name, h
                idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                hechos += 1
                print(f"✓ {t} {per}: {out.stat().st_size // 1024} KB")
            except Exception as e:  # noqa: BLE001  un PDF que falla no frena los demás
                fallos.append(f"{t} {per}: {e}")
                print(f"✗ {t} {per}: {e}", file=sys.stderr)
        browser.close()
    srv.shutdown()
    print(f"PDF generados: {hechos}; fallos: {len(fallos)}")
    return 1 if fallos and not hechos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
