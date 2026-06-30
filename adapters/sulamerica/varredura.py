"""
adapters/sulamerica/varredura.py — Tempo 2 (VARREDURA) do adapter Sul America.

Espelha sassepe/varredura.py: coletar(janela_dias) raspa o historico de
solicitacoes e devolve status normalizado; capturar_protocolo_pos_envio(page)
pega o numero da autorizacao logo apos o Confirmar.

ESTADO: os seletores/estrutura exatos do historico e da tela de resultado do
SulAmerica serao mapeados na sondagem ao vivo do portal. Ate' la', as duas
funcoes degradam com seguranca (I3): coletar() retorna [] e a captura retorna
None (-> requer_captura_manual no submit). Sem inventar dado.
"""
import unicodedata

from . import sessao  # noqa: F401  (usado quando coletar for implementado)

# Rotulos do portal -> vocabulario normalizado do contrato.
_MAPA_STATUS = {
    "AUTORIZAD": "AUTORIZADO",
    "LIBERAD": "AUTORIZADO",
    "DEFERID": "AUTORIZADO",
    "APROVAD": "AUTORIZADO",
    "NEGAD": "NEGADO",
    "INDEFERID": "NEGADO",
    "CANCELAD": "NEGADO",
    "RECUSAD": "NEGADO",
    "EM ANALISE": "EM_ANALISE",
    "ANALISE": "EM_ANALISE",
    "PENDENTE": "EM_ANALISE",
    "AGUARDAND": "EM_ANALISE",
    "AUDITORIA": "EM_ANALISE",
}


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def normalizar_status(texto: str) -> str:
    t = _sem_acento(texto).strip().upper()
    for chave, valor in _MAPA_STATUS.items():
        if chave in t:
            return valor
    return "DESCONHECIDO"


async def capturar_protocolo_pos_envio(page) -> str | None:
    """Le o numero da autorizacao na tela de resultado (pos-Confirmar).
    Conservador (I3): retorna None se nao achar com seguranca.

    TODO(sondagem): mapear o seletor/regex do protocolo no SulAmerica.
    """
    return None


async def coletar(janela_dias: int | None = None) -> list[dict]:
    """Login -> Historico de solicitacoes -> raspa as guias da janela.
    Retorna [{numero_protocolo, status_portal, status_raw, carteirinha,
              paciente, data, senha?, ts}].

    TODO(sondagem): mapear a tela de historico do SulAmerica. Ate' la' retorna
    lista vazia (degradacao segura — nada de status inventado).
    """
    return []
