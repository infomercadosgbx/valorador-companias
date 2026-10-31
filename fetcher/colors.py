"""Color de marca a partir del logo (PNG), sin dependencias externas.

Decodifica PNG de 8 bits RGB/RGBA no entrelazados, descarta blancos, negros y
grises, y devuelve el color dominante (cubetas de color) en #RRGGBB.
"""
from __future__ import annotations

import colorsys
import struct
import zlib

PALETTE = ["#2563EB", "#0D9488", "#7C3AED", "#DB2777", "#EA580C", "#16A34A", "#0891B2", "#CA8A04", "#DC2626", "#4F46E5"]


def fallback(ticker: str) -> str:
    return PALETTE[sum(map(ord, ticker.upper())) % len(PALETTE)]


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def decode_png(data: bytes):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, idat, w = 8, b"", None
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or ctype not in (2, 6) or inter:
                return None
            bpp = 3 if ctype == 2 else 4
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if not w:
        return None
    raw = zlib.decompress(idat)
    stride = w * bpp
    prev = bytearray(stride)
    rows, i = [], 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                line[x] = (line[x] + _paeth(a, b, c)) & 255
        rows.append(line)
        prev = line
    return w, h, bpp, rows


def dominant(data: bytes, step=6):
    try:
        img = decode_png(data)
    except Exception:  # noqa: BLE001
        return None
    if not img:
        return None
    w, h, bpp, rows = img
    buckets = {}
    for y in range(0, h, step):
        row = rows[y]
        for x in range(0, w, step):
            r, g, b = row[x * bpp], row[x * bpp + 1], row[x * bpp + 2]
            if bpp == 4 and row[x * bpp + 3] < 128:
                continue
            hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if ss < 0.35 or ll > 0.85 or ll < 0.15:
                continue
            k = int(hh * 24)
            t = buckets.setdefault(k, [0, 0, 0, 0])
            t[0] += r
            t[1] += g
            t[2] += b
            t[3] += 1
    if not buckets:
        return None
    r, g, b, n = max(buckets.values(), key=lambda t: t[3])
    return "#{:02X}{:02X}{:02X}".format(r // n, g // n, b // n)
