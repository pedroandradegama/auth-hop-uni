"""Credencial rejeitada tem que falhar com o motivo CERTO.

Sem isso ela se disfarça de problema de portal: o modal de contexto não aparece
(porque o login não passou) e o adapter reporta 'modal_nao_apareceu', mandando a
investigação para timeout/seletor. Foi o que aconteceu em 03/set — o dump do
teste_login mostrou a página ainda no formulário de login com o ALERTA
"Verifique se usuário e/ou senha estão corretos".
"""
import importlib

import pytest


def _mod():
    return importlib.import_module("adapters.unimed_intercambio.sessao")


class _Page:
    def __init__(self, retorno=None, erro=None):
        self._retorno, self._erro = retorno, erro

    async def evaluate(self, _js):
        if self._erro:
            raise self._erro
        return self._retorno


@pytest.mark.asyncio
async def test_detecta_alerta_de_credencial():
    texto = "Verifique se usuário e/ou senha estão corretos."
    assert await _mod().erro_credencial(_Page(texto)) == texto


@pytest.mark.asyncio
async def test_sem_alerta_devolve_none():
    assert await _mod().erro_credencial(_Page(None)) is None


@pytest.mark.asyncio
async def test_erro_no_evaluate_nao_levanta():
    """Diagnóstico nunca pode derrubar o fluxo."""
    assert await _mod().erro_credencial(_Page(erro=RuntimeError("ctx destroyed"))) is None


def test_js_procura_o_texto_do_portal_sem_acento():
    """O JS normaliza acentos, então casa 'usuário e/ou senha' do portal."""
    js = _mod()._JS_ERRO_CREDENCIAL
    assert "usuario e" in js and "ou senha" in js
    assert "normalize('NFD')" in js
