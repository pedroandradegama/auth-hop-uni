import importlib


def test_recibo_autorizado_vira_protocolado():
    submit = importlib.import_module("adapters.unimed_intercambio.submit")
    recibo = {"Número Guia Operadora": "999888", "Nº da Autorização": "AUT123",
              "Data de Validade da Autorização": "31/08/2026", "Status": "Autorizado"}
    r = submit._mapear_recibo(recibo, "Autorizado")
    assert r["status"] == "protocolado"
    assert r["numero_protocolo"] == "999888"
    assert r["numero_autorizacao"] == "AUT123"
    assert r["validade"] == "31/08/2026"


def test_recibo_status_nao_autorizado_vira_pendente():
    submit = importlib.import_module("adapters.unimed_intercambio.submit")
    recibo = {"Número Guia Operadora": "", "Status": "Em análise"}
    r = submit._mapear_recibo(recibo, "Em análise")
    assert r["status"] == "requer_humano"
    assert r["requer_captura_manual"] is True
