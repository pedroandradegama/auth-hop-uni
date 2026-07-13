import contextlib
import importlib

import pytest

from agente import FalhaDeterministica, MotivoFalha


class _FakePage:
    url = "https://portal.test/x"


def _fake_navegador():
    @contextlib.asynccontextmanager
    async def _nav():
        yield _FakePage()
    return _nav


async def _noop_login(page):
    return None


# ── exports (sessao + DOMINIO) ────────────────────────────────────────────
def test_sassepe_exports():
    a = importlib.import_module("adapters.sassepe")
    assert callable(a.sessao.navegador) and callable(a.sessao.login)
    assert a.DOMINIO == "sassepe.maida.health"


def test_sulamerica_exports():
    a = importlib.import_module("adapters.sulamerica")
    assert callable(a.sessao.navegador) and callable(a.sessao.login)
    assert a.DOMINIO == "saude.sulamericaseguros.com.br"


# ── Costura A: hard stop in-portal -> FalhaDeterministica ──────────────────
@pytest.mark.asyncio
async def test_sassepe_hardstop_vira_falha(monkeypatch):
    submit = importlib.import_module("adapters.sassepe.submit")
    sessao = importlib.import_module("adapters.sassepe.sessao")
    monkeypatch.setattr(sessao, "navegador", _fake_navegador())
    monkeypatch.setattr(sessao, "login", _noop_login)

    async def _raise(page):
        raise submit.SubmitAbortado("Card 'SP/SADT' nao encontrado.")
    monkeypatch.setattr(submit, "_abrir_sp_sadt", _raise)

    job = {"cpf": "64387720468", "medico": "16188 NUBIA",
           "codigos": [{"codigo_tuss": "40808041", "sub_tipo": "RM"}],
           "arquivos": ["/x"], "paciente_nome": "X"}
    with pytest.raises(FalhaDeterministica) as ei:
        await submit.executar(job)
    assert ei.value.motivo == MotivoFalha.ESTADO_INESPERADO
    assert ei.value.etapa == "submit_sassepe"
    assert "SP/SADT" in ei.value.detalhe


@pytest.mark.asyncio
async def test_sulamerica_hardstop_vira_falha(monkeypatch):
    submit = importlib.import_module("adapters.sulamerica.submit")
    sessao = importlib.import_module("adapters.sulamerica.sessao")
    monkeypatch.setattr(sessao, "navegador", _fake_navegador())
    monkeypatch.setattr(sessao, "login", _noop_login)

    async def _raise(page):
        raise submit.SubmitAbortado("Formulario SP/SADT nao carregou.")
    monkeypatch.setattr(submit, "_navegar_para_solicitacao", _raise)

    job = {"carteirinha": "01234567890123456789", "medico": "16188 NOME",
           "codigos": [{"codigo_tuss": "40901220"}], "arquivos": ["/x"]}
    with pytest.raises(FalhaDeterministica) as ei:
        await submit.executar(job)
    assert ei.value.motivo == MotivoFalha.ESTADO_INESPERADO
    assert ei.value.etapa == "submit_sulamerica"
    assert "SP/SADT" in ei.value.detalhe
