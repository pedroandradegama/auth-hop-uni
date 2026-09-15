"""Codigo que o portal do convenio nao oferece nao e' erro tecnico.

Caso real (15/09/2026): os jobs 37e3d344 e ab04673a abortaram porque o Sassepe
nao tem 40901360 (Doppler de carotidas) nem 40901211 (estruturas superficiais)
na tabela 22 — ambos TUSS 202605 vigentes, mapeamento correto do nosso lado.

Antes, isso virava ESTADO_INESPERADO e acionava o agente, que gastou US$ 0,02 e
concluiu tres vezes que "a rota /workspace/solicitacoes do portal mudou" — com o
robo ja dentro do formulario, tendo adicionado exames. Diagnostico falso e caro.

Agora vai direto para revisao humana: quem decide trocar o codigo, tirar o exame
do pedido ou autorizar por outro canal e' uma pessoa.
"""
import contextlib
import importlib

import pytest

from agente import (FalhaDeterministica, MotivoFalha,
                    MOTIVOS_AGENTE, MOTIVOS_REQUER_HUMANO)


class _FakePage:
    url = "https://sassepe.maida.health/solicitacoes/sp-sadt"


def _fake_navegador():
    @contextlib.asynccontextmanager
    async def _nav():
        yield _FakePage()
    return _nav


async def _noop(*a, **k):
    return None


class TestClassificacao:
    def test_nao_aciona_agente(self):
        assert MotivoFalha.PROCEDIMENTO_INDISPONIVEL not in MOTIVOS_AGENTE

    def test_vai_para_revisao_humana(self):
        assert MotivoFalha.PROCEDIMENTO_INDISPONIVEL in MOTIVOS_REQUER_HUMANO

    def test_waf_captcha_tambem(self):
        """O comentario em tipos.py sempre disse 'requer_humano direto'; ate'
        agora o worker devolvia erro_submit. Alinhado."""
        assert MotivoFalha.WAF_CAPTCHA in MOTIVOS_REQUER_HUMANO

    def test_estado_inesperado_continua_indo_ao_agente(self):
        assert MotivoFalha.ESTADO_INESPERADO in MOTIVOS_AGENTE
        assert MotivoFalha.ESTADO_INESPERADO not in MOTIVOS_REQUER_HUMANO


class TestAdapterSassepe:
    @pytest.mark.asyncio
    async def test_listbox_vazio_vira_procedimento_indisponivel(self, monkeypatch):
        submit = importlib.import_module("adapters.sassepe.submit")
        sessao = importlib.import_module("adapters.sassepe.sessao")
        monkeypatch.setattr(sessao, "navegador", _fake_navegador())
        monkeypatch.setattr(sessao, "login", _noop)
        for passo in ("_abrir_sp_sadt", "_buscar_e_selecionar_paciente",
                      "_preencher_cabecalho", "_diag", "_snap"):
            monkeypatch.setattr(submit, passo, _noop)

        async def _sem_codigo(page, codigo, qty):
            return False, (f"Codigo '{codigo}' nao encontrado no portal "
                           f"(tabela 22, listbox vazio).")
        monkeypatch.setattr(submit, "_adicionar_exame", _sem_codigo)

        job = {"cpf": "03441014448", "medico": "2644 WALDETE",
               "codigos": [{"codigo_tuss": "40901360"}],
               "arquivos": ["/x"], "paciente_nome": "X"}
        with pytest.raises(FalhaDeterministica) as ei:
            await submit.executar(job)
        assert ei.value.motivo == MotivoFalha.PROCEDIMENTO_INDISPONIVEL
        assert "40901360" in ei.value.detalhe
        assert "nao oferece" in ei.value.detalhe

    @pytest.mark.asyncio
    async def test_outra_falha_de_exame_continua_indo_ao_agente(self, monkeypatch):
        """Opcao existente que nao casou e' problema NOSSO — ali o agente ajuda."""
        submit = importlib.import_module("adapters.sassepe.submit")
        sessao = importlib.import_module("adapters.sassepe.sessao")
        monkeypatch.setattr(sessao, "navegador", _fake_navegador())
        monkeypatch.setattr(sessao, "login", _noop)
        for passo in ("_abrir_sp_sadt", "_buscar_e_selecionar_paciente",
                      "_preencher_cabecalho", "_diag", "_snap"):
            monkeypatch.setattr(submit, passo, _noop)

        async def _nao_casou(page, codigo, qty):
            return False, (f"Codigo '{codigo}' nao casou com nenhuma opcao. "
                           f"Portal ofereceu 3: A; B; C")
        monkeypatch.setattr(submit, "_adicionar_exame", _nao_casou)

        job = {"cpf": "03441014448", "medico": "2644 WALDETE",
               "codigos": [{"codigo_tuss": "40901360"}],
               "arquivos": ["/x"], "paciente_nome": "X"}
        with pytest.raises(FalhaDeterministica) as ei:
            await submit.executar(job)
        assert ei.value.motivo == MotivoFalha.ESTADO_INESPERADO


def test_placeholder_nao_conta_como_opcao():
    """O 'Nenhum resultado' do portal e' estado vazio renderizado dentro do
    listbox. Contado como opcao, o erro dizia 'portal ofereceu 1: Nenhum
    resultado' — o oposto do que ocorreu."""
    _ui = importlib.import_module("adapters.sassepe._ui")
    assert "nenhum resultado" in _ui._JS_LISTBOX_OPTIONS.lower()
    assert "vazio(t)" in _ui._JS_LISTBOX_OPTIONS
