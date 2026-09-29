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


class TestLazyLoadEsperado:
    """29/set: a falha migrou para o executante fixo ('21798 - PEDRO ANDRADE').

    O listbox entrega ~5 itens e só carrega o resto sob WheelEvent no próprio
    elemento. O piloto manual já documentava que, buscando '21798', o alvo é o
    6º item. Antes de `eda1623` a espera pós-wheel era `wait_for_timeout(800)`,
    que dava tempo do lote seguinte chegar; o poll que a substituiu retornava na
    hora (já havia opções) e a lista travava nos 5 primeiros.
    """

    class _PageLazy:
        """Cada WheelEvent acrescenta um lote de 5."""

        def __init__(self, total=12):
            self.total = total
            self.carregados = 5
            self.wheels = 0

        async def evaluate(self, js, *a):
            if "WheelEvent" in js:
                self.wheels += 1
                self.carregados = min(self.total, self.carregados + 5)
                return None
            return {"estado": "ok",
                    "opcoes": [f"21798 - MEDICO {i}" for i in range(self.carregados)]}

        async def wait_for_timeout(self, ms):
            pass

    @pytest.mark.asyncio
    async def test_expande_ate_a_lista_parar_de_crescer(self):
        page = self._PageLazy(total=12)
        opcoes = await _ui.expandir_listbox(page, max_ciclos=6, passo_ms=50,
                                            timeout_ms=200)
        assert len(opcoes) == 12

    @pytest.mark.asyncio
    async def test_para_de_rodar_quando_a_lista_esta_completa(self):
        """Lista que já veio inteira não paga ciclos extras."""
        page = self._PageLazy(total=5)
        await _ui.expandir_listbox(page, max_ciclos=6, passo_ms=50, timeout_ms=200)
        assert page.wheels == 1

    @pytest.mark.asyncio
    async def test_respeita_o_teto_de_ciclos(self):
        page = self._PageLazy(total=10**6)
        await _ui.expandir_listbox(page, max_ciclos=3, passo_ms=50, timeout_ms=200)
        assert page.wheels == 3

    def test_preencher_dropdown_expande_quando_o_alvo_nao_esta_na_lista(self):
        src = inspect.getsource(_ui.preencher_dropdown_detalhado)
        assert "_opcao_presente" in src
        assert "expandir_listbox" in src

    def test_opcao_presente_usa_o_mesmo_criterio_do_clique(self):
        opcoes = ["21798 - PEDRO ANDRADE GAMA DE OLIVEIRA", "21798 - OUTRO"]
        assert _ui._opcao_presente(opcoes, "21798 - PEDRO ANDRADE GAMA DE OLIVEIRA")
        assert _ui._opcao_presente(opcoes, "PEDRO ANDRADE")
        assert not _ui._opcao_presente(opcoes, "MARIA")


class TestCoerenciaComOTermo:
    """29/set, job 0d4466b9: buscas por '42085', 'ALICE LECA VITAL DO CARMO' e
    'ALICE LECA' devolveram as MESMAS cinco linhas (RUBEM, RICARDO, ELAINE,
    DIEGO, DANIEL) — lista filtrada por CRM entregue como resposta a uma busca
    por nome. "A lista mudou" não pega isso quando a assinatura anterior não
    pôde ser lida (listbox fechado no instante da leitura)."""

    CRM = ["42085 - RUBEM PINA DOMINGUES", "42085 - RICARDO PEDRO LOTTI"]

    def test_lista_de_crm_nao_responde_busca_por_nome(self):
        assert not _ui.opcoes_coerentes(self.CRM, "ALICE LECA VITAL DO CARMO")

    def test_lista_de_crm_responde_busca_por_crm(self):
        assert _ui.opcoes_coerentes(self.CRM, "42085")

    def test_acento_nao_derruba_a_coerencia(self):
        assert _ui.opcoes_coerentes(["37499 - RODRIGO REBELLO FRANÇA"],
                                    "RODRIGO REBELLO FRANCA")

    @pytest.mark.asyncio
    async def test_poll_nao_aceita_lista_incompativel_com_o_termo(self):
        class _Page:
            def __init__(self): self.polls = 0
            async def evaluate(self, js, *a):
                self.polls += 1
                return {"estado": "ok",
                        "opcoes": TestCoerenciaComOTermo.CRM}
            async def wait_for_timeout(self, ms): pass
        page = _Page()
        assert await _ui._esperar_listbox(page, 900, passo_ms=150,
                                          teto_carregando_ms=900,
                                          termo="ALICE LECA") is False


class TestRelatoDosCamposFixos:
    """29/set, job 18982e35: o relato determinístico dizia apenas "Campo fixo
    nao preenchido: Regime de Atendimento" — compatível com quatro causas
    diferentes. `preencher_dropdown_detalhado` passa a dizer qual delas.

    O caso do solicitante consumiu três commits antes de alguém registrar a
    resposta do portal; os campos fixos não tinham registro nenhum.
    """

    @pytest.mark.asyncio
    async def test_diz_quando_o_portal_nao_respondeu_ao_termo(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0): return False
        monkeypatch.setattr(_ui, "abrir_dropdown", _abrir)
        ok, porque = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert ok is False
        assert "nao respondeu" in porque and "ambulatorial" in porque

    @pytest.mark.asyncio
    async def test_diz_o_que_o_portal_ofereceu_quando_o_alvo_falta(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0): return True
        async def _ler(page): return {"estado": "ok", "opcoes": ["02 - Hospitalar"]}
        async def _expandir(page, **kw): return ["02 - Hospitalar"]
        monkeypatch.setattr(_ui, "abrir_dropdown", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "expandir_listbox", _expandir)
        ok, porque = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert ok is False
        assert "02 - Hospitalar" in porque
        assert "01 - Ambulatorial" in porque

    @pytest.mark.asyncio
    async def test_distingue_alvo_presente_mas_clique_falho(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0): return True
        async def _ler(page): return {"estado": "ok", "opcoes": ["01 - Ambulatorial"]}
        async def _clicar(page, opt): return False
        monkeypatch.setattr(_ui, "abrir_dropdown", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "clicar_opcao_listbox", _clicar)
        ok, porque = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert ok is False
        assert "clique" in porque

    @pytest.mark.asyncio
    async def test_caminho_feliz_nao_tem_porque(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0): return True
        async def _ler(page): return {"estado": "ok", "opcoes": ["01 - Ambulatorial"]}
        async def _clicar(page, opt): return True
        monkeypatch.setattr(_ui, "abrir_dropdown", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "clicar_opcao_listbox", _clicar)
        ok, porque = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert ok is True and porque == ""

    def test_a_falha_de_campo_fixo_carrega_o_motivo(self):
        submit = importlib.import_module("adapters.sassepe.submit")
        corpo = inspect.getsource(submit._preencher_cabecalho)
        assert 'f"Campo fixo nao preenchido: {label} — {porque}."' in corpo
        assert "Profissional executante fixo nao localizado — {porque}" in corpo
