"""A busca de beneficiario deve distinguir resposta vazia de uma linha clicavel."""
import importlib

import pytest

from agente import FalhaDeterministica, MOTIVOS_AGENTE, MOTIVOS_REQUER_HUMANO, MotivoFalha


def test_valor_do_dropdown_precisa_confirmar_a_opcao_clicada():
    ui = importlib.import_module("adapters.sassepe._ui")
    assert ui._valor_confirma_opcao("01 - Ambulatorial", "01 - Ambulatorial")
    assert ui._valor_confirma_opcao("40901122 - Exame", "40901122 - Exame")
    assert not ui._valor_confirma_opcao("ambulatorial", "01 - Ambulatorial")
    assert not ui._valor_confirma_opcao("40901122", "40901122 - Exame")
    assert not ui._valor_confirma_opcao(None, "22")


@pytest.mark.asyncio
async def test_dropdown_repete_apenas_quando_o_estado_e_transitorio(monkeypatch):
    ui = importlib.import_module("adapters.sassepe._ui")
    respostas = iter((
        ui.ResultadoCampo(ui.MotivoCampo.CLIQUE_SEM_EFEITO, "nao gravou"),
        ui.ResultadoCampo(ui.MotivoCampo.OK),
    ))

    async def _uma_vez(*args, **kwargs):
        return next(respostas)

    monkeypatch.setattr(ui, "_preencher_dropdown_uma_vez", _uma_vez)

    class _Page:
        esperas = []
        async def wait_for_timeout(self, ms): self.esperas.append(ms)

    page = _Page()
    resultado = await ui.preencher_dropdown_detalhado(
        page, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
    assert resultado.ok
    assert page.esperas == [700]


class _Mouse:
    async def click(self, *args):
        return None


class _Keyboard:
    async def type(self, *args):
        return None


class _BuscaVaziaPage:
    url = "https://sassepe.maida.health/solicitacoes/sp-sadt"
    mouse = _Mouse()
    keyboard = _Keyboard()

    async def evaluate(self, js, *args):
        if "placeholder" in js:
            return {"cx": 10, "cy": 10, "bottom": 20}
        if "nenhum beneficiario encontrado" in js:
            return {"estado": "vazio"}
        raise AssertionError("evaluate inesperado")

    async def wait_for_timeout(self, ms):
        return None


@pytest.mark.asyncio
async def test_resposta_vazia_do_portal_vai_para_revisao_sem_tentar_formulario():
    submit = importlib.import_module("adapters.sassepe.submit")

    with pytest.raises(FalhaDeterministica) as erro:
        await submit._buscar_e_selecionar_paciente(_BuscaVaziaPage(), "00000000000")

    assert erro.value.motivo is MotivoFalha.BENEFICIARIO_NAO_ENCONTRADO
    assert erro.value.motivo in MOTIVOS_REQUER_HUMANO
    assert erro.value.motivo not in MOTIVOS_AGENTE
    assert "Nada foi enviado" in erro.value.detalhe
