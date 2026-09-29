"""O diagnóstico do agente não pode ocupar o lugar do relato determinístico.

Incidente de 29/set/2026 (job do MAYLON WELLIK, mamografia 40808041): a tela
"Submissão ao convênio" mostrava, como causa raiz, que o campo de CPF do portal
"não se torna interativo dentro de 12 segundos", com três hipóteses para o
operador (indisponibilidade, rate-limit/WAF, mudança estrutural da página).

Isso é o relato da tentativa de RECUPERAÇÃO: o agente reconstrói o formulário do
zero numa page nova e falhou no primeiro campo. O que o robô determinístico fez
e onde parou foi descartado — `_mapear_resultado_agente` devolvia
`mensagem = res.diagnostico` e `evidencias: []`.

Efeito: o operador perde a única frase verificada e age sobre hipótese. Nos
casos de 28/09 isso mandou abrir chamado com o SASSEPE para credenciar um médico
que estava cadastrado o tempo todo.
"""
import importlib

from agente import FalhaDeterministica, MotivoFalha, ResultadoStatus

worker = importlib.import_module("worker")


class _ResAgente:
    def __init__(self, status, diagnostico, protocolo=None):
        self.status = status
        self.diagnostico = diagnostico
        self.protocolo = protocolo


FALHA = FalhaDeterministica(
    motivo=MotivoFalha.ESTADO_INESPERADO,
    etapa="submit_sassepe",
    detalhe="Profissional executante fixo nao localizado.",
    url="https://sassepe.maida.health/solicitacoes/sp-sadt",
    screenshot_path="/opt/.../diag_FALHA_20260929_071500.png",
)


class TestOrdemDaVerdade:
    def test_relato_deterministico_vem_primeiro(self):
        res = _ResAgente(ResultadoStatus.REQUER_HUMANO,
                         "O campo de CPF nao fica interativo em 12s.")
        out = worker._mapear_resultado_agente(res, FALHA)
        msg = out["mensagem"]
        assert msg.index("RELATO DO ROBO DETERMINISTICO") < msg.index("HIPOTESE DO AGENTE")

    def test_o_relato_carrega_etapa_e_url(self):
        res = _ResAgente(ResultadoStatus.REQUER_HUMANO, "qualquer coisa")
        msg = worker._mapear_resultado_agente(res, FALHA)["mensagem"]
        assert "Profissional executante fixo nao localizado." in msg
        assert "submit_sassepe" in msg
        assert "/solicitacoes/sp-sadt" in msg

    def test_hipotese_do_agente_e_rotulada_como_nao_verificada(self):
        res = _ResAgente(ResultadoStatus.REQUER_HUMANO, "rate-limit do portal")
        msg = worker._mapear_resultado_agente(res, FALHA)["mensagem"]
        assert "nao verificada" in msg
        assert "rate-limit do portal" in msg

    def test_evidencia_sobrevive_ao_agente(self):
        """`evidencias: []` cravado apagava o screenshot mesmo depois de 0c1e59d,
        porque o resultado do agente substituía o dict inteiro."""
        res = _ResAgente(ResultadoStatus.REQUER_HUMANO, "x")
        out = worker._mapear_resultado_agente(res, FALHA)
        assert out["evidencias"][0]["screenshot_path"].endswith(
            "diag_FALHA_20260929_071500.png")

    def test_sucesso_do_agente_nao_ganha_preambulo(self):
        res = _ResAgente(ResultadoStatus.CONCLUIDO, "Protocolo capturado.",
                         protocolo="123456")
        out = worker._mapear_resultado_agente(res, FALHA)
        assert out["status"] == "protocolado"
        assert out["numero_protocolo"] == "123456"
        assert "HIPOTESE DO AGENTE" not in out["mensagem"]

    def test_sem_falha_o_contrato_antigo_vale(self):
        res = _ResAgente(ResultadoStatus.REQUER_HUMANO, "so o agente")
        out = worker._mapear_resultado_agente(res)
        assert out["mensagem"] == "so o agente"
        assert out["evidencias"] == []
