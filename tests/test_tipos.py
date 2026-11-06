"""Tipos de interés: calendario del FOMC, decisión de la última reunión y lo que descuenta el mercado."""
from datetime import date

from fetcher import tipos as T
from test_mercado_hoy import Falsas


def test_hora_de_madrid_con_cambios_de_horario():
    assert T.hora_decision("2026-12-09") == "20:00"     # invierno en los dos lados: 6 h
    assert T.hora_decision("2026-03-18") == "19:00"     # EE. UU. ya en verano, España aún no: 5 h
    assert T.hora_decision("2026-10-28") == "19:00"     # España ya en invierno, EE. UU. aún no: 5 h


def test_calendario():
    c = T.calendario(date(2026, 11, 6))
    p = c["proximas"][0]
    assert p["fin"] == "2026-12-09" and p["proyecciones"] and p["dias"] == 33
    assert p["comunicado"].endswith("monetary20261209a.htm") and p["diagrama"].endswith("fomcprojtabl20261209.htm")
    u = c["ultima"]
    assert u["fin"] == "2026-10-28" and "actas" not in u and u["actas_fecha"] == "2026-11-18"
    assert c["ultima_proyeccion"] == "2026-09-16"
    assert "actas" in T.calendario(date(2026, 11, 20))["ultima"]
    # el día de la reunión sigue siendo «próxima»
    assert T.calendario(date(2026, 12, 9))["proximas"][0]["dias"] == 0


def test_decision_y_ultimo_cambio():
    techo = [("2026-09-01", 4.25), ("2026-09-17", 4.0), ("2026-10-29", 4.0), ("2026-10-30", 4.0)]
    reun = {"inicio": "2026-10-27", "fin": "2026-10-28"}
    assert T.decision(techo, reun) == {"pb": 0, "texto": "Mantuvo los tipos"}
    assert T.decision(techo, {"inicio": "2026-09-15", "fin": "2026-09-16"})["texto"] == "Bajó 25 pb"
    assert T.ultimo_cambio(techo) == {"fecha": "2026-09-17", "pb": -25}
    assert T.decision(techo, {"inicio": "2026-12-08", "fin": "2026-12-09"}) is None   # aún sin datos


def test_lectura():
    assert [T.lectura(x) for x in (-40, -10, 0, 14, 30, None)] == ["bajadas", "sin cambios", "sin cambios", "sin cambios", "subidas", None]


class ConTipos(Falsas):
    def __init__(self, fallan=()):
        super().__init__(fallan)
        self.m.update(
            DFEDTARL=[("2026-09-16", 4.0), ("2026-09-17", 3.75), ("2026-11-04", 3.75)],
            DFEDTARU=[("2026-09-16", 4.25), ("2026-09-17", 4.0), ("2026-11-04", 4.0)],
            EFFR=[("2026-11-03", 3.87), ("2026-11-04", 3.88)],
            FEDTARMD=[("2025-01-01", 4.4), ("2026-01-01", 3.9), ("2027-01-01", 3.6), ("2028-01-01", 3.4)],
            FEDTARMDLR=[("2026-09-16", 3.0)])

    def tesoro(self, col):
        self._f("tesoro")
        v = {"3 Mo": 3.95, "6 Mo": 3.90, "1 Yr": 3.70, "2 Yr": 3.55, "10 Yr": 4.83, "5 Yr": 4.62}[col]
        return [("2026-10-05", v - 0.2), ("2026-11-04", v)]


def test_build_tipos():
    out = T.build(ConTipos(), lambda s: ConTipos().fred(s, None), [])
    f = out["fed"]
    assert (f["inferior"], f["superior"], f["efectivo"]["valor"]) == (3.75, 4.0, 3.88)
    assert f["ultimo_cambio"] == {"fecha": "2026-09-17", "pb": -25}
    assert out["calendario"]["ultima"]["decision"]["texto"] == "Mantuvo los tipos"
    assert [a["anio"] for a in out["diagrama"]["anios"]] == [2026, 2027, 2028] and out["diagrama"]["largo_plazo"] == 3.0
    pl = {p["plazo"]: p for p in out["mercado"]["plazos"]}
    assert pl["3 meses"]["dif_pb"] == 7 and pl["3 meses"]["lectura"] == "sin cambios"
    assert pl["2 años"]["dif_pb"] == -33 and pl["2 años"]["lectura"] == "bajadas"
    assert out["pendiente"]["10a_2a"]["pb"] == 128 and out["pendiente"]["10a_3m"]["hace_1m"] == 88


def test_fallos_no_rompen_y_conservan_lo_anterior():
    prev = T.build(ConTipos(), lambda s: ConTipos().fred(s, None), [])
    avisos = []
    f = ConTipos(fallan={"DFEDTARU", "tesoro"})

    def fred(s):
        try:
            return f.fred(s, None)
        except RuntimeError:
            raise
    out = T.build(f, fred, avisos, prev)
    assert out["fed"]["desactualizado"] and out["mercado"] == prev["mercado"]
    assert any(a.startswith("Tipos de la Fed") for a in avisos) and any(a.startswith("Curva del Tesoro") for a in avisos)


def test_tesoro_descarga_cada_anio_una_vez():
    from fetcher import mercado_hoy as MH
    llamadas = []

    def http(url, **k):
        llamadas.append(url)
        return 'Date,"3 Mo","10 Yr"\n11/04/2026,3.95,4.83\n'
    f = MH.Fuentes(env={}, http=http, hoy=date(2026, 11, 6), sleep=lambda s: None)
    f.tesoro("3 Mo"); f.tesoro("10 Yr"); f.tesoro("3 Mo")
    assert len(llamadas) == 2
