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
    """Portal que pinta placeholder primeiro e responde depois de N polls.

    `estado_inicial` e' o que o listbox mostra enquanto a busca esta' em voo:
    'carregando' (spinner, visto em 28/09 17:55) ou 'fechado'.
    """

    def __init__(self, responde_no_poll: int, estado_inicial="carregando",
                 opcoes=("37499 - RODRIGO REBELLO FRANCA",)):
        self.responde_no_poll = responde_no_poll
        self.estado_inicial = estado_inicial
        self.opcoes = list(opcoes)
        self.polls = 0

    async def evaluate(self, js, *a):
        self.polls += 1
        if self.polls >= self.responde_no_poll:
            return {"estado": "ok", "opcoes": self.opcoes}
        return {"estado": self.estado_inicial, "opcoes": []}

    async def wait_for_timeout(self, ms):
        pass


class TestPlaceholderNaoEncerraAEspera:
    @pytest.mark.asyncio
    async def test_espera_ate_a_resposta_real_chegar(self):
        page = _PageListbox(responde_no_poll=8)      # ~1,2s de spinner
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150) is True
        assert page.polls == 8

    @pytest.mark.asyncio
    async def test_spinner_renova_a_paciencia_ate_o_teto(self):
        """"carregando" e' evidencia de que o portal esta' trabalhando. Parar
        nele e' concluir "nao existe" sem ter visto a resposta — foi o que
        aconteceu em 28/09 (4 buscas em 6s)."""
        page = _PageListbox(responde_no_poll=60, estado_inicial="carregando")
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150,
                                          teto_carregando_ms=12000) is True
        assert page.polls == 60                      # ~9s de espera, nao 2s

    @pytest.mark.asyncio
    async def test_spinner_eterno_para_no_teto_absoluto(self):
        page = _PageListbox(responde_no_poll=10**6, estado_inicial="carregando")
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150,
                                          teto_carregando_ms=3000) is False
        assert page.polls <= 3000 // 150 + 1

    @pytest.mark.asyncio
    async def test_vazio_estavel_encerra_cedo(self):
        """"Nenhum resultado" e' resposta terminal: nao faz sentido esperar o
        teto. Mas so' vale depois de estavel — o portal mostra o vazio da busca
        ANTERIOR por alguns frames antes de trocar pelo spinner."""
        page = _PageListbox(responde_no_poll=10**6, estado_inicial="vazio")
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150) is False
        assert page.polls == _ui._VAZIO_ESTAVEL

    @pytest.mark.asyncio
    async def test_vazio_transitorio_nao_encerra(self):
        """vazio -> carregando -> ok: o vazio do inicio nao pode decidir."""
        class _Page:
            def __init__(self): self.polls = 0
            async def evaluate(self, js, *a):
                self.polls += 1
                if self.polls <= 2:  return {"estado": "vazio", "opcoes": []}
                if self.polls <= 10: return {"estado": "carregando", "opcoes": []}
                return {"estado": "ok", "opcoes": ["37499 - RODRIGO"]}
            async def wait_for_timeout(self, ms): pass
        page = _Page()
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150) is True
        assert page.polls == 11

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
        assert "ler_listbox(page)" in src

    def test_nao_existe_mais_predicado_por_contagem_de_filhos(self):
        """`children.length > 0` só pode sobreviver na docstring que explica a
        regressão — nunca num JS avaliado."""
        assert not hasattr(_ui, "_JS_LISTBOX_PRONTO")
        assert not hasattr(_ui, "_JS_LISTBOX_OPTIONS")
        js = [v for k, v in vars(_ui).items()
              if k.startswith("_JS_") and isinstance(v, str)]
        assert not any("children.length > 0" in j for j in js)

    def test_o_js_descarta_o_placeholder(self):
        assert "nenhum resultado" in _ui._JS_LISTBOX_ESTADO.lower()

    def test_o_js_descarta_o_spinner(self):
        """Segundo placeholder, achado em 28/09 17:55: contado como opcao, ele
        encerrava a espera com 1 'candidato' que nunca casaria."""
        assert "carregando" in _ui._JS_LISTBOX_ESTADO.lower()


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


