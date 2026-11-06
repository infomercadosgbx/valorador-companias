"""Seguimientos: búsqueda de un asunto en documentos de la SEC y noticias (sin red)."""
import json
from datetime import date

from fetcher import seguimientos as S
from fetcher import alerts as A

CFG = {
    "id": "prestamo_doe", "titulo": "Préstamo del DOE", "desde": "2026-10-01",
    "estado_inicial": "Compromiso condicional",
    "terminos": ["Department of Energy", "\\bDOE\\b", "Energy Dominance Financing", "Loan Programs Office"],
    "contexto": ["loan", "guarantee", "financing", "conditional commitment"],
}


def test_clasificar_frases_tipo():
    c = lambda t: S.clasificar(t, CFG)
    assert c("On December 1, 2026, Vistra entered into a loan guarantee agreement with the DOE for up to $4.2 billion.") == "cierre"
    assert c("The DOE has terminated its conditional commitment for the Vistra uprate loan.") == "cancelacion"
    assert c("The DOE conditional commitment could be terminated if conditions are not satisfied.") == "mencion"
    assert c("There can be no assurance that we will reach financial close on the DOE loan.") == "mencion"
    assert c("House Democrats open a probe into the DOE loan to Vistra.") == "riesgo"
    assert c("In October 2026, the DOE issued a conditional commitment for a loan of up to $4.2 billion.") == "mencion"


def test_buscar_exige_contexto():
    txt = "The DOE published data on reactors. " + "x " * 400 + "Vistra received a DOE conditional commitment for a loan."
    frags = S.buscar(txt, CFG)
    assert len(frags) == 1 and "conditional commitment" in frags[0]
    assert S.buscar("Nothing about energy here.", CFG) == []


class FakeClient:
    def __init__(self, docs):
        self.docs, self.urls = docs, []

    def get_text(self, url):
        self.urls.append(url)
        return self.docs.get(url.rsplit("/", 1)[-1])

    def get_json(self, url):
        self.urls.append(url)
        return {"directory": {"item": [{"name": "ex99.htm"}, {"name": "main.htm"}]}}


def _subs():
    r = {"accessionNumber": ["0001-26-000003", "0001-26-000002", "0001-26-000001"],
         "filingDate": ["2026-12-02", "2026-11-09", "2026-09-01"],
         "reportDate": ["", "2026-09-30", ""], "form": ["8-K", "10-Q", "8-K"],
         "primaryDocument": ["main.htm", "q3.htm", "old.htm"], "items": ["1.01,9.01", "", "8.01"]}
    return {"filings": {"recent": r}}


def test_actualizar_historial_avisos_y_email(tmp_path):
    (tmp_path / "seguimientos.json").write_text(json.dumps({"seguimientos": {"VST": [CFG]}}), encoding="utf-8")
    docs = {"q3.htm": "<p>In October 2026, the DOE issued a conditional commitment for a loan of up to $4.2 billion.</p>",
            "main.htm": "<p>Item 1.01.</p>",
            "ex99.htm": "<p>Vistra entered into a loan guarantee agreement with the Department of Energy.</p>"}
    cl = FakeClient(docs)
    comp = {"ticker": "VST", "cik": "1", "nombre": "Vistra"}
    rec = {"avisos": [], "noticias": [{"titular": "Lawmakers probe DOE loan to Vistra", "medio": "Utility Dive",
                                       "url": "https://x/n", "fecha": "2026-12-03"}]}
    S.actualizar(cl, comp, rec, None, tmp_path, subs=_subs(), today=date(2026, 12, 3))
    s = rec["seguimientos"][0]
    assert sorted(s["documentos_leidos"]) == ["0001-26-000002", "0001-26-000003"]   # el de septiembre no se lee
    assert {h["senal"] for h in s["hallazgos"]} == {"mencion", "cierre", "riesgo"}
    assert s["estado"]["codigo"] == "riesgo"   # la señal más reciente (noticia del 3-dic)
    assert sum(1 for w in rec["avisos"] if w["codigo"] == "seguimiento") == 2

    # segunda pasada: no vuelve a descargar lo ya leído ni duplica hallazgos
    cl2 = FakeClient(docs)
    rec2 = {"avisos": [], "noticias": rec["noticias"]}
    S.actualizar(cl2, comp, rec2, rec, tmp_path, subs=_subs(), today=date(2026, 12, 4))
    assert cl2.urls == [] and len(rec2["seguimientos"][0]["hallazgos"]) == 3

    # email: oficial siempre, prensa solo con señal; no se repite
    state = {}
    out = A.company_alerts(comp, rec2, rec2, None, state, date(2026, 12, 4))
    seg = [x for x in out if "Préstamo del DOE" in x[1]]
    assert len(seg) == 3
    assert [x for x in A.company_alerts(comp, rec2, rec2, None, state, date(2026, 12, 4)) if "Préstamo del DOE" in x[1]] == []


def test_sin_configuracion_no_hace_nada(tmp_path):
    rec = {"avisos": []}
    assert S.actualizar(None, {"ticker": "AMZN", "cik": "1"}, rec, None, tmp_path) == []
    assert "seguimientos" not in rec
