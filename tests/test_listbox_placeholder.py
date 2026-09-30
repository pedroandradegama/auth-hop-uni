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
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page): return {"estado": "vazio", "opcoes": []}
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        status, relato = await _ui.selecionar_solicitante(
            None, "37499", "RODRIGO REBELLO FRANCA")
        # O portal abriu e respondeu vazio em todos os termos: busca esgotada.
        assert status == "nao_cadastrado"
        assert any("37499" in r and "vazio" in r for r in relato)

    @pytest.mark.asyncio
    async def test_distingue_portal_vazio_de_recusa_nossa(self, monkeypatch):
        """Portal ofereceu nomes e NÓS é que não casamos — diagnóstico oposto."""
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page):
            return {"estado": "ok", "opcoes": ["1111 - OUTRA PESSOA",
                                               "2222 - MAIS ALGUEM"]}
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        status, relato = await _ui.selecionar_solicitante(
            None, "37499", "RODRIGO REBELLO FRANCA")
        assert status == "nao_cadastrado"
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
        src = inspect.getsource(_ui.abrir_dropdown_tipado)
        assert "antes = await _assinatura_listbox(page)" in src
        assert "assinatura_anterior=antes" in src
        assert "MotivoCampo.SEM_RESPOSTA" in src


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
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.SEM_RESPOSTA
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert not r
        assert r.motivo is _ui.MotivoCampo.SEM_RESPOSTA
        assert "nao respondeu" in r.detalhe and "ambulatorial" in r.detalhe

    @pytest.mark.asyncio
    async def test_diz_o_que_o_portal_ofereceu_quando_o_alvo_falta(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page): return {"estado": "ok", "opcoes": ["02 - Hospitalar"]}
        async def _expandir(page, **kw): return ["02 - Hospitalar"]
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "expandir_listbox", _expandir)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert not r
        assert r.motivo is _ui.MotivoCampo.OPCAO_AUSENTE
        assert "02 - Hospitalar" in r.detalhe
        assert "01 - Ambulatorial" in r.detalhe
        assert r.opcoes == ("02 - Hospitalar",)

    @pytest.mark.asyncio
    async def test_distingue_alvo_presente_mas_clique_falho(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page): return {"estado": "ok", "opcoes": ["01 - Ambulatorial"]}
        async def _clicar(page, opt): return False
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "clicar_opcao_listbox", _clicar)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert not r
        assert r.motivo is _ui.MotivoCampo.CLIQUE_SEM_EFEITO
        assert "clique" in r.detalhe

    @pytest.mark.asyncio
    async def test_caminho_feliz_nao_tem_porque(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page): return {"estado": "ok", "opcoes": ["01 - Ambulatorial"]}
        async def _clicar(page, opt): return True
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "clicar_opcao_listbox", _clicar)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert r.ok and r.detalhe == ""

    def test_a_falha_de_campo_fixo_e_tipada(self):
        submit = importlib.import_module("adapters.sassepe.submit")
        corpo = inspect.getsource(submit._preencher_cabecalho)
        assert "_falha_de_campo(page, label, r)" in corpo
        assert '_falha_de_campo(page, "Profissional executante", r)' in corpo


