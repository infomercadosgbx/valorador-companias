"""Cliente HTTP para la SEC con límite de ritmo y reintentos.

- Cabecera User-Agent obligatoria con el formato «Nombre email» (política de la SEC).
- Máximo 5 peticiones por segundo en total (la SEC permite 10; vamos a la mitad).
- Reintentos con espera exponencial ante 429, 5xx y errores de red.
- Solo usa la biblioteca estándar de Python.
"""
from __future__ import annotations

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.request

MAX_RPS = 5
RETRIES = 5
BACKOFF_BASE = 1.5  # segundos: 1.5, 3, 6, 12, 24


class SecError(RuntimeError):
    pass


class SecClient:
    def __init__(self, user_agent: str | None = None, max_rps: float = MAX_RPS,
                 retries: int = RETRIES, sleep=time.sleep, opener=None):
        ua = (user_agent or os.environ.get("SEC_USER_AGENT", "")).strip()
        if not ua or "@" not in ua or " " not in ua:
            raise SecError(
                "Falta SEC_USER_AGENT con el formato «Nombre email» "
                "(por ejemplo «Ana Pérez ana@ejemplo.com»). Ver README, paso 2.")
        self.user_agent = ua
        self.min_interval = 1.0 / max_rps
        self.retries = retries
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last = 0.0
        self._open = opener or urllib.request.urlopen
        self.requests_made = 0

    def _throttle(self):
        with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()

    def get_bytes(self, url: str) -> bytes | None:
        """Devuelve el cuerpo, o None si la SEC responde 404."""
        last_err = None
        for attempt in range(self.retries):
            self._throttle()
            req = urllib.request.Request(url, headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            })
            try:
                with self._open(req, timeout=60) as resp:
                    self.requests_made += 1
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except urllib.error.HTTPError as e:
                self.requests_made += 1
                if e.code == 404:
                    return None
                # 403 suele indicar ritmo excesivo o User-Agent rechazado: se reintenta.
                if e.code not in (403, 429, 500, 502, 503, 504):
                    raise SecError(f"HTTP {e.code} en {url}") from e
                last_err = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = e
            self._sleep(BACKOFF_BASE * (2 ** attempt))
        raise SecError(f"Sin respuesta de la SEC tras {self.retries} intentos: {url} ({last_err})")

    def get_json(self, url: str):
        body = self.get_bytes(url)
        return None if body is None else json.loads(body)

    def get_text(self, url: str) -> str | None:
        body = self.get_bytes(url)
        return None if body is None else body.decode("utf-8", errors="replace")

    # Atajos
    def companyfacts(self, cik: str):
        return self.get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_10(cik)}.json")

    def submissions(self, cik: str):
        return self.get_json(f"https://data.sec.gov/submissions/CIK{cik_10(cik)}.json")

    def company_tickers(self):
        return self.get_json("https://www.sec.gov/files/company_tickers.json")


def cik_10(cik) -> str:
    return str(int(str(cik))).zfill(10)
