import importlib


def test_intercambio_exports():
    a = importlib.import_module("adapters.unimed_intercambio")
    assert a.NOME == "unimed_intercambio"
    assert callable(a.submit)
    assert callable(a.sessao.navegador)
    assert a.DOMINIO == "remote.unimedrecife.com.br:444"
