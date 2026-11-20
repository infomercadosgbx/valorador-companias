from fetcher.segments import _marcar_detalle


def test_subtotal_y_detalle_de_otra_linea():
    rows = [{"nombre": n, "ajuste": False} for n in (
        "Retail Energy Charge In ERCOT", "Total Other Revenues",
        "Transferable Production Tax Credit Revenues", "Transferable Nuclear Production Tax Credit Revenues",
        "Advertising", "Advertising Services")]
    aj = {r["nombre"] for r in _marcar_detalle(rows) if r["ajuste"]}
    assert aj == {"Total Other Revenues", "Transferable Nuclear Production Tax Credit Revenues"}
