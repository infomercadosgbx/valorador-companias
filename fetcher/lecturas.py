"""Lecturas: copia en texto de los documentos oficiales que lee la tarea de la mañana.

La tarea programada de análisis corre en un entorno sin nadie delante y su lector web
(WebFetch) no puede abrir direcciones que no hayan salido antes en una búsqueda: sec.gov
y las webs oficiales de las compañías fallaban casi siempre. Por eso el robot nocturno
(GitHub Actions, que sí puede descargarlas) deja aquí el texto de:

- SEC: la última nota de resultados (8-K, Exhibit 99.1), el último 10-Q/10-K y los
  8-K y otras presentaciones de los últimos días (`data/<T>.json`).
- Webs oficiales (`companies.json → webs_oficiales`): texto de la página y sus enlaces
  del mismo dominio (productos, notas de prensa, presentaciones). Si la descarga simple
  falla o trae poco texto (páginas hechas con JavaScript), se repite con Chromium.

Resultado en `lecturas/<T>/` y el estado de cada descarga en `lecturas/_estado.json`
(ok, código HTTP, tamaño, fecha). Los documentos de la SEC no cambian: se descargan una
vez por número de registro (accn) y se borran cuando dejan de ser los últimos. Las webs se
reescriben solo si cambia su texto.

Uso: python -m fetcher.lecturas [--only T1 T2] [--root .]
"""
from __future__ import annotations

import argparse
import hashlib
import html as _html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DIAS_VENTANA = 10              # 8-K y presentaciones recientes que se copian
MAX_SEC = 900_000              # caracteres por documento de la SEC (un 10-K cabe entero)
MAX_WEB = 120_000              # caracteres por página web
MAX_ENLACES = 120
POCO_TEXTO = 800               # menos que esto: página que se monta con JavaScript
UA_WEB = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0 Safari/537.36 valorador-companias")

_BLOQUE = re.compile(r"(?i)</?(p|div|br|li|tr|h[1-6]|table|section|article|ul|ol|header|footer|title)\b[^>]*>")


def html_a_texto(raw: str) -> str:
    """HTML (también iXBRL de la SEC) a texto legible con saltos de línea."""
    t = raw or ""
    t = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", t)          # datos XBRL ocultos
    t = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?is)<div[^>]*display:\s*none[^>]*>.*?</div>", " ", t)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = _BLOQUE.sub("\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ").replace("​", "")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    lineas = [ln.strip() for ln in t.split("\n")]
    out, vacia = [], False
    for ln in lineas:
        if not ln:
            if not vacia and out:
                out.append("")
            vacia = True
            continue
        out.append(ln)
        vacia = False
    return "\n".join(out).strip()


def enlaces(raw: str, base: str) -> list[dict]:
    """Enlaces del mismo dominio (sin anclas ni duplicados), con su texto."""
    dom = urllib.parse.urlparse(base).netloc.lower().removeprefix("www.")
    vistos, res = set(), []
    for m in re.finditer(r'(?is)<a\b[^>]*href\s*=\s*["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', raw or ""):
        href = urllib.parse.urljoin(base, _html.unescape(m.group(1)).strip())
        p = urllib.parse.urlparse(href)
        if p.scheme not in ("http", "https"):
            continue
        d = p.netloc.lower().removeprefix("www.")
        if not (d == dom or d.endswith("." + dom) or dom.endswith("." + d)):
            continue
        texto = re.sub(r"\s+", " ", html_a_texto(m.group(2))).strip()
        if not texto or href in vistos:
            continue
        vistos.add(href)
        res.append({"t": texto[:140], "u": href})
        if len(res) >= MAX_ENLACES:
            break
    return res


def slug(s: str) -> str:
    s = urllib.parse.urlparse(s).netloc + urllib.parse.urlparse(s).path if "://" in s else s
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "web"


def _cabecera(**kw) -> str:
    return "\n".join(f"# {k}: {v}" for k, v in kw.items() if v not in (None, "")) + "\n\n"


