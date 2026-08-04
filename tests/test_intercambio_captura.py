import importlib


def _m():
    return importlib.import_module("adapters.unimed_intercambio.submit")


def test_captura_autorizado_vira_protocolado():
    cap = {"status_guia": "Autorizado", "autorizacao": "192549032",
           "guia_operadora": "137873051", "guia_prestador": "18009511500042011431",
           "data": "04/08/2026"}
    r = _m()._mapear_captura(cap)
    assert r["status"] == "protocolado"
    assert r["numero_protocolo"] == "192549032"
    assert r["numero_guia_operadora"] == "137873051"


def test_captura_negado_vira_requer_humano():
    cap = {"status_guia": "Negado", "autorizacao": "-", "guia_operadora": "137878504",
           "guia_prestador": "18009511500042016408", "data": "04/08/2026"}
    r = _m()._mapear_captura(cap)
    assert r["status"] == "requer_humano"
    assert r["requer_captura_manual"] is True
    assert "NEGADA" in r["mensagem"]


def test_captura_cancelada_vira_requer_humano():
    cap = {"status_guia": "Cancelada", "autorizacao": "192517463", "guia_operadora": "137828823",
           "guia_prestador": "18009511500041974415", "data": "03/08/2026"}
    r = _m()._mapear_captura(cap)
    assert r["status"] == "requer_humano"
    assert "CANCELADA" in r["mensagem"]


def test_captura_none_vira_captura_manual():
    r = _m()._mapear_captura(None)
    assert r["status"] == "requer_humano"
    assert r["requer_captura_manual"] is True