class TestFonteUnicaDeOpcaoReal:
    """29/set: `[cbo] indice=1: 'carregando'` em três ciclos — o robô clicou no
    spinner e gravou lixo no campo obrigatório.

    A causa não foi o filtro estar errado; foi existirem TRÊS cópias do critério
    "o que é opção real" (`_JS_LISTBOX_ESTADO`, `_JS_PRIMEIRA_OPCAO` e o JS
    embutido em `clicar_opcao_listbox`), e as correções de 25 e 28/09 terem
    tocado só uma delas. Agora há um fragmento só; quem precisa de coordenada
    usa o índice que essa leitura já classificou.
    """

    def test_nao_existe_mais_copia_do_criterio(self):
        assert not hasattr(_ui, "_JS_PRIMEIRA_OPCAO")

    def test_o_js_de_coordenada_nao_tem_filtro(self):
        """Se voltar a ter, volta a poder divergir."""
        js = _ui._JS_COORD_POR_INDICE.lower()
        for termo in ("nenhum resultado", "carregando", "loading", "buscando"):
            assert termo not in js

    def test_clicar_opcao_nao_tem_query_proprio(self):
        src = inspect.getsource(_ui.clicar_opcao_listbox)
        assert "querySelectorAll" not in src
        assert "ler_listbox(page)" in src

    @pytest.mark.asyncio
    async def test_clica_a_opcao_real_e_nao_o_placeholder(self):
        """Portal com o spinner em children[0] e a opção real em children[1].
        `_JS_PRIMEIRA_OPCAO` olhava children[0], devolvia o spinner, e o valor
        do campo virava 'carregando'."""
        clicados = []

        class _Page:
            class _Mouse:
                async def click(self, x, y): clicados.append((x, y))
            def __init__(self): self.mouse = self._Mouse()
            async def evaluate(self, js, *a):
                if "viuCarregando" in js:
                    return {"estado": "ok", "opcoes": ["999999 - Nao Informado"],
                            "indices": [1]}
                assert a and a[0] == 1, "clicou no indice do placeholder"
                return {"cx": 7, "cy": 9, "texto": "999999 - Nao Informado"}
            async def wait_for_timeout(self, ms): pass

        texto = await _ui.clicar_primeira_opcao(_Page())
        assert texto == "999999 - Nao Informado"
        assert clicados == [(7, 9)]

    @pytest.mark.asyncio
    async def test_listbox_so_com_placeholder_nao_clica_nada(self):
        class _Page:
            async def evaluate(self, js, *a):
                return {"estado": "carregando", "opcoes": [], "indices": []}
            async def wait_for_timeout(self, ms): pass
        assert await _ui.clicar_primeira_opcao(_Page()) is None


