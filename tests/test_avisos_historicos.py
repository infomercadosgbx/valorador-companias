from datetime import date

from fetcher import validate as V


def _w(codigo, periodo, nivel="aviso"):
    return {"nivel": nivel, "codigo": codigo, "mensaje": f"Ingresos {periodo}: x", "periodo": periodo}


def test_antiguos_pasan_a_nota_y_los_recientes_siguen_siendo_aviso():
    avisos = [_w("salto_raro", "4T21"), _w("posible_discontinuada", "2023"),
              _w("salto_raro", "3T24"), _w("posible_discontinuada", "2025"),
              _w("deuda_asumida_cero", None), _w("etiqueta_obsoleta", "2019", "info")]
    out = V.archivar_antiguos(avisos, date(2026, 9, 30))
    niv = {(w["codigo"], w["periodo"]): (w["nivel"], w.get("historico")) for w in out}
    assert niv[("salto_raro", "4T21")] == ("info", True)
    assert niv[("posible_discontinuada", "2023")] == ("info", True)
    assert niv[("salto_raro", "3T24")] == ("aviso", None)
    assert niv[("posible_discontinuada", "2025")] == ("aviso", None)
    assert niv[("deuda_asumida_cero", None)] == ("aviso", None)
    assert niv[("etiqueta_obsoleta", "2019")] == ("info", None)


def test_el_mensaje_no_cambia_para_conservar_aprobaciones():
    w = _w("salto_raro", "1T22")
    V.archivar_antiguos([w], date(2026, 9, 30))
    assert w["mensaje"] == "Ingresos 1T22: x"


def test_sin_fecha_de_referencia_no_toca_nada():
    w = _w("salto_raro", "1T22")
    V.archivar_antiguos([w], None)
    assert w["nivel"] == "aviso"
