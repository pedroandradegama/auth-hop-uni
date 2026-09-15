"""'Próximo' precisa ESPERAR a navegação e, se não avançar, dizer por quê.

Caso (15/set/2026, job 3d1b8d73): o robô preencheu a página 1 inteira — paciente,
cabeçalho, 2 exames de RX cobertos pelo convênio, anexo — clicou 'Próximo' e
abortou com "Esperava a tela de resumo (confirmar-dados), URL atual: .../sp-sadt".

A mensagem não distinguia duas causas opostas: o portal REPROVOU a página por
validação, ou a navegação do SPA só demorou mais que os 2s fixos que
_clicar_proximo esperava. Sem isso o agente supôs WAF e bloqueio de bot — os
diag_* mostram o portal respondendo em cada passo anterior.
"""
import importlib

import pytest

submit = importlib.import_module("adapters.sassepe.submit")


class _PageFake:
    """Simula o SPA: a URL troca depois de N polls."""

    def __init__(self, polls_ate_navegar=None, erros=None, achar_botao=True):
        self.url = "https://sassepe.maida.health/solicitacoes/sp-sadt"
        self._restantes = polls_ate_navegar
        self._erros = erros or []
        self._achar = achar_botao
        self.cliques = 0
        self.mouse = self

    async def evaluate(self, js, *a):
        if "Próximo" in js:
            return {"cx": 10, "cy": 20} if self._achar else None
        if "role=alert" in js:
            return self._erros
        return None

    async def click(self, x, y):
        self.cliques += 1

    async def wait_for_timeout(self, ms):
        if self._restantes is not None:
            self._restantes -= 1
            if self._restantes <= 0:
                self.url = "https://sassepe.maida.health/solicitacoes/confirmar-dados"


@pytest.mark.asyncio
async def test_espera_a_navegacao_lenta_do_spa():
    """Antes, 2s fixos: navegação em 4 polls virava falso negativo."""
    page = _PageFake(polls_ate_navegar=4)
    await submit._clicar_proximo(page, timeout_ms=15000, passo_ms=500)
    assert "confirmar-dados" in page.url
    assert page.cliques == 1


@pytest.mark.asyncio
async def test_navegacao_imediata_nao_espera_atoa():
    page = _PageFake(polls_ate_navegar=1)
    await submit._clicar_proximo(page, timeout_ms=15000, passo_ms=500)
    assert "confirmar-dados" in page.url


@pytest.mark.asyncio
async def test_reprovacao_do_portal_entra_no_detalhe():
    page = _PageFake(polls_ate_navegar=None,
                     erros=["Código CBO é obrigatório",
                            "Data da solicitação inválida"])
    with pytest.raises(submit.SubmitAbortado) as ei:
        await submit._clicar_proximo(page, timeout_ms=1000, passo_ms=500)
    msg = str(ei.value)
    assert "o portal reprovou" in msg
    assert "Código CBO" in msg
    assert "Data da solicitação" in msg


@pytest.mark.asyncio
async def test_sem_mensagem_o_detalhe_diz_isso_explicitamente():
    """Silêncio do portal é informação: separa 'reprovou' de 'clique não pegou'."""
    page = _PageFake(polls_ate_navegar=None, erros=[])
    with pytest.raises(submit.SubmitAbortado) as ei:
        await submit._clicar_proximo(page, timeout_ms=1000, passo_ms=500)
    msg = str(ei.value)
    assert "nao exibiu mensagem de validacao" in msg
    assert "sp-sadt" in msg


@pytest.mark.asyncio
async def test_botao_ausente_continua_sendo_erro_proprio():
    page = _PageFake(achar_botao=False)
    with pytest.raises(submit.SubmitAbortado) as ei:
        await submit._clicar_proximo(page)
    assert "nao encontrado" in str(ei.value)
    assert page.cliques == 0
