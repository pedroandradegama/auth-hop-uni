"""Casamento do nome do medico solicitante tolerante a erro de grafia.

Caso que motivou (14/09/2026, job 37e3d344): o pedido trazia
'Waldete calvacanti' (OCR de manuscrito) e o portal Sassepe tinha
'2644 - WALDETE AMARAL PEREIRA CAVALCANTI'. A busca por CRM funcionou e a opcao
certa estava na lista; o token-match EXATO e' que recusou, por uma transposicao
de letras. O job virou requer_humano sem necessidade.

Estas funcoes sao puras — testam a regra sem subir browser.
"""
import importlib

_ui = importlib.import_module("adapters.sassepe._ui")


class TestCasaTokens:
    def test_exato_continua_valendo(self):
        assert _ui.casa_tokens(["NUBIA", "ROSA"], ["NUBIA", "ROSA", "LOPES"])

    def test_sobrenome_extra_no_registro_e_tolerado(self):
        # regra antiga, preservada: buscado ⊂ registro
        assert _ui.casa_tokens(
            ["NUBIA", "ROSA", "LOPES"], ["NUBIA", "ROSA", "LOPES", "FREIRE"])

    def test_sem_fuzzy_a_transposicao_reprova(self):
        assert not _ui.casa_tokens(
            ["WALDETE", "CALVACANTI"],
            ["WALDETE", "AMARAL", "PEREIRA", "CAVALCANTI"])

    def test_com_fuzzy_a_transposicao_passa(self):
        assert _ui.casa_tokens(
            ["WALDETE", "CALVACANTI"],
            ["WALDETE", "AMARAL", "PEREIRA", "CAVALCANTI"],
            _ui.LIMIAR_FUZZY)

    def test_fuzzy_nao_aproxima_pessoas_diferentes(self):
        # MACEDO x MACHADO = 0.77, abaixo do limiar
        assert not _ui.casa_tokens(
            ["MARIA", "MACEDO"], ["MARIA", "MACHADO"], _ui.LIMIAR_FUZZY)

    def test_token_curto_exige_exato(self):
        # LUZ x CRUZ passaria de 0.86 no ratio; token curto nao pode usar fuzzy
        assert not _ui.casa_tokens(["ANA", "LUZ"], ["ANA", "CRUZ"],
                                   _ui.LIMIAR_FUZZY)

    def test_lista_vazia_de_tokens_nao_casa(self):
        assert not _ui.casa_tokens([], ["QUALQUER", "COISA"], _ui.LIMIAR_FUZZY)


class TestFiltrarCandidatos:
    OPCOES = [
        "2644 - WALDETE AMARAL PEREIRA CAVALCANTI",
        "2645 - WALDETE SOUZA MACHADO",
    ]

    def test_caso_real_exato_nao_acha(self):
        assert _ui.filtrar_candidatos(self.OPCOES, ["WALDETE", "CALVACANTI"]) == []

    def test_caso_real_fuzzy_acha_um_so(self):
        achados = _ui.filtrar_candidatos(
            self.OPCOES, ["WALDETE", "CALVACANTI"], _ui.LIMIAR_FUZZY)
        assert achados == ["2644 - WALDETE AMARAL PEREIRA CAVALCANTI"]

    def test_homonimo_continua_ambiguo(self):
        # I3: buscar so' pelo primeiro nome tem que devolver os DOIS, para o
        # chamador abortar em vez de escolher.
        achados = _ui.filtrar_candidatos(self.OPCOES, ["WALDETE"],
                                         _ui.LIMIAR_FUZZY)
        assert len(achados) == 2

    def test_opcao_sem_hifen_nao_quebra(self):
        assert _ui.filtrar_candidatos(["MARIA DA PIEDADE REVOREDO DE MACEDO"],
                                      ["MARIA", "PIEDADE"]) == \
            ["MARIA DA PIEDADE REVOREDO DE MACEDO"]

    def test_ordem_preservada_e_sem_repetidas(self):
        opcoes = ["1 - ANA PAULA SILVA", "1 - ANA PAULA SILVA", "2 - ANA PAULA SOUZA"]
        achados = _ui.filtrar_candidatos(opcoes, ["ANA", "PAULA"])
        assert achados == ["1 - ANA PAULA SILVA", "2 - ANA PAULA SOUZA"]


class TestMensagemSemCrm:
    """Sem CRM, a mensagem tem que dizer QUE falta o CRM.

    18/set: dois jobs abortaram com "Profissional solicitante 'X' nao localizado
    no dropdown" — mensagem que faz o operador procurar defeito no robô. A causa
    provável é outra: o job chegou sem `medico_solicitante_crm`, e o portal
    indexa o solicitante por CRM (lazy-load de ~10 itens em ordem alfabética).
    """

    def _msg(self, crm, medico="RICARDO JOSE LISBOA LYRA"):
        sem_crm = not (crm or "").strip()
        return (f"Profissional solicitante '{medico}' nao localizado no dropdown"
                + (" — o job veio SEM CRM, e o portal indexa o solicitante por CRM; "
                   "a busca so' por nome e' fragil. Resolver o CRM deste medico no "
                   "cadastro/HOP."
                   if sem_crm else f" (buscado por CRM {crm})."))

    def test_sem_crm_a_mensagem_aponta_o_cadastro(self):
        m = self._msg(None)
        assert "SEM CRM" in m and "cadastro/HOP" in m

    def test_com_crm_a_mensagem_mostra_o_que_foi_buscado(self):
        m = self._msg("16188")
        assert "buscado por CRM 16188" in m
        assert "SEM CRM" not in m

    def test_string_vazia_conta_como_sem_crm(self):
        assert "SEM CRM" in self._msg("   ")

    def test_o_texto_do_adapter_bate_com_o_testado(self):
        """Guarda contra a mensagem do submit.py divergir deste teste."""
        import io
        src = io.open("adapters/sassepe/submit.py", encoding="utf-8").read()
        assert "o job veio SEM CRM" in src
        assert "buscado por CRM" in src
