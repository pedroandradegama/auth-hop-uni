"""Modal HTML de ALERTA do CONNECTA (ex.: validacao do medico via CFM indisponivel).

A modal cobre a pagina e desabilita a secao de procedimentos. Nao e' dialogo
NATIVO, entao `page.on("dialog")` nao pega. O adapter dispensa (clica OK),
REGISTRA o texto e segue — a mensagem e' de servico fora, nao de medico invalido.
"""
import importlib

import pytest


def _mod():
    return importlib.import_module("adapters.unimed_intercambio.submit")


class _PageComModal:
    """evaluate() devolve o texto da modal, como o JS faria ao achar+clicar."""
    def __init__(self, texto):
        self._texto = texto
        self.chamadas = 0

    async def evaluate(self, _js):
        self.chamadas += 1
        return self._texto


class _PageQueQuebra:
    async def evaluate(self, _js):
        raise RuntimeError("Execution context was destroyed")


@pytest.mark.asyncio
async def test_dispensa_devolve_texto_da_modal():
    texto = ("ALERTA A validação do médico solicitante está ativada via serviço "
             "CFM. Não foi possível efetuar a validação. OK")
    page = _PageComModal(texto)
    assert await _mod().dispensar_modal_alerta(page) == texto
    assert page.chamadas == 1


@pytest.mark.asyncio
async def test_sem_modal_devolve_none():
    assert await _mod().dispensar_modal_alerta(_PageComModal(None)) is None


@pytest.mark.asyncio
async def test_erro_no_evaluate_nao_levanta():
    """Nunca pode derrubar o fluxo: sem modal detectada, segue a vida."""
    assert await _mod().dispensar_modal_alerta(_PageQueQuebra()) is None
