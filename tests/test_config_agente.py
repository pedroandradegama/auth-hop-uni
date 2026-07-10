import importlib


def test_agente_flags(monkeypatch):
    import config
    monkeypatch.setenv("AGENTE_HABILITADO", "true")
    monkeypatch.delenv("AGENTE_SUBMETER_HABILITADO", raising=False)
    importlib.reload(config)
    assert config.agente_habilitado() is True
    assert config.agente_submeter_habilitado() is False  # default F0


def test_agente_flags_desligado(monkeypatch):
    import config
    monkeypatch.setenv("AGENTE_HABILITADO", "false")
    importlib.reload(config)
    assert config.agente_habilitado() is False