def activas(root: Path, only=None) -> list[dict]:
    cj = json.loads((root / "companies.json").read_text(encoding="utf-8"))
    cs = cj["companies"] if isinstance(cj, dict) else cj
    res = [c for c in cs if not c.get("archivada")]
    if only:
        res = [c for c in res if c["ticker"] in set(only)]
    return res


def documentos_sec(d: dict, hoy: date) -> list[dict]:
    """Qué documentos de la SEC copiar para una compañía (sin descargar nada)."""
    docs = []
    r = d.get("ultimo_8k_resultados") or {}
    if r.get("url_ex99_1") and r.get("accn"):
        docs.append({"tipo": "nota_resultados", "accn": r["accn"], "u": r["url_ex99_1"],
                     "fecha": r.get("fecha_presentacion") or r.get("fecha"), "t": "Nota de resultados (8-K, Ex. 99.1)"})
    i = d.get("ultimo_informe") or {}
    if i.get("url_documento") and i.get("accn"):
        docs.append({"tipo": re.sub(r"[^a-z0-9]+", "", (i.get("formulario") or "informe").lower()), "accn": i["accn"],
                     "u": i["url_documento"], "fecha": i.get("fecha_presentacion") or i.get("fecha"),
                     "t": f"{i.get('formulario') or 'Informe'} (último informe periódico)"})
    desde = (hoy - timedelta(days=DIAS_VENTANA)).isoformat()
    for n in d.get("noticias") or []:
        if "SEC" in str(n.get("medio")) and "8-K" in str(n.get("medio")) and (n.get("fecha") or "") >= desde:
            u = n.get("url") or ""
            m = re.search(r"/(\d{18})/", u)
            accn = (f"{m.group(1)[:10]}-{m.group(1)[10:12]}-{m.group(1)[12:]}" if m else hashlib.sha1(u.encode()).hexdigest()[:12])
            if u and accn != r.get("accn"):
                docs.append({"tipo": "8k", "accn": accn, "u": u, "fecha": n.get("fecha"),
                             "t": n.get("titular") or "8-K"})
    for p in d.get("presentaciones_sec") or []:
        if (p.get("fecha_presentacion") or "") >= desde and p.get("url_documento") and p.get("accn"):
            if str(p.get("formulario")) in ("4", "144"):
                continue
            docs.append({"tipo": re.sub(r"[^a-z0-9]+", "", str(p.get("formulario")).lower()) or "sec",
                         "accn": p["accn"], "u": p["url_documento"], "fecha": p.get("fecha_presentacion"),
                         "t": f"{p.get('formulario')}: {p.get('descripcion') or ''}".strip()})
    vistos, unicos = set(), []
    for x in docs:
        k = (x["tipo"], x["accn"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(x)
    return unicos


def _web_get(url: str, opener=urllib.request.urlopen) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA_WEB, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                                               "Accept-Language": "en-US,en;q=0.9,es;q=0.8"})
    try:
        with opener(req, timeout=40) as r:
            raw = r.read(4_000_000)
            cs = r.headers.get_content_charset() or "utf-8"
            return getattr(r, "status", 200), raw.decode(cs, "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # red, TLS, tiempo de espera
        return 0, f"{type(e).__name__}: {e}"


class Navegador:
    """Segundo intento con un navegador de verdad (Chromium vía Playwright) para las webs que
    se montan con JavaScript, bloquean a los lectores simples o tardan en responder.
    Se arranca solo si hace falta; si Playwright no está instalado, no hace nada."""

    def __init__(self, log=print):
        self._pw = self._browser = None
        self._ok = None
        self.log = log

    def _arrancar(self) -> bool:
        if self._ok is not None:
            return self._ok
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch(channel="chrome")
            except Exception:  # noqa: BLE001 — sin Chrome del sistema: el Chromium de Playwright
                self._browser = self._pw.chromium.launch()
            self._ok = True
        except Exception as ex:  # noqa: BLE001
            self.log(f"  Navegador no disponible: {ex}")
            self._ok = False
        return self._ok

    def __call__(self, url: str) -> tuple[int, str]:
        if not self._arrancar():
            return 0, "navegador no disponible"
        ctx = self._browser.new_context(user_agent=UA_WEB.replace(" valorador-companias", ""),
                                        locale="en-US", viewport={"width": 1366, "height": 900})
        try:
            page = ctx.new_page()
            r = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:  # noqa: BLE001 — páginas que nunca quedan en silencio
                pass
            page.wait_for_timeout(1_500)
            return (r.status if r else 200), page.content()
        except Exception as ex:  # noqa: BLE001
            return 0, f"{type(ex).__name__}: {ex}"
        finally:
            ctx.close()

    def cerrar(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass


def _escribir_si_cambia(path: Path, cuerpo: str, cabecera: str) -> bool:
    """Escribe cabecera + cuerpo si el cuerpo ha cambiado (la fecha de la cabecera no cuenta)."""
    h = hashlib.sha1(cuerpo.encode()).hexdigest()[:16]
    if path.exists():
        viejo = path.read_text(encoding="utf-8")
        if f"# hash: {h}\n" in viejo:
            return False
    path.write_text(cabecera.rstrip("\n") + f"\n# hash: {h}\n\n" + cuerpo + "\n", encoding="utf-8")
    return True


def actualizar(root: Path, only=None, sec=None, web_get=_web_get, hoy: date | None = None, log=print,
               navegador=None) -> dict:
    hoy = hoy or date.today()
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    base = root / "lecturas"
    base.mkdir(exist_ok=True)
    est_path = base / "_estado.json"
    try:
        estado = json.loads(est_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        estado = {}
    estado["_nota"] = ("Estado de las copias en texto de lecturas/<T>/ (fetcher/lecturas.py). "
                       "ok=false o poco_texto=true: la tarea debe buscar esa fuente por otra vía y decirlo.")
    for c in activas(root, only):
        t = c["ticker"]
        carpeta = base / t
        carpeta.mkdir(exist_ok=True)
        e = estado.setdefault(t, {})
        e["sec"], e_web = [], e.get("web") or {}
        try:
            d = json.loads((root / "data" / f"{t}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            d = {}
        # --- SEC
        conservar = set()
        for doc in documentos_sec(d, hoy):
            nombre = f"sec_{doc['tipo']}_{doc['accn']}.txt"
            conservar.add(nombre)
            p = carpeta / nombre
            item = {"archivo": f"lecturas/{t}/{nombre}", "t": doc["t"], "u": doc["u"], "fecha": doc["fecha"]}
            if p.exists():
                item.update(ok=True, nuevo=False)
                e["sec"].append(item)
                continue
            if sec is None:
                item.update(ok=False, error="sin cliente de la SEC (falta SEC_USER_AGENT)")
                e["sec"].append(item)
                continue
            try:
                raw = sec.get_bytes(doc["u"])
                texto = html_a_texto((raw or b"").decode("utf-8", "replace"))
                if not texto:
                    raise ValueError("documento vacío o no encontrado")
                recortado = len(texto) > MAX_SEC
                p.write_text(_cabecera(fuente=doc["t"], url=doc["u"], presentado=doc["fecha"], accn=doc["accn"],
                                       copiado=ahora, recortado="sí" if recortado else "")
                             + texto[:MAX_SEC] + "\n", encoding="utf-8")
                item.update(ok=True, nuevo=True, caracteres=min(len(texto), MAX_SEC))
                log(f"  {t}: copiado {nombre} ({len(texto):,} caracteres)")
            except Exception as ex:  # noqa: BLE001 — se anota y sigue
                item.update(ok=False, error=f"{type(ex).__name__}: {ex}"[:200])
                log(f"  {t}: no se pudo copiar {doc['u']}: {ex}")
            e["sec"].append(item)
        for viejo in carpeta.glob("sec_*.txt"):
            if viejo.name not in conservar:
                viejo.unlink()
        # --- Webs oficiales
        urls = [w for w in (c.get("webs_oficiales") or []) if isinstance(w, dict) and w.get("u")]
        nuevas_web = {}
        for w in urls:
            u = w["u"]
            nombre = f"web_{slug(u)}.txt"
            codigo, raw = web_get(u)
            via = "http"
            corta = codigo and 200 <= codigo < 300 and raw and len(html_a_texto(raw)) < POCO_TEXTO
            if navegador is not None and (not (codigo and 200 <= codigo < 300 and raw) or corta):
                c2, r2 = navegador(u)
                if c2 and 200 <= c2 < 300 and r2 and len(html_a_texto(r2)) > (len(html_a_texto(raw)) if corta else 0):
                    codigo, raw, via = c2, r2, "navegador"
                elif not corta:
                    log(f"  {t}: web {u} → tampoco con navegador ({c2 or r2[:120]})")
            item = {"archivo": f"lecturas/{t}/{nombre}", "t": w.get("t"), "u": u, "codigo": codigo, "via": via,
                    "revisado": ahora}
            if codigo and 200 <= codigo < 300 and raw:
                texto = html_a_texto(raw)[:MAX_WEB]
                ls = enlaces(raw, u)
                cuerpo = texto + ("\n\n## Enlaces de la página\n" + "\n".join(f"- {x['t']} — {x['u']}" for x in ls) if ls else "")
                cambio = _escribir_si_cambia(carpeta / nombre, cuerpo,
                                             _cabecera(fuente=w.get("t") or u, url=u, copiado=ahora))
                item.update(ok=True, caracteres=len(texto), enlaces=len(ls), poco_texto=len(texto) < POCO_TEXTO,
                            cambio=cambio, ultimo_cambio=ahora if cambio else (e_web.get(u) or {}).get("ultimo_cambio"))
            else:
                item.update(ok=False, error=(raw[:200] if not codigo else f"HTTP {codigo}"),
                            ultimo_ok=(e_web.get(u) or {}).get("revisado") if (e_web.get(u) or {}).get("ok") else (e_web.get(u) or {}).get("ultimo_ok"))
                log(f"  {t}: web {u} → {item['error']}")
            nuevas_web[u] = item
        e["web"] = nuevas_web
        validos = {Path(x["archivo"]).name for x in nuevas_web.values()}
        for viejo in carpeta.glob("web_*.txt"):
            if viejo.name not in validos:
                viejo.unlink()
        e["revisado"] = ahora
    for t in [k for k in estado if not k.startswith("_")]:
        if t not in {c["ticker"] for c in activas(root)}:
            estado.pop(t)   # archivada o retirada: sus copias se quedan, pero no se vigilan
    est_path.write_text(json.dumps(estado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return estado


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--root", default=".")
    ap.add_argument("--sin-navegador", action="store_true", help="no intentar con Chromium las webs que fallan")
    a = ap.parse_args(argv)
    try:
        from fetcher.sec_client import SecClient
        sec = SecClient()
    except Exception as ex:  # noqa: BLE001
        print(f"Sin cliente de la SEC: {ex}", file=sys.stderr)
        sec = None
    nav = None if a.sin_navegador else Navegador()
    try:
        est = actualizar(Path(a.root), a.only, sec=sec, navegador=nav)
    finally:
        if nav:
            nav.cerrar()
    fallos = [(t, x["u"]) for t, e in est.items() if not t.startswith("_")
              for x in list(e.get("sec", [])) + list((e.get("web") or {}).values()) if not x.get("ok")]
    print(f"Lecturas al día. Fuentes que fallan: {len(fallos)}")
    for t, u in fallos:
        print(f"  - {t}: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
