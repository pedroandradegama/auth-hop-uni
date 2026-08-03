import contextlib
import importlib

import pytest

from agente import FalhaDeterministica, MotivoFalha


class _FakePage:
    url = "https://remote.unimedrecife.com.br:444/connecta/x"

    async def screenshot(self, *a, **k):
        return None


@pytest.mark.asyncio
async def test_login_contexto_falha_vira_falhadeterministica(monkeypatch):
    submit = importlib.import_module("adapters.unimed_intercambio.submit")
    sessao = importlib.import_module("adapters.unimed_intercambio.sessao")

    @contextlib.asynccontextmanager
    async def _fake_navegador():
        yield _FakePage()

    monkeypatch.setattr(sessao, "navegador", _fake_navegador)

    async def _login_quebra(page):
        raise RuntimeError("contexto nao selecionado")

    monkeypatch.setattr(sessao, "login", _login_quebra)

    job = {"carteirinha": "08650002578827002", "medico": "PEDRO ANDRADE GAMA",
           "crm": "21798", "codigos": [{"codigo_tuss": "40901122", "quantidade": 1}]}
    with pytest.raises(FalhaDeterministica) as ei:
        await submit.executar(job)
    assert ei.value.motivo == MotivoFalha.ESTADO_INESPERADO
    assert ei.value.etapa == "login_contexto"
