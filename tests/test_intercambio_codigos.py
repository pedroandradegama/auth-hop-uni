import importlib


def test_resolver_identidade():
    codigos = importlib.import_module("adapters.unimed_intercambio.codigos")
    assert codigos.resolver_codigo_portal("40901122") == "40901122"
    assert codigos.resolver_codigo_portal("  123 ") == "123"
