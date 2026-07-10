import importlib


def test_unimed_expoe_sessao_e_dominio():
    adapter = importlib.import_module("adapters.unimed_recife")
    assert hasattr(adapter, "sessao")
    assert callable(adapter.sessao.navegador)
    assert callable(adapter.sessao.login)
    assert adapter.DOMINIO == "autorizador.unimedrecife.com.br"
