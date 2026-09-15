"""Clicar num dropdown não é prova de que o campo ficou preenchido.

Caso (15/set/2026, job 3d1b8d73): o 'Código CBO' da seção Contratado EXECUTANTE
ficou VAZIO no portal, mas preencher_cbo devolveu True. O adapter seguiu, montou
a página 1 inteira e só descobriu o problema no 'Próximo' — que o portal reprovou
por campo obrigatório, sem mensagem que o robô soubesse ler.

O CBO do executante só popula DEPOIS que o profissional executante é selecionado.
Se a lista ainda não carregou, o clique cai no vazio.
"""
import importlib

import pytest

_ui = importlib.import_module("adapters.sassepe._ui")


class _PageFake:
    """Portal falso: a opção do CBO só aparece a partir de `abre_na_tentativa`."""

    def __init__(self, abre_na_tentativa=1, placeholder=False, grava=True):
        self.abre = abre_na_tentativa
        self.placeholder = placeholder
        self.grava = grava
        self.valor = ""
        self.tentativa = 0
        self.cliques_opcao = 0   # so' os cliques NA OPCAO (abrir_dropdown tambem clica)
        self.mouse = self
        self.keyboard = self

    async def evaluate(self, js, *a):
        if "scrollIntoView({block: 'center'})" in js or "label.scrollIntoView" in js:
            return True
        if "lx:" in js:                      # rect do label
            return {"lx": 0, "ly": 0, "lw": 100}
        if "WheelEvent" in js:
            return None
        if "nenhum resultado" in js.lower() and "listbox" in js.lower():
            self.tentativa += 1
            if self.placeholder or self.tentativa < self.abre:
                return None                  # lista vazia (ou ainda carregando)
            return {"cx": 5, "cy": 5, "texto": "999999 - null"}
        if "melhor.value" in js:             # leitura do valor do campo
            return self.valor
        return None

    async def click(self, x, y):
        if (x, y) != (5, 5):
            return               # clique que abre o dropdown, nao seleciona
        self.cliques_opcao += 1
        if self.grava:
            self.valor = "999999 - null"

    async def press(self, k): pass
    async def type(self, t): pass
    async def wait_for_timeout(self, ms): pass


@pytest.mark.asyncio
async def test_caminho_feliz():
    page = _PageFake()
    assert await _ui.preencher_cbo(page, indice=0) is True
    assert page.valor == "999999 - null"


@pytest.mark.asyncio
async def test_lista_lenta_e_re_tentada():
    """O CBO do executante aparece só depois que o profissional carrega."""
    page = _PageFake(abre_na_tentativa=3)
    assert await _ui.preencher_cbo(page, indice=1) is True
    assert page.cliques_opcao == 1


@pytest.mark.asyncio
async def test_clique_que_nao_gravou_devolve_false():
    """O BUG: antes isto devolvia True e o adapter seguia com o campo vazio."""
    page = _PageFake(grava=False)
    assert await _ui.preencher_cbo(page, indice=1) is False
    assert page.valor == ""


@pytest.mark.asyncio
async def test_placeholder_nao_e_clicado():
    page = _PageFake(placeholder=True)
    assert await _ui.preencher_cbo(page, indice=1) is False
    assert page.cliques_opcao == 0


@pytest.mark.asyncio
async def test_valor_do_campo_sem_erro_quando_a_pagina_reclama():
    class _Explode:
        async def evaluate(self, *a): raise RuntimeError("contexto destruido")
    assert await _ui.valor_do_campo(_Explode(), "Código CBO", 1) == ""
