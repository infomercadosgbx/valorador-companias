"""Logos y perfil de la compañía desde la API oficial de Finnhub (/stock/profile2).

El logo se guarda en /logos/<TICKER>.<ext> y solo se reescribe si cambia.
Si companies.json trae "logo" (ruta propia), se respeta y no se descarga nada.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

MAX_BYTES = 600_000
MAGIC = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif", b"RIFF": "webp"}


def _kind(data: bytes):
    for sig, ext in MAGIC.items():
        if data.startswith(sig):
            return ext
    head = data[:300].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:1000].lower()):
        return "svg"
    return None


def update(provider, company, root: Path, opener=None):
    """Devuelve (perfil|None, cambiado: bool)."""
    t = company["ticker"].upper()
    if company.get("logo"):
        return {"logo": company["logo"], "logo_fuente": "companies.json"}, False
    getp = getattr(provider, "profile", None)
    if not getp:
        return None, False
    try:
        p = getp(t) or {}
    except Exception:  # noqa: BLE001  el perfil es secundario
        return None, False
    perfil = {k2: p.get(k1) for k1, k2 in (("finnhubIndustry", "industria"), ("weburl", "web"),
                                           ("country", "pais"), ("ipo", "salida_bolsa"), ("exchange", "mercado"))
              if p.get(k1)}
    url = p.get("logo")
    changed = False
    if url:
        try:
            op = opener or urllib.request.urlopen
            with op(urllib.request.Request(url, headers={"User-Agent": "valorador"}), timeout=30) as r:
                data = r.read(MAX_BYTES + 1)
            ext = _kind(data) if len(data) <= MAX_BYTES else None
            if ext:
                folder = root / "logos"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{t}.{ext}"
                for old in folder.glob(f"{t}.*"):
                    if old != path:
                        old.unlink()
                        changed = True
                if not path.exists() or path.read_bytes() != data:
                    path.write_bytes(data)
                    changed = True
                perfil.update({"logo": f"logos/{t}.{ext}", "logo_fuente": "Finnhub (perfil de la compañía)"})
        except Exception:  # noqa: BLE001
            pass
    if not perfil.get("logo"):
        old = sorted((root / "logos").glob(f"{t}.*")) if (root / "logos").exists() else []
        if old:
            perfil.update({"logo": f"logos/{old[0].name}", "logo_fuente": "Finnhub (perfil de la compañía)"})
    return perfil or None, changed
