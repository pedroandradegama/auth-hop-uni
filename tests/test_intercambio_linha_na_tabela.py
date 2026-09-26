"""A prova de que o procedimento entrou é o CÓDIGO ESTAR NA TABELA.

Incidente (25/set, job fc58a7e9, 26 exames no Unimed Intercâmbio): o adapter
reportou 13 códigos como "nao entrou na tabela de Procedimentos apos clicar
Adicionar (2 tentativas)" e abortou o envio pelo hard-stop.

O screenshot do portal no momento da falha mostra os 13 NA TABELA, com
quantidade 1. A guia estava correta e foi descartada — mandada para revisão
humana por um falso negativo. O job levou 18 minutos para chegar a essa
conclusão errada.

A verificação antiga comparava número de linhas antes/depois, o que quebra com
postback do ASP.NET ainda não refletido no DOM, tabela aninhada casando no
seletor e paginação do grid. A presença do código não quebra com nenhum dos três.
"""
import importlib
import inspect

submit = importlib.import_module("adapters.unimed_intercambio.submit")


class TestVerificacaoPorPresenca:
    @property
    def src(self):
        return inspect.getsource(submit.adicionar_item_procedimento)

    def test_nao_conta_mais_linhas(self):
        assert "_contar_linhas_tabela_procedimentos" not in self.src
        assert "linhas_depois <= linhas_antes" not in self.src

    def test_procura_o_codigo_na_tabela(self):
        assert "_procedimento_na_tabela" in self.src
        assert "cels.includes(cod)" in self.src

    def test_espera_o_postback_em_vez_de_ler_estado_velho(self):
        assert "_esperar_na_tabela" in self.src

    def test_mensagem_de_erro_cita_a_ausencia_e_nao_a_contagem(self):
        assert "nao aparece na tabela" in self.src

    def test_alerta_do_portal_entra_no_detalhe(self):
        """'Digite os dados obrigatórios' distingue campo vazio de postback lento."""
        assert "Digite os dados obrigatorios" in self.src

    def test_duplicata_e_barrada(self):
        """Se o código já estava lá antes do clique, não dá para afirmar que
        este clique o adicionou — e procedimento duplicado na guia é
        irreversível depois do envio (I1)."""
        assert "ja_estava" in self.src
        assert "possivel duplicata" in self.src


class TestHardStopPreservado:
    def test_qualquer_falha_ainda_aborta(self):
        """A correção mira o falso negativo, não o hard-stop: uma falha real
        continua impedindo guia parcial."""
        src = inspect.getsource(submit.adicionar_todos_procedimentos)
        assert "erros.append" in src
        assert "return erros" in src
