"""config.py — Adapter Unimed Intercambio (portal CONNECTA).

Portal ASP.NET WebForms (remote.unimedrecife.com.br:444/connecta). Diferente do
autorizador.unimedrecife.com.br (adapter unimed_recife). Regras fixas validadas
ao vivo em 14/07/2026 (bot_connecta.py). Engine chromium + headless=False + Xvfb:
o CONNECTA esconde o formulario quando detecta headless puro.
"""
import os
from urllib.parse import urlparse

import config as _raiz  # reusa SCREENSHOTS_DIR/BASE_DIR globais


def _req(nome: str) -> str:
    v = os.environ.get(nome)
    if not v:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {nome}.")
    return v


PORTAL_URL = os.environ.get(
    "UNIMED_CONECTA_URL",
    "https://remote.unimedrecife.com.br:444/connecta/Default.aspx",
)
URL_SOLICITACAO = os.environ.get(
    "UNIMED_CONECTA_URL_SOLICITACAO",
    "https://remote.unimedrecife.com.br:444/connecta/Content/TISS/Prestador/GuiaSolicitacaoSPSADT.aspx",
)
URL_HISTORICO_AUTORIZACAO = os.environ.get(
    "UNIMED_CONECTA_URL_HISTORICO",
    "https://remote.unimedrecife.com.br:444/connecta/Content/TISS/Historico/Autorizacao.aspx",
)


def unimed_conecta_user() -> str:
    return _req("UNIMED_CONECTA_USER")


def unimed_conecta_pass() -> str:
    return _req("UNIMED_CONECTA_PASS")


def contexto_prestador() -> str:
    return os.environ.get("CONTEXTO_PRESTADOR", "Imag Diagnostico Por Imagem Ltda")


# Regras de negocio fixas (validadas 14/07/2026 no bot_connecta.py)
CONSELHO_PROFISSIONAL_FIXO = "CRM"
UF_CONSELHO_FIXO = "PE"   # fallback historico; a autoridade e' uf_conselho()


def uf_conselho(uf_do_job: str | None = None) -> str:
    """UF do conselho: a do job (autoridade) ou UF_CONSELHO_PADRAO do deploy."""
    return _raiz.uf_conselho(uf_do_job)
CODIGO_CBO_FIXO = "225125 - Médico clínico"
CARATER_ATENDIMENTO_FIXO = "1-Eletiva"
TIPO_ITEM_FIXO = "Procedimento"
CODIGO_PRESTADOR_FIXO = "99999999999999"

BROWSER_ENGINE = "chromium"          # CONNECTA esconde form em headless puro
BROWSER_HEADLESS = False             # roda sob Xvfb no Linux (ver sessao.py)
DOMINIO = urlparse(PORTAL_URL).netloc  # "remote.unimedrecife.com.br:444"
SCREENSHOTS_DIR = _raiz.SCREENSHOTS_DIR
