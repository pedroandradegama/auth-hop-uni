"""Custo de tempo por exame — reclamação da ponta em 25/set: "está demorando
muito a processar no portal quando são múltiplos exames".

Medido no código (soma dos wait_for_timeout fixos), ANTES:

    abrir_dropdown      3,8s
    preencher_dropdown  4,6s
    POR EXAME          12,5s   ->  6 exames = 1,2 min | 20 exames = 4,2 min

Duas causas, ambas nossas:
  1. a Tabela (sempre 22, nunca muda) era re-selecionada a CADA exame — 5,1s;
  2. as esperas eram fixas: 2000ms cravados depois de digitar, mesmo que a
     lista aparecesse em 300ms.
"""
import importlib
import inspect

import pytest

_ui = importlib.import_module("adapters.sassepe._ui")
submit = importlib.import_module("adapters.sassepe.submit")


class TestEsperaPorEvento:
    def test_abrir_dropdown_nao_usa_mais_espera_fixa_de_2s(self):
        src = inspect.getsource(_ui.abrir_dropdown)
        assert "wait_for_timeout(2000)" not in src
        assert "_esperar_listbox(page, 2000)" in src

    def test_o_teto_nao_mudou(self):
        """Poll não pode piorar o pior caso — só sair mais cedo."""
        src = inspect.getsource(_ui.abrir_dropdown)
        assert "_esperar_listbox(page, 2000)" in src   # era wait fixo de 2000
        assert "_esperar_listbox(page, 800)" in src    # era wait fixo de 800

    @pytest.mark.asyncio
    async def test_sai_assim_que_o_listbox_responde(self):
        class _Page:
            def __init__(self): self.esperas = 0
            async def evaluate(self, js, *a): return self.esperas >= 2
            async def wait_for_timeout(self, ms): self.esperas += 1
        page = _Page()
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150) is True
        assert page.esperas <= 3        # ~450ms, não 2000ms

    @pytest.mark.asyncio
    async def test_respeita_o_teto_quando_nunca_responde(self):
        class _Page:
            def __init__(self): self.esperas = 0
            async def evaluate(self, js, *a): return False
            async def wait_for_timeout(self, ms): self.esperas += 1
        page = _Page()
        assert await _ui._esperar_listbox(page, 900, passo_ms=150) is False
        assert page.esperas == 6        # 900/150

    @pytest.mark.asyncio
    async def test_contexto_destruido_nao_derruba_o_poll(self):
        """Navegação do SPA mata o evaluate; o poll tem que seguir."""
        class _Page:
            def __init__(self): self.n = 0
            async def evaluate(self, js, *a):
                self.n += 1
                if self.n == 1: raise RuntimeError("Execution context destroyed")
                return True
            async def wait_for_timeout(self, ms): pass
        assert await _ui._esperar_listbox(_Page(), 900, passo_ms=150) is True


class TestTabelaUmaVez:
    @pytest.mark.asyncio
    async def test_nao_reseleciona_quando_ja_esta_em_22(self, monkeypatch):
        chamou = []

        async def _valor(page, label, indice=0): return "22 - Procedimentos e eventos em saúde"
        monkeypatch.setattr(_ui, "valor_do_campo", _valor)

        async def _preencher(page, label, *a, **k):
            chamou.append(label)
            return True
        monkeypatch.setattr(_ui, "preencher_dropdown", _preencher)

        class _Page:
            url = "https://x"
            async def wait_for_timeout(self, ms): pass
            async def evaluate(self, js, *a): return None   # botão '+' não achado
            mouse = None
        ok, erro = await submit._adicionar_exame(_Page(), "40901122", 1)
        assert "Tabela" not in chamou          # pulou o dropdown da Tabela
        assert not ok and "quantidade" in erro  # parou adiante, como esperado

    @pytest.mark.asyncio
    async def test_reseleciona_quando_o_portal_limpou(self, monkeypatch):
        """Se o portal zerar o bloco entre itens, a conferência detecta."""
        chamou = []

        async def _valor(page, label, indice=0): return ""
        monkeypatch.setattr(_ui, "valor_do_campo", _valor)

        async def _preencher(page, label, *a, **k):
            chamou.append(label)
            return True
        monkeypatch.setattr(_ui, "preencher_dropdown", _preencher)

        class _Page:
            url = "https://x"
            async def wait_for_timeout(self, ms): pass
            async def evaluate(self, js, *a): return None
            mouse = None
        await submit._adicionar_exame(_Page(), "40901122", 1)
        assert "Tabela" in chamou
