# ============================================================================
# agente/acoes.py  (v0.1.0)
# Allowlist de ações + execução via Playwright. As regras de segurança vivem
# AQUI (runtime), não no prompt:
#   - submeter: bloqueado sem verificação aprovada + checagem de guia existente
#   - navegar: apenas mesmo domínio do portal
#   - anexar: apenas arquivos baixados do job (paths permitidos)
# ============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .pruner import Snapshot, localizar

# Schema exposto ao modelo via tool use (uma única tool: proxima_acao).
TOOL_PROXIMA_ACAO: dict[str, Any] = {
    "name": "proxima_acao",
    "description": (
        "Decide a próxima ação no portal. Use refs do snapshot (e1, e2...). "
        "'verificar' pede auditoria do formulário antes de submeter. "
        "'submeter' só é aceito após 'verificar' aprovado. "
        "'escalar' encerra e envia o caso para revisão humana com diagnóstico."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "acao": {
                "type": "string",
                "enum": ["clicar", "preencher", "selecionar", "anexar",
                         "navegar", "verificar", "submeter", "escalar"],
            },
            "ref": {"type": "string", "description": "ref do elemento (e1...)"},
            "valor": {"type": "string", "description": "texto/opção/URL/nome do anexo"},
            "racional": {"type": "string", "description": "1 frase: por que esta ação"},
            "diagnostico": {"type": "string",
                            "description": "obrigatório em 'escalar': causa raiz + o que um humano deve fazer"},
            "patch_sugerido": {"type": "string",
                               "description": "em 'escalar' ou após reparo: correção sugerida no adapter determinístico (seletor/etapa)"},
        },
        "required": ["acao", "racional"],
    },
}

TIMEOUT_ACAO_MS = 12_000


@dataclass
class ContextoSeguranca:
    dominio_portal: str                  # ex.: "portal.unimedrecife.com.br"
    anexos_permitidos: dict[str, str]    # nome -> path local baixado do job
    verificacao_aprovada: bool = False   # setado pelo verifier (loop.py)
    submeter_habilitado: bool = False    # AGENTE_SUBMETER_HABILITADO (F0: False)
    guia_existente_checada: bool = False # setado pelo loop após busca no portal


class AcaoBloqueada(Exception):
    """Ação violou uma regra de segurança do runtime."""


async def executar(page: Any, snap: Snapshot, acao: dict[str, Any],
                   ctx: ContextoSeguranca) -> str:
    """Executa a ação decidida pelo modelo. Retorna observação curta (vai pro
    histórico do loop). Lança AcaoBloqueada em violação de segurança."""
    nome = acao.get("acao")
    ref = acao.get("ref", "")
    valor = acao.get("valor", "")

    if nome == "clicar":
        alvo = localizar(page, snap.refs, ref)
        await alvo.click(timeout=TIMEOUT_ACAO_MS)
        return f"cliquei em {ref}"

    if nome == "preencher":
        alvo = localizar(page, snap.refs, ref)
        await alvo.fill(valor, timeout=TIMEOUT_ACAO_MS)
        return f"preenchi {ref} com {valor!r}"

    if nome == "selecionar":
        alvo = localizar(page, snap.refs, ref)
        await alvo.select_option(label=valor, timeout=TIMEOUT_ACAO_MS)
        return f"selecionei {valor!r} em {ref}"

    if nome == "anexar":
        path = ctx.anexos_permitidos.get(valor)
        if not path:
            raise AcaoBloqueada(
                f"anexo {valor!r} não está na lista do job "
                f"(permitidos: {sorted(ctx.anexos_permitidos)})")
        alvo = localizar(page, snap.refs, ref)
        await alvo.set_input_files(path, timeout=TIMEOUT_ACAO_MS)
        return f"anexei {valor}"

    if nome == "navegar":
        destino = urlparse(valor)
        if destino.netloc and destino.netloc != ctx.dominio_portal:
            raise AcaoBloqueada(
                f"navegação fora do portal bloqueada: {destino.netloc}")
        await page.goto(valor, timeout=TIMEOUT_ACAO_MS * 2)
        return f"naveguei para {valor}"

    if nome == "verificar":
        # A execução real da verificação é do loop (chama o verifier Sonnet).
        return "verificacao_solicitada"

    if nome == "submeter":
        if not ctx.submeter_habilitado:
            raise AcaoBloqueada(
                "submeter desabilitado nesta fase (F0/shadow) — escale para humano")
        if not ctx.verificacao_aprovada:
            raise AcaoBloqueada(
                "submeter sem verificação aprovada — use 'verificar' antes")
        if not ctx.guia_existente_checada:
            raise AcaoBloqueada(
                "submeter sem checagem de guia existente — risco de guia dupla")
        alvo = localizar(page, snap.refs, ref)
        await alvo.click(timeout=TIMEOUT_ACAO_MS * 2)
        return "submeti"

    if nome == "escalar":
        return "escalado"

    raise AcaoBloqueada(f"ação desconhecida: {nome!r}")