class TestRelatoDosCamposFixos:
    """29/set, job 18982e35: o relato determinístico dizia apenas "Campo fixo
    nao preenchido: Regime de Atendimento" — compatível com quatro causas
    diferentes. `preencher_dropdown_detalhado` passa a dizer qual delas.

    O caso do solicitante consumiu três commits antes de alguém registrar a
    resposta do portal; os campos fixos não tinham registro nenhum.
    """

    @pytest.mark.asyncio
    async def test_diz_quando_o_portal_nao_respondeu_ao_termo(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.SEM_RESPOSTA
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert not r
        assert r.motivo is _ui.MotivoCampo.SEM_RESPOSTA
        assert "nao respondeu" in r.detalhe and "ambulatorial" in r.detalhe

    @pytest.mark.asyncio
    async def test_diz_o_que_o_portal_ofereceu_quando_o_alvo_falta(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page): return {"estado": "ok", "opcoes": ["02 - Hospitalar"]}
        async def _expandir(page, **kw): return ["02 - Hospitalar"]
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "expandir_listbox", _expandir)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert not r
        assert r.motivo is _ui.MotivoCampo.OPCAO_AUSENTE
        assert "02 - Hospitalar" in r.detalhe
        assert "01 - Ambulatorial" in r.detalhe
        assert r.opcoes == ("02 - Hospitalar",)

    @pytest.mark.asyncio
    async def test_distingue_alvo_presente_mas_clique_falho(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page): return {"estado": "ok", "opcoes": ["01 - Ambulatorial"]}
        async def _clicar(page, opt): return False
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "clicar_opcao_listbox", _clicar)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert not r
        assert r.motivo is _ui.MotivoCampo.CLIQUE_SEM_EFEITO
        assert "clique" in r.detalhe

    @pytest.mark.asyncio
    async def test_caminho_feliz_nao_tem_porque(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.OK
        async def _ler(page): return {"estado": "ok", "opcoes": ["01 - Ambulatorial"]}
        async def _clicar(page, opt): return True
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        monkeypatch.setattr(_ui, "ler_listbox", _ler)
        monkeypatch.setattr(_ui, "clicar_opcao_listbox", _clicar)
        r = await _ui.preencher_dropdown_detalhado(
            None, "Regime de Atendimento", "ambulatorial", "01 - Ambulatorial")
        assert r.ok and r.detalhe == ""

    def test_a_falha_de_campo_fixo_e_tipada(self):
        submit = importlib.import_module("adapters.sassepe.submit")
        corpo = inspect.getsource(submit._preencher_cabecalho)
        assert "_falha_de_campo(page, label, r)" in corpo
        assert '_falha_de_campo(page, "Profissional executante", r)' in corpo




class TestCampoNaoVaiMaisParaOAgente:
    """Codex, 29/set: "esses casos convergem para SubmitAbortado e depois para
    ESTADO_INESPERADO, o que aciona o agente indevidamente".

    O agente não retoma do ponto de falha — abre browser novo, re-loga e refaz o
    formulário do zero. Para um dropdown que não respondeu, ele só repete a mesma
    corrida. Custo medido em 24h: 25 fallbacks, 192 passos, US$ 0,96, nenhum job
    recuperado.
    """

    def _falha(self, motivo):
        submit = importlib.import_module("adapters.sassepe.submit")

        class _Page:
            url = "https://sassepe.maida.health/solicitacoes/sp-sadt"
        r = _ui.ResultadoCampo(motivo, "detalhe qualquer")
        return submit._falha_de_campo(_Page(), "Regime de Atendimento", r)

    def test_transitorio_nao_aciona_o_agente_e_pode_reenfileirar(self):
        from agente import MOTIVOS_AGENTE, MotivoFalha
        for motivo in (_ui.MotivoCampo.CAMPO_AUSENTE,
                       _ui.MotivoCampo.SEM_RESPOSTA,
                       _ui.MotivoCampo.RESPOSTA_INCOERENTE,
                       _ui.MotivoCampo.CLIQUE_SEM_EFEITO):
            f = self._falha(motivo)
            assert f.motivo is MotivoFalha.CAMPO_NAO_PREENCHIDO
            assert f.motivo not in MOTIVOS_AGENTE
            assert "seguro reenfileirar" in f.detalhe

    def test_opcao_ausente_e_decisao_humana(self):
        """O portal respondeu e não tem aquele valor. Repetir não resolve."""
        from agente import MOTIVOS_AGENTE, MOTIVOS_REQUER_HUMANO, MotivoFalha
        f = self._falha(_ui.MotivoCampo.OPCAO_AUSENTE)
        assert f.motivo is MotivoFalha.PROCEDIMENTO_INDISPONIVEL
        assert f.motivo not in MOTIVOS_AGENTE
        assert f.motivo in MOTIVOS_REQUER_HUMANO
        assert "seguro reenfileirar" not in f.detalhe

    def test_o_motivo_tipado_aparece_na_mensagem_do_operador(self):
        f = self._falha(_ui.MotivoCampo.RESPOSTA_INCOERENTE)
        assert "[resposta_incoerente]" in f.detalhe
        assert "Regime de Atendimento" in f.detalhe

    def test_a_url_viva_acompanha(self):
        f = self._falha(_ui.MotivoCampo.SEM_RESPOSTA)
        assert f.url.endswith("/solicitacoes/sp-sadt")


class TestListaEstaticaNaoPrecisaMudar:
    """30/set: 'Regime de Atendimento' deu `sem_resposta` em 4 de 4 ciclos.

    Regressão de `a34a30b`, que passou a exigir que a lista MUDASSE depois de
    digitar. Os quatro campos fixos do formulário são listas estáticas curtas
    ("01 - Ambulatorial", "02 - Hospitalar", …) que não filtram por digitação:
    a lista depois é igual à de antes, e a espera nunca terminava. O campo
    funcionava até 23/09 — jobs chegavam a `pos_cabecalho` com os quatro
    preenchidos.

    O critério certo é o de `422f323`: se a lista já CONTÉM o que foi pedido,
    ela responde ao termo. Não precisa mudar.
    """

    ESTATICA = ["01 - Ambulatorial", "02 - Hospitalar", "03 - Domiciliar"]

    def _page(self, opcoes):
        class _Page:
            def __init__(self): self.polls = 0
            async def evaluate(self, js, *a):
                self.polls += 1
                return {"estado": "ok", "opcoes": opcoes,
                        "indices": list(range(len(opcoes)))}
            async def wait_for_timeout(self, ms): pass
        return _Page()

    @pytest.mark.asyncio
    async def test_lista_inalterada_mas_coerente_e_aceita(self):
        page = self._page(self.ESTATICA)
        assert await _ui._esperar_listbox(
            page, 2000, passo_ms=150,
            assinatura_anterior="|".join(self.ESTATICA),
            termo="ambulatorial") is True
        assert page.polls == 1          # aceita de primeira, não espera o teto

    @pytest.mark.asyncio
    async def test_lista_velha_incoerente_continua_rejeitada(self):
        """A proteção de 28/09 não pode ter sido perdida: a busca por '37499'
        devolvia a cabeça alfabética do cadastro, que não contém '37499'."""
        cabeca = ["29278 - AABENMA SILVA RIBEIRO", "245471 - AALAN SOUSA GALIAN"]
        page = self._page(cabeca)
        assert await _ui._esperar_listbox(
            page, 900, passo_ms=150, teto_carregando_ms=900,
            assinatura_anterior="|".join(cabeca), termo="37499") is False

    @pytest.mark.asyncio
    async def test_sem_termo_o_criterio_continua_sendo_a_mudanca(self):
        """Filtro limpo não tem o que conferir; o único sinal é mudar."""
        page = self._page(self.ESTATICA)
        assert await _ui._esperar_listbox(
            page, 900, passo_ms=150, teto_carregando_ms=900,
            assinatura_anterior="|".join(self.ESTATICA), termo=None) is False


class TestCorridaEntreClassificarEClicar:
    """30/set: `[cbo] indice=0: 'carregando'` num ciclo em que a leitura tinha
    classificado uma opção real.

    Entre `ler_listbox` e a medição da coordenada o listbox re-renderiza, e o
    índice passa a apontar para outro elemento — inclusive um placeholder.
    """

    @pytest.mark.asyncio
    async def test_nao_clica_se_o_indice_mudou_de_conteudo(self):
        clicados = []

        class _Page:
            class _Mouse:
                async def click(self, x, y): clicados.append((x, y))
            def __init__(self): self.mouse = self._Mouse()
            async def evaluate(self, js, *a):
                if "viuCarregando" in js:
                    return {"estado": "ok", "opcoes": ["999999 - Nao Informado"],
                            "indices": [1]}
                return {"cx": 3, "cy": 4, "texto": "carregando"}   # re-renderizou
            async def wait_for_timeout(self, ms): pass

        assert await _ui.clicar_primeira_opcao(_Page()) is None
        assert clicados == []

    @pytest.mark.asyncio
    async def test_clica_quando_o_conteudo_confere(self):
        clicados = []

        class _Page:
            class _Mouse:
                async def click(self, x, y): clicados.append((x, y))
            def __init__(self): self.mouse = self._Mouse()
            async def evaluate(self, js, *a):
                if "viuCarregando" in js:
                    return {"estado": "ok", "opcoes": ["999999 - Nao Informado"],
                            "indices": [1]}
                return {"cx": 3, "cy": 4, "texto": "999999 - Nao Informado"}
            async def wait_for_timeout(self, ms): pass

        assert await _ui.clicar_primeira_opcao(_Page()) == "999999 - Nao Informado"
        assert clicados == [(3, 4)]


class TestBuscaEsgotadaNaoVoltaParaAFila:
    """30/set, job 0d4466b9 (ALICE LEÇA VITAL DO CARMO, CRM 42085).

        termo='42085'                    estado='ok'    5 opções, nenhuma é ela
        termo='ALICE LECA VITAL DO CARMO' estado='vazio' 0 opções
        termo='ALICE LECA'                estado='vazio' 0 opções
        termo='ALICE'                     estado='vazio' 0 opções

    O portal respondeu a todos os termos. A médica não está lá. Classificar
    isso como falha transitória faz o job voltar à fila e falhar para sempre,
    sem ninguém ser avisado de que é cadastro.
    """

    @pytest.mark.asyncio
    async def test_termo_transitorio_no_meio_mantem_o_job_reenfileiravel(
            self, monkeypatch):
        """Se UM termo não teve resposta, não dá para afirmar que esgotou."""
        respostas = iter([_ui.MotivoCampo.SEM_RESPOSTA,
                          _ui.MotivoCampo.LISTA_VAZIA,
                          _ui.MotivoCampo.LISTA_VAZIA,
                          _ui.MotivoCampo.LISTA_VAZIA])

        async def _abrir(page, label, termo, indice=0):
            return next(respostas, _ui.MotivoCampo.LISTA_VAZIA)
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        status, _ = await _ui.selecionar_solicitante(
            None, "42085", "ALICE LECA VITAL DO CARMO")
        assert status == "nenhum"

    @pytest.mark.asyncio
    async def test_lista_vazia_em_todos_os_termos_esgota(self, monkeypatch):
        async def _abrir(page, label, termo, indice=0):
            return _ui.MotivoCampo.LISTA_VAZIA
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        status, relato = await _ui.selecionar_solicitante(
            None, "42085", "ALICE LECA VITAL DO CARMO")
        assert status == "nao_cadastrado"
        assert len(relato) == 4          # CRM + 3 variações de nome

    def test_esgotado_vai_para_humano_e_nao_para_o_agente(self):
        from agente import MOTIVOS_AGENTE, MOTIVOS_REQUER_HUMANO, MotivoFalha
        submit = importlib.import_module("adapters.sassepe.submit")
        corpo = inspect.getsource(submit._preencher_cabecalho)
        assert 'if status == "nao_cadastrado":' in corpo
        assert "MotivoFalha.PROCEDIMENTO_INDISPONIVEL" in corpo
        assert MotivoFalha.PROCEDIMENTO_INDISPONIVEL not in MOTIVOS_AGENTE
        assert MotivoFalha.PROCEDIMENTO_INDISPONIVEL in MOTIVOS_REQUER_HUMANO

    def test_lista_vazia_de_campo_tambem_e_humano(self):
        submit = importlib.import_module("adapters.sassepe.submit")
        assert _ui.MotivoCampo.LISTA_VAZIA in submit._MOTIVOS_CAMPO_HUMANO
        assert _ui.MotivoCampo.SEM_RESPOSTA not in submit._MOTIVOS_CAMPO_HUMANO


class TestBuscaComAcento:
    """30/set, job 0d4466b9. O portal guarda acentos — o próprio log traz
    'IVO ALVES DE FRANÇA', 'NÁDIA RAQUEL', 'FLÁVIA MOREIRA'. Nós digitávamos o
    termo normalizado sem acento:

        termo='ALICE LECA VITAL DO CARMO'  -> vazio
        termo='ALICE LECA'                 -> vazio

    O cadastro do job traz 'ALICE LEÇA VITAL DO CARMO'. A normalização existe
    para CASAR o que o portal devolve (tolerância a acento e grafia); aplicá-la
    também ao termo digitado mutila a busca.
    """

    def test_termo_de_busca_preserva_acento(self):
        assert _ui.nome_para_busca("Dra. Alice Leça Vital do Carmo") == \
            "ALICE LEÇA VITAL DO CARMO"

    def test_casamento_continua_sem_acento(self):
        """A tolerância no casamento não pode ter sido perdida."""
        assert _ui.limpar_nome_medico("Dra. Alice Leça Vital do Carmo") == \
            "ALICE LECA VITAL DO CARMO"
        assert _ui.casa_tokens(["ALICE", "LECA"],
                               _ui._norm("42085 - ALICE LEÇA VITAL DO CARMO").split())

    @pytest.mark.asyncio
    async def test_tenta_com_acento_antes_de_sem(self, monkeypatch):
        vistos = []

        async def _abrir(page, label, termo, indice=0):
            vistos.append(termo)
            return _ui.MotivoCampo.LISTA_VAZIA
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        await _ui.selecionar_solicitante(None, "42085", "Alice Leça Vital do Carmo")
        assert vistos[0] == "42085"
        assert "ALICE LEÇA VITAL DO CARMO" in vistos
        assert "ALICE LECA VITAL DO CARMO" in vistos
        assert vistos.index("ALICE LEÇA VITAL DO CARMO") < \
            vistos.index("ALICE LECA VITAL DO CARMO")

    @pytest.mark.asyncio
    async def test_nome_sem_acento_nao_duplica_termos(self, monkeypatch):
        vistos = []

        async def _abrir(page, label, termo, indice=0):
            vistos.append(termo)
            return _ui.MotivoCampo.LISTA_VAZIA
        monkeypatch.setattr(_ui, "abrir_dropdown_tipado", _abrir)
        await _ui.selecionar_solicitante(None, "37499", "RODRIGO REBELLO FRANCA")
        assert len(vistos) == len(set(vistos))
        assert len(vistos) == 4          # CRM + 3 variações do nome


class TestLazyLoadPrecisaChegarAoFim:
    """30/set: `termo='ALICE' apos expandir: opcoes=10` — a lista travou em 10 e
    a expansão não a fez crescer. Um único wheel de 300px não chega ao fim de
    uma lista de 10 linhas, e o portal só pede o lote seguinte quando o scroll
    encosta no fim."""

    def test_o_wheel_procura_o_elemento_que_rola(self):
        js = _ui._JS_WHEEL_LISTBOX
        assert "scrollHeight" in js and "clientHeight" in js

    def test_mais_de_um_evento_e_delta_maior(self):
        js = _ui._JS_WHEEL_LISTBOX
        assert "deltaY: 800" in js
        assert "i < 3" in js


class TestCoerenciaExigeTodosOsTokens:
    """30/set. `opcoes_coerentes` conferia só o primeiro token do termo, e a
    lista da consulta anterior passava quando os dois termos começavam igual:

        termo='ALICE LECA VITAL DO CARMO' estado='ok' opcoes=5:
          ['91762 - ACSA ALICE MARTINS ARAUJO', '91370 - ADRIANA ALICE A DA
            SILVA DE FREITAS', ...]

    É o resultado do termo anterior ('ALICE'). Uma resposta de verdade conteria
    'LECA' também.
    """

    VELHA = ["91762 - ACSA ALICE MARTINS ARAUJO",
             "91370 - ADRIANA ALICE A DA SILVA DE FREITAS"]

    def test_lista_do_termo_anterior_nao_passa(self):
        assert not _ui.opcoes_coerentes(self.VELHA, "ALICE LECA VITAL DO CARMO")

    def test_resposta_de_verdade_passa(self):
        assert _ui.opcoes_coerentes(
            ["42085 - ALICE LEÇA VITAL DO CARMO"], "ALICE LECA VITAL DO CARMO")

    def test_termo_de_um_token_continua_valendo(self):
        assert _ui.opcoes_coerentes(self.VELHA, "ALICE")
        assert _ui.opcoes_coerentes(["42085 - RUBEM PINA"], "42085")

    def test_sobrenome_extra_no_registro_nao_atrapalha(self):
        """'NUBIA ROSA LOPES' ⊂ 'NUBIA ROSA LOPES FREIRE' continua casando."""
        assert _ui.opcoes_coerentes(
            ["2644 - NUBIA ROSA LOPES FREIRE"], "NUBIA ROSA LOPES")


class TestExpandirNaoPodeEncolher:
    """30/set: `opcoes=5` antes, `apos expandir: opcoes=0` depois. O scroll
    derrubou a lista. Devolver o vazio faz o adapter concluir "o portal não
    tem" — o oposto do que ele tinha acabado de mostrar."""

    @pytest.mark.asyncio
    async def test_devolve_a_maior_lista_ja_vista(self):
        leituras = iter([
            {"estado": "ok", "opcoes": ["a1", "a2", "a3"], "indices": [0, 1, 2]},
            {"estado": "ok", "opcoes": [], "indices": []},
            {"estado": "ok", "opcoes": [], "indices": []},
        ])
        ultima = {"estado": "ok", "opcoes": [], "indices": []}

        class _Page:
            async def evaluate(self, js, *a):
                if "WheelEvent" in js:
                    return 0
                return next(leituras, ultima)
            async def wait_for_timeout(self, ms): pass

        opcoes = await _ui.expandir_listbox(_Page(), max_ciclos=2, passo_ms=50,
                                            timeout_ms=100)
        assert opcoes == ["a1", "a2", "a3"]

    @pytest.mark.asyncio
    async def test_crescimento_normal_continua_valendo(self):
        estados = [
            {"estado": "ok", "opcoes": ["a"] * 5, "indices": list(range(5))},
            {"estado": "ok", "opcoes": ["a"] * 10, "indices": list(range(10))},
        ]
        idx = {"i": 0}

        class _Page:
            async def evaluate(self, js, *a):
                if "WheelEvent" in js:
                    idx["i"] = 1
                    return 0
                return estados[idx["i"]]
            async def wait_for_timeout(self, ms): pass

        opcoes = await _ui.expandir_listbox(_Page(), max_ciclos=3, passo_ms=50,
                                            timeout_ms=200)
        assert len(opcoes) == 10
