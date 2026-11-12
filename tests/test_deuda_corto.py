"""Deuda a corto (pólizas, papel comercial) sumada a la deuda a largo.

Caso real: Vistra a 31-dic-25 tenía LongTermDebt 17.043 M (incluye vencimientos
corrientes) y ShortTermBorrowings 1.800 M, que el robot no sumaba.
"""
from datetime import date

from fetcher import extract as E


def _f(val, end, filed="2026-02-27", form="10-K", accn="0001692819-26-000006"):
    return {"val": val, "end": end, "filed": filed, "form": form, "accn": accn, "fy": 2025, "fp": "FY"}


def _cf(**tags):
    return {"cik": 1692819, "facts": {"us-gaap": {t: {"units": {"USD": v}} for t, v in tags.items()}}}


def test_suma_deuda_a_corto_si_existe():
    cf = _cf(LongTermDebt=[_f(17_043e6, "2025-12-31")], ShortTermBorrowings=[_f(1_800e6, "2025-12-31")])
    r, w = E.build_instant(cf, 1692819, "deuda", date(2025, 12, 31))
    assert r["ultimo"]["valor"] == 18_843e6
    assert "ShortTermBorrowings" in r["ultimo"]["etiqueta"]


def test_sin_deuda_a_corto_no_avisa():
    cf = _cf(LongTermDebt=[_f(21_146e6, "2026-09-30")], ShortTermBorrowings=[_f(1_800e6, "2025-12-31")])
    r, w = E.build_instant(cf, 1692819, "deuda", date(2026, 9, 30))
    assert r["ultimo"]["valor"] == 21_146e6
    assert not any(x["codigo"] == "componente_no_etiquetado" for x in w)


def test_no_duplica_si_ya_usa_debtcurrent():
    cf = _cf(LongTermDebtNoncurrent=[_f(10_000e6, "2026-09-30")], DebtCurrent=[_f(500e6, "2026-09-30")],
             ShortTermBorrowings=[_f(300e6, "2026-09-30")])
    r, w = E.build_instant(cf, 1, "deuda", date(2026, 9, 30))
    assert r["ultimo"]["valor"] == 10_500e6
