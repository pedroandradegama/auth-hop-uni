import contextlib

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from agente import FalhaDeterministica, MotivoFalha


class _FakeLocator:
    async def click(self, *a, **k): return None
    async def wait_for(self, *a, **k): return None


class _FakeRole:
    async def click(self, *a, **k): return None


class _FakePage:
    """Simula o portal até o 1o hard stop: tudo passa, menos o
    wait_for_selector('#emailprestador'), que estoura como no portal real
    quando a carteirinha não retorna beneficiário."""
    url = "https://autorizador.unimedrecife.com.br/gerar.php"

    def get_by_role(self, *a, **k): return _FakeRole()
    def locator(self, *a, **k): return _FakeLocator()

    async def fill(self, *a, **k): return None
    async def click(self, *a, **k): return None
    async def wait_for_load_state(self, *a, **k): return None
    async def wait_for_timeout(self, *a, **k): return None
    async def screenshot(self, *a, **k): return None
    async def select_option(self, *a, **k): return None

    async def wait_for_selector(self, seletor, *a, **k):
        if "emailprestador" in seletor:
            raise PlaywrightTimeoutError("emailprestador ausente")
        return None


@pytest.mark.asyncio
async def test_beneficiario_nao_encontrado_lanca_falha(monkeypatch):
    import importlib
    submit = importlib.import_module("adapters.unimed_recife.submit")
    sessao = importlib.import_module("adapters.unimed_recife.sessao")

    @contextlib.asynccontextmanager
    async def _fake_navegador():
        yield _FakePage()

    monkeypatch.setattr(sessao, "navegador", _fake_navegador)

    async def _noop_login(page):
        return None

    monkeypatch.setattr(sessao, "login", _noop_login)

    job = {
        "carteirinha": "0" * 16, "medico": "DR FULANO",
        "codigos": [{"codigo_tuss": "40901114", "sub_tipo": "RM"}],
        "arquivos": [], "paciente_nome": "PACIENTE X",
    }
    with pytest.raises(FalhaDeterministica) as ei:
        await submit.executar(job)
    falha = ei.value
    assert falha.motivo == MotivoFalha.VALIDACAO_PORTAL
    assert falha.etapa == "buscar_beneficiario"
    assert "autorizador.unimedrecife.com.br" in (falha.url or "")