class TestRelatoDoPortal:
    """Três ciclos (25–28/09) foram gastos adivinhando o que o dropdown tinha
    respondido, porque a falha dizia só "não localizado". O adapter passa a
    registrar, por termo, o estado e as opções que o portal ofereceu."""

    @pytest.mark.asyncio
    async def test_nenhum_devolve_o_relato_por_termo(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0): return True
        async def _ler(page): return {"estado": "vazio", "opcoes": []}
        monkeypatch.setattr(_ui, "abrir_dropdown", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        status, relato = await _ui.selecionar_solicitante(
            None, "37499", "RODRIGO REBELLO FRANCA")
        assert status == "nenhum"
        assert any("37499" in r and "vazio" in r for r in relato)

    @pytest.mark.asyncio
    async def test_distingue_portal_vazio_de_recusa_nossa(self, monkeypatch):
        """Portal ofereceu nomes e NÓS é que não casamos — diagnóstico oposto."""
        async def _abrir(page, label, termo, indice=0): return True
        async def _ler(page):
            return {"estado": "ok", "opcoes": ["1111 - OUTRA PESSOA",
                                               "2222 - MAIS ALGUEM"]}
        monkeypatch.setattr(_ui, "abrir_dropdown", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        status, relato = await _ui.selecionar_solicitante(
            None, "37499", "RODRIGO REBELLO FRANCA")
        assert status == "nenhum"
        assert any("nenhuma casou" in r for r in relato)
        assert any("OUTRA PESSOA" in r for r in relato)

    def test_a_mensagem_do_operador_carrega_o_relato(self):
        submit = importlib.import_module("adapters.sassepe.submit")
        corpo = inspect.getsource(submit._preencher_cabecalho)
        assert "O QUE O PORTAL RESPONDEU" in corpo


class TestListaVelhaNaoContaComoResposta:
    """Log de 28/09: as buscas por '37499', 'RODRIGO REBELLO FRANCA' e
    'RODRIGO REBELLO' devolveram as MESMAS cinco linhas — a cabeça alfabética do
    cadastro (AABENMA, AALAN, AALEC, AARAO, AARAO), ou seja, a lista sem filtro.
    São opções reais, então passavam por 'ok' e encerravam a espera.

    Efeito: a busca por CRM, a mais específica, era descartada em toda execução,
    e o adapter decidia sempre pelo termo mais fraco (primeiro nome sozinho) —
    que funcionou por acaso de tempo. Com dois homônimos, daria ambíguo ou
    casamento errado de solicitante, que é violação do I3.
    """

    CABECA = ["29278 - AABENMA SILVA RIBEIRO", "245471 - AALAN SOUSA GALIAN"]

    @pytest.mark.asyncio
    async def test_lista_identica_a_anterior_nao_encerra_a_espera(self):
        class _Page:
            def __init__(self): self.polls = 0
            async def evaluate(self, js, *a):
                self.polls += 1
                return {"estado": "ok",
                        "opcoes": TestListaVelhaNaoContaComoResposta.CABECA}
            async def wait_for_timeout(self, ms): pass
        page = _Page()
        assinatura = "|".join(self.CABECA)
        assert await _ui._esperar_listbox(page, 2000, passo_ms=150,
                                          teto_carregando_ms=2000,
                                          assinatura_anterior=assinatura) is False
        assert page.polls > 1

    @pytest.mark.asyncio
    async def test_aceita_assim_que_a_lista_muda(self):
        class _Page:
            def __init__(self): self.polls = 0
            async def evaluate(self, js, *a):
                self.polls += 1
                if self.polls < 5:
                    return {"estado": "ok",
                            "opcoes": TestListaVelhaNaoContaComoResposta.CABECA}
                return {"estado": "ok", "opcoes": ["37499 - RODRIGO REBELLO FRANCA"]}
            async def wait_for_timeout(self, ms): pass
        page = _Page()
        assert await _ui._esperar_listbox(
            page, 2000, passo_ms=150,
            assinatura_anterior="|".join(self.CABECA)) is True
        assert page.polls == 5

    @pytest.mark.asyncio
    async def test_sem_assinatura_anterior_qualquer_lista_serve(self):
        """Primeira abertura, ou termo vazio (a lista sem filtro É a resposta)."""
        class _Page:
            async def evaluate(self, js, *a):
                return {"estado": "ok",
                        "opcoes": TestListaVelhaNaoContaComoResposta.CABECA}
            async def wait_for_timeout(self, ms): pass
        assert await _ui._esperar_listbox(_Page(), 2000, passo_ms=150) is True

    def test_abrir_dropdown_reprova_o_termo_sem_resposta(self):
        """Ler o listbox depois disso devolveria conteúdo que não corresponde ao
        que foi pedido — e quem lê não tem como saber."""
        src = inspect.getsource(_ui.abrir_dropdown)
        assert "antes = await _assinatura_listbox(page)" in src
        assert "assinatura_anterior=antes" in src
        assert "return False" in src
