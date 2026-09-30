"""Telemetria opt-in do canario SASSEPE: nao pode mexer no fluxo normal."""
import importlib

import pytest


_ui = importlib.import_module("adapters.sassepe._ui")
submit = importlib.import_module("adapters.sassepe.submit")
config = importlib.import_module("adapters.sassepe.config")


class _PageMetricas:
    def __init__(self):
        self.chamadas = []

    async def evaluate(self, script, *args):
        self.chamadas.append(script)
        if script == _ui._JS_METRICAS_LISTBOX:
            return {"aberto": True, "alvo": {"scrollTop": 0, "maxScroll": 120}}
        return {"estado": "ok", "opcoes": ["21798 - PEDRO"], "indices": [0]}


@pytest.mark.asyncio
async def test_telemetria_desligada_nao_le_o_dom(monkeypatch):
    page = _PageMetricas()
    monkeypatch.setattr(config, "telemetria_dropdown_habilitada", lambda: False)

    await _ui._telemetria_listbox(page, "antes_busca", termo="21798")

    assert page.chamadas == []


@pytest.mark.asyncio
async def test_diagnostico_separa_metricas_e_opcoes():
    page = _PageMetricas()

    dado = await _ui.diagnostico_listbox(page)

    assert dado["estado"] == "ok"
    assert dado["qtd_opcoes"] == 1
    assert dado["metricas"]["alvo"]["maxScroll"] == 120


class _Tracing:
    def __init__(self):
        self.inicios = []
        self.paradas = []

    async def start(self, **kwargs):
        self.inicios.append(kwargs)

    async def stop(self, **kwargs):
        self.paradas.append(kwargs)


class _PageTrace:
    def __init__(self):
        self.context = type("Context", (), {"tracing": _Tracing()})()


@pytest.mark.asyncio
async def test_trace_so_persiste_quando_falha(monkeypatch, tmp_path):
    page = _PageTrace()
    monkeypatch.setattr(config, "trace_falhas_habilitado", lambda: True)
    monkeypatch.setattr(config, "TRACES_DIR", str(tmp_path))

    assert await submit._iniciar_trace_falha(page) is True
    caminho = await submit._encerrar_trace(page, falhou=True)

    assert page.context.tracing.inicios == [
        {"screenshots": True, "snapshots": True, "sources": False}
    ]
    assert caminho is not None and caminho.endswith(".zip")
    assert page.context.tracing.paradas == [{"path": caminho}]

