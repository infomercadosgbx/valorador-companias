"""scripts/aplicar_cambios.py: qué se aplica solo, qué espera al usuario y qué va a la cola."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for d in ("analysis", "data", "propuestas", "scripts"):
        (tmp_path / d).mkdir()
    shutil.copy(REPO / "valorador.html", tmp_path)
    shutil.copy(REPO / "scripts" / "impacto_dcf.mjs", tmp_path / "scripts")
    for f in ("analysis/VST.json", "data/VST.json"):
        shutil.copy(REPO / f, tmp_path / f)
    (tmp_path / "companies.json").write_text(json.dumps([{"ticker": "VST"}]))
    spec = importlib.util.spec_from_file_location("aplicar", REPO / "scripts" / "aplicar_cambios.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "PROP", tmp_path / "propuestas")
    monkeypatch.setattr(m, "COLA", tmp_path / "propuestas" / "_cola")
    return m, tmp_path


def _prop(root, cambios, **kw):
    p = {"ticker": "VST", "creada": "2026-11-12", "motivo": "Prueba", "resumen": "r", "fuentes": [], "cambios": cambios, **kw}
    (root / "propuestas" / "VST.json").write_text(json.dumps(p, ensure_ascii=False))


def _rd(p):
    return json.loads(p.read_text()) if p.exists() else None


OK = {"ok": True, "nota": "Cifra presente en el 10-Q"}


def test_hecho_verificado_se_aplica_y_se_registra(repo):
    m, root = repo
    _prop(root, [{"campo": "meta.employees", "valor": "6.850", "tipo": "hecho", "porque": "p", "verificacion": OK}])
    r = m.procesar("VST", "2026-11-12", False)
    an = _rd(root / "analysis/VST.json")
    assert an["meta"]["employees"] == "6.850"
    assert an["cambios_auto"][-1]["campo"] == "meta.employees"
    assert an["cambios_auto"][-1]["antes"] == "6.390"
    assert r["aplicados"] == ["meta.employees"]
    assert not (root / "propuestas/VST.json").exists()


def test_hecho_sin_verificar_queda_para_hoy(repo):
    m, root = repo
    _prop(root, [{"campo": "meta.employees", "valor": "6.850", "tipo": "hecho", "verificacion": {"ok": False, "nota": "No aparece en el 10-Q"}}])
    m.procesar("VST", "2026-11-12", False)
    p = _rd(root / "propuestas/VST.json")
    assert p["cambios"][0]["fallo_verificacion"] == "No aparece en el 10-Q"
    assert _rd(root / "analysis/VST.json")["meta"]["employees"] == "6.390"


def test_criterio_disfrazado_de_hecho_no_se_aplica(repo):
    m, root = repo
    _prop(root, [{"campo": "verdict.rating", "valor": "Comprar", "tipo": "hecho", "verificacion": OK}])
    m.procesar("VST", "2026-11-12", False)
    assert _rd(root / "analysis/VST.json")["verdict"]["rating"] != "Comprar"
    assert _rd(root / "propuestas/_cola/VST.json")["cambios"][0]["campo"] == "verdict.rating"


def test_criterio_sin_resultados_va_a_la_cola_y_sale_el_sabado(repo):
    m, root = repo
    _prop(root, [{"campo": "verdict.conviction", "valor": "Alta", "tipo": "criterio", "porque": "x"}])
    m.procesar("VST", "2026-11-12", False)
    assert not (root / "propuestas/VST.json").exists()
    assert (root / "propuestas/_cola/VST.json").exists()
    m.procesar("VST", "2026-11-14", True)
    p = _rd(root / "propuestas/VST.json")
    assert p["cambios"][0]["campo"] == "verdict.conviction" and p["creada"] == "2026-11-14"
    assert p["motivo"].startswith("Revisión semanal")
    assert not (root / "propuestas/_cola/VST.json").exists()


def test_criterio_urgente_queda_para_hoy(repo):
    m, root = repo
    _prop(root, [{"campo": "verdict.conviction", "valor": "Alta", "tipo": "criterio"}], urgente=True)
    m.procesar("VST", "2026-11-12", False)
    assert _rd(root / "propuestas/VST.json")["cambios"][0]["campo"] == "verdict.conviction"


def test_supuesto_dcf_pequeno_se_descarta(repo):
    m, root = repo
    an = _rd(root / "analysis/VST.json")
    _prop(root, [{"campo": "v.tax", "valor": an["v"]["tax"] + 0.5, "tipo": "criterio"}], urgente=True)
    r = m.procesar("VST", "2026-11-12", False)
    assert r["descartados"] and not (root / "propuestas/VST.json").exists()


def test_supuesto_dcf_grande_no_espera_al_sabado(repo):
    m, root = repo
    an = _rd(root / "analysis/VST.json")
    g = list(an["v"]["g"]); g[0] += 15
    _prop(root, [{"campo": "v.g", "valor": g, "tipo": "criterio"}])
    r = m.procesar("VST", "2026-11-12", False)
    assert r["impacto_dcf"] >= 10
    assert _rd(root / "propuestas/VST.json")["cambios"][0]["campo"] == "v.g"


def test_avisos_resueltos_y_ajustes_caducados(repo):
    m, root = repo
    an = _rd(root / "analysis/VST.json")
    an["ajustes_posteriores"][0]["base_accn"] = "viejo"
    (root / "analysis/VST.json").write_text(json.dumps(an, ensure_ascii=False))
    _prop(root, [], avisos_resueltos=[{"codigo": "trimestres_no_suman", "nivel": "aviso", "mensaje": "Ingresos 2025: los 4 trimestres suman 17.700 M y el año 17.738 M.",
                                       "comprobacion": "Coberturas a mercado (nota 4 del 10-Q)."}])
    r = m.procesar("VST", "2026-11-12", False)
    an = _rd(root / "analysis/VST.json")
    assert r["caducados"] == 1 and len(an["ajustes_posteriores"]) == 1
    nuevo = an["avisos_aprobados"][-1]
    assert nuevo["por"] == "robot" and nuevo["id"] == "trimestres_no_suman.Ingresos #: los # trimestres suman # M y el año # M."


def test_w_id_igual_que_la_web():
    spec = importlib.util.spec_from_file_location("aplicar", REPO / "scripts" / "aplicar_cambios.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    an = json.loads((REPO / "analysis/VST.json").read_text())
    for a in an["avisos_aprobados"]:
        cod = a["id"].split(".", 1)[0]
        assert m.w_id(cod, a["mensaje"]) == a["id"]


def test_texto_verificado_se_aplica_solo(repo):
    """Tesis, riesgos, MOAT… se aplican solos si pasan la verificación (13-nov-2026)."""
    m, root = repo
    _prop(root, [{"campo": "overview.thesis", "valor": "Nueva tesis", "tipo": "texto", "verificacion": OK}])
    r = m.procesar("VST", "2026-11-12", False)
    assert _rd(root / "analysis/VST.json")["overview"]["thesis"] == "Nueva tesis"
    assert r["aplicados"] == ["overview.thesis"]


def test_texto_sin_verificar_no_se_aplica(repo):
    m, root = repo
    antes = _rd(root / "analysis/VST.json")["overview"]["thesis"]
    _prop(root, [{"campo": "overview.thesis", "valor": "X", "tipo": "texto", "verificacion": {"ok": False, "nota": "No lo dice la fuente"}}])
    m.procesar("VST", "2026-11-12", False)
    assert _rd(root / "analysis/VST.json")["overview"]["thesis"] == antes
    assert _rd(root / "propuestas/VST.json")["cambios"][0]["fallo_verificacion"] == "No lo dice la fuente"


def test_riesgo_con_salto_grande_espera_al_usuario(repo):
    m, root = repo
    riesgos = _rd(root / "analysis/VST.json")["risks"]
    nuevo = [dict(x) for x in riesgos]
    nuevo[0]["p"] = 1 if float(nuevo[0]["p"]) >= 3 else 5
    _prop(root, [{"campo": "risks", "valor": nuevo, "tipo": "texto", "verificacion": OK}], urgente=True)
    r = m.procesar("VST", "2026-11-12", False)
    assert _rd(root / "analysis/VST.json")["risks"] == riesgos
    assert r["hoy"] == ["risks"]
    assert "Cambio grande" in _rd(root / "propuestas/VST.json")["cambios"][0]["espera_usuario"]


def test_riesgo_con_salto_pequeno_se_aplica(repo):
    m, root = repo
    riesgos = _rd(root / "analysis/VST.json")["risks"]
    nuevo = [dict(x) for x in riesgos]
    nuevo[0]["p"] = float(nuevo[0]["p"]) + (1 if float(nuevo[0]["p"]) < 5 else -1)
    nuevo[0]["note"] = "Nota nueva"
    _prop(root, [{"campo": "risks", "valor": nuevo, "tipo": "texto", "verificacion": OK}])
    m.procesar("VST", "2026-11-12", False)
    assert _rd(root / "analysis/VST.json")["risks"][0]["note"] == "Nota nueva"


def test_veredicto_y_dcf_nunca_se_aplican_solos(repo):
    m, root = repo
    an = _rd(root / "analysis/VST.json")
    _prop(root, [{"campo": "verdict.rating", "valor": "Vender", "tipo": "texto", "verificacion": OK},
                 {"campo": "notes", "valor": "x", "tipo": "texto", "verificacion": OK}], urgente=True)
    m.procesar("VST", "2026-11-12", False)
    an2 = _rd(root / "analysis/VST.json")
    assert an2["verdict"] == an["verdict"] and an2.get("notes") == an.get("notes")


def test_textos_del_veredicto_se_aplican_y_la_recomendacion_no(repo):
    m, root = repo
    an = _rd(root / "analysis/VST.json")
    _prop(root, [{"campo": "verdict.summary", "valor": "Resumen nuevo", "tipo": "texto", "verificacion": OK},
                 {"campo": "verdict.watch", "valor": ["Vigilar A"], "tipo": "texto", "verificacion": OK},
                 {"campo": "verdict.buyBelow", "valor": 1, "tipo": "texto", "verificacion": OK}], urgente=True)
    m.procesar("VST", "2026-11-12", False)
    v2 = _rd(root / "analysis/VST.json")["verdict"]
    assert v2["summary"] == "Resumen nuevo" and v2["watch"] == ["Vigilar A"]
    assert v2["buyBelow"] == an["verdict"]["buyBelow"] and v2.get("rating") == an["verdict"].get("rating")
    assert _rd(root / "propuestas/VST.json")["cambios"][0]["campo"] == "verdict.buyBelow"


def test_texto_del_veredicto_sin_verificar_no_se_aplica(repo):
    m, root = repo
    an = _rd(root / "analysis/VST.json")
    _prop(root, [{"campo": "verdict.bull", "valor": ["x"], "tipo": "texto", "verificacion": {"ok": False, "nota": "no cuadra"}}], urgente=True)
    m.procesar("VST", "2026-11-12", False)
    assert _rd(root / "analysis/VST.json")["verdict"]["bull"] == an["verdict"]["bull"]
