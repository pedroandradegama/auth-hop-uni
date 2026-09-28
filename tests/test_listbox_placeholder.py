"""Regressão de 28/set/2026: o poll do listbox parava no placeholder de vazio.

`eda1623` (25/set, performance) trocou as esperas fixas de `abrir_dropdown` por
um poll cujo critério de parada era `listbox.children.length > 0`. O portal
SASSEPE renderiza "Nenhum resultado" DENTRO do listbox enquanto a busca ainda
está em voo — então o poll terminava em ~150ms, `_JS_LISTBOX_OPTIONS` descartava
o placeholder, e o adapter concluía que o registro não existe.

Medido no log da VPS, `pos_cpf` até a falha, mesma etapa:

    16–22/set (antes)   23s, 23s, 22s, 47s     4 buscas de verdade
    28/set   (depois)    5s,  6s               4 buscas abortadas

Evidência direta: `diag_FALHA_20260928_111533.png` mostra o campo com "RODRIGO"
e o dropdown em "Nenhum resultado" — para um primeiro nome que o portal
certamente indexa. Consequência mais grave que o solicitante: o MESMO
`abrir_dropdown` serve o dropdown de exames, onde listbox vazio vira
`PROCEDIMENTO_INDISPONIVEL`, ou seja, uma afirmação de que o convênio não cobre
o procedimento.
"""
import importlib
import inspect

import pytest

_ui = importlib.import_module("adapters.sassepe._ui")


class _PageListbox:
    """Portal que pinta o placeholder primeiro e responde depois de N polls."""

    def __init__(self, responde_no_poll: int, opcoes=("37499 - RODRIGO REBELLO FRANCA",)):
        self.responde_no_poll = responde_no_poll
        self.opcoes = list(opcoes)
        self.polls = 0

    async def evaluate(self, js, *a):
        self.polls += 1
        # o adapter só pergunta uma coisa: quais são as opções REAIS
        return self.opcoes if self.polls >= self.responde_no_poll else []

    async def wait_for_timeout(self, ms):
        pass


class TestPlaceholderNaoEncerraAEspera:
    @pytest.mark.asyncio
    async def test_espera_ate_a_resposta_real_chegar(self):
        """Placeholder nos primeiros polls não pode encerrar a espera."""
        page = _PageListbox(responde_no_poll=8)      # ~1,2s
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150) is True
        assert page.polls == 8

    @pytest.mark.asyncio
    async def test_vazio_de_verdade_custa_o_teto_inteiro(self):
        """Sem resposta, o teto é o mesmo que existia antes do poll (2000ms)."""
        page = _PageListbox(responde_no_poll=10**6)
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150) is False
        assert page.polls == 2000 // 150

    @pytest.mark.asyncio
    async def test_sucesso_rapido_continua_rapido(self):
        """O ganho de performance vinha do caso de sucesso — ele fica de pé."""
        page = _PageListbox(responde_no_poll=1)
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150) is True
        assert page.polls == 1


class TestCriterioUnico:
    def test_espera_e_leitura_usam_o_MESMO_js(self):
        """A regressão nasceu de dois critérios divergentes: um contava o
        placeholder como conteúdo, o outro o descartava."""
        src = inspect.getsource(_ui._esperar_listbox)
        assert "_JS_LISTBOX_OPTIONS" in src

    def test_nao_existe_mais_predicado_por_contagem_de_filhos(self):
        """`children.length > 0` só pode sobreviver na docstring que explica a
        regressão — nunca num JS avaliado."""
        assert not hasattr(_ui, "_JS_LISTBOX_PRONTO")
        js = [v for k, v in vars(_ui).items()
              if k.startswith("_JS_") and isinstance(v, str)]
        assert not any("children.length > 0" in j for j in js)

    def test_o_js_descarta_o_placeholder(self):
        assert "nenhum resultado" in _ui._JS_LISTBOX_OPTIONS.lower()


class TestEvidenciaChegaAoHop:
    """A tela mostrava 'EVIDÊNCIAS DO ROBÔ []' para uma falha que TINHA print.

    `_diag` gravava a imagem em disco e não a devolvia; as três saídas de falha
    do worker mandavam `evidencias: []` cravado. O operador via só o texto — e
    o texto, naquele caso, era um diagnóstico de agente que estava errado.
    """

    def test_diag_devolve_o_caminho(self):
        submit = importlib.import_module("adapters.sassepe.submit")
        assert "return caminho" in inspect.getsource(submit._diag)

    def test_url_na_falha_carrega_o_screenshot(self):
        submit = importlib.import_module("adapters.sassepe.submit")
        e = submit._UrlNaFalha("https://x/y", "/tmp/diag_FALHA.png")
        assert e.url == "https://x/y"
        assert e.screenshot == "/tmp/diag_FALHA.png"

    def test_worker_monta_evidencia_a_partir_da_falha(self):
        from agente import FalhaDeterministica, MotivoFalha
        worker = importlib.import_module("worker")
        f = FalhaDeterministica(
            motivo=MotivoFalha.ESTADO_INESPERADO, etapa="submit_sassepe",
            detalhe="Profissional solicitante nao localizado",
            screenshot_path="/opt/.../diag_FALHA_20260928_111533.png")
        ev = worker._evidencias_da_falha(f)
        assert len(ev) == 1
        assert ev[0]["screenshot_path"].endswith("diag_FALHA_20260928_111533.png")
        assert ev[0]["etapa"] == "submit_sassepe"

    def test_sem_screenshot_nao_inventa_evidencia(self):
        from agente import FalhaDeterministica, MotivoFalha
        worker = importlib.import_module("worker")
        f = FalhaDeterministica(motivo=MotivoFalha.REDE, etapa="x")
        assert worker._evidencias_da_falha(f) == []
