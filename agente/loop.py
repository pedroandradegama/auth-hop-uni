# ============================================================================
# agente/loop.py  (v0.1.0)
# Loop híbrido: entra APENAS quando o adapter determinístico lança
# FalhaDeterministica com motivo em MOTIVOS_AGENTE (decisão é do runner).
#
# Executor  = AGENTE_MODELO_EXECUTOR (default Haiku 4.5): decide próximo passo.
# Verifier  = AGENTE_MODELO_VERIFIER (default Sonnet 4.6): audita formulário
#             campo-a-campo contra o JobPreAutorizacao antes de submeter, e
#             assume o replan quando o executor falha 2x na mesma etapa.
#
# Regras de aço (runtime, não prompt):
#   - submeter exige verificação aprovada + checagem de guia existente (acoes.py)
#   - erro/timeout APÓS clique de submeter => RESULTADO_INCERTO, nunca retry
#   - orçamento (passos + USD) checado antes de cada chamada de modelo
# ============================================================================
from __future__ import annotations

import json
import os
import time
from typing import Any, Awaitable, Callable, Optional

import anthropic

from .acoes import (TOOL_PROXIMA_ACAO, AcaoBloqueada, ContextoSeguranca,
                    executar)
from .orcamento import Orcamento, OrcamentoEstourado
from .pruner import Snapshot, podar
from .tipos import (FalhaDeterministica, ResultadoAgente, ResultadoStatus)

MODELO_EXECUTOR = os.environ.get("AGENTE_MODELO_EXECUTOR", "claude-haiku-4-5")
MODELO_VERIFIER = os.environ.get("AGENTE_MODELO_VERIFIER", "claude-sonnet-4-6")
MAX_FALHAS_MESMA_ETAPA = 2

SYSTEM_EXECUTOR = """Você é o módulo de recuperação do robô de pré-autorização da IMAG.
O fluxo automatizado determinístico falhou no portal do convênio e você assume do ponto
de falha para CONCLUIR a solicitação de pré-autorização — ou escalar com diagnóstico útil.

Regras:
1. Uma ação por vez, sempre via tool proxima_acao, sempre baseada no snapshot atual.
2. Use SOMENTE os dados do job fornecidos. Nunca invente carteirinha, CPF, código TUSS.
3. Antes de submeter, use 'verificar' (auditoria independente). Submeter sem verificação
   aprovada será bloqueado pelo sistema.
4. Se encontrar CAPTCHA, WAF, exigência não coberta pelos dados do job, ou após 2
   tentativas falhas na mesma tela: use 'escalar' com diagnóstico claro (causa raiz +
   o que o humano deve fazer) e, se identificou a mudança do portal, patch_sugerido.
5. Campos já preenchidos corretamente pelo robô determinístico não precisam ser refeitos.
6. Seja econômico: o menor número de ações que conclui o fluxo corretamente."""

SYSTEM_VERIFIER = """Você é o auditor independente do robô de pré-autorização da IMAG.
Receberá (a) os dados oficiais do job e (b) o snapshot do formulário no portal.
Compare CAMPO A CAMPO. Responda APENAS JSON:
{"aprovado": true|false, "divergencias": ["campo: esperado X, encontrado Y", ...],
 "observacao": "1 frase"}
Reprove em QUALQUER divergência de: carteirinha, CPF, código TUSS/quantidade, médico
solicitante, anexos. Formatação equivalente (máscara de CPF, maiúsculas) não é divergência."""


def _job_compacto(job: dict[str, Any]) -> str:
    """Dados do job no formato que vai pro modelo (só o necessário)."""
    return json.dumps({
        "carteirinha": job.get("carteirinha"),
        "cpf": job.get("cpf"),
        "medico": job.get("medico"),
        "codigos": job.get("codigos"),
        "anexos": [a.get("nome") for a in job.get("anexos", [])],
        "convenio": job.get("convenio"),
    }, ensure_ascii=False)


class AgenteFallback:
    def __init__(
        self,
        client: Optional[anthropic.AsyncAnthropic] = None,
        # Callable async fornecida pelo adapter: busca guia existente no portal
        # (carteirinha + data). Retorna protocolo se existir, None se não.
        buscar_guia_existente: Optional[Callable[..., Awaitable[Optional[str]]]] = None,
        # Callable async: extrai protocolo da tela de confirmação, se presente.
        extrair_protocolo: Optional[Callable[..., Awaitable[Optional[str]]]] = None,
    ) -> None:
        self.client = client or anthropic.AsyncAnthropic()
        self.buscar_guia_existente = buscar_guia_existente
        self.extrair_protocolo = extrair_protocolo

    # ── chamada executor (Haiku) com cache do bloco fixo ──────────────────
    async def _decidir(self, orc: Orcamento, job: dict[str, Any],
                       falha: FalhaDeterministica, historico: list[str],
                       snap: Snapshot, replan: bool) -> dict[str, Any]:
        modelo = MODELO_VERIFIER if replan else MODELO_EXECUTOR
        system = [{
            "type": "text",
            "text": SYSTEM_EXECUTOR + "\n\nDADOS DO JOB:\n" + _job_compacto(job)
            + "\n\nFALHA ORIGINAL DO ROBÔ:\n" + json.dumps(falha.resumo(), ensure_ascii=False),
            "cache_control": {"type": "ephemeral"},
        }]
        user = ("HISTÓRICO DE AÇÕES:\n" + ("\n".join(historico[-12:]) or "(início)")
                + "\n\nSNAPSHOT ATUAL DA PÁGINA:\n" + snap.texto
                + "\n\nDecida a próxima ação via proxima_acao.")
        resp = await self.client.messages.create(
            model=modelo, max_tokens=700, system=system,
            tools=[TOOL_PROXIMA_ACAO],
            tool_choice={"type": "tool", "name": "proxima_acao"},
            messages=[{"role": "user", "content": user}],
        )
        orc.registrar(modelo, resp.usage, verifier=replan)
        for bloco in resp.content:
            if bloco.type == "tool_use":
                return dict(bloco.input)
        return {"acao": "escalar", "racional": "modelo não retornou tool_use",
                "diagnostico": "falha interna do executor"}

    # ── verifier (Sonnet): audita formulário antes do submit ──────────────
    async def _verificar(self, orc: Orcamento, job: dict[str, Any],
                         snap: Snapshot) -> dict[str, Any]:
        user = ("DADOS OFICIAIS DO JOB:\n" + _job_compacto(job)
                + "\n\nSNAPSHOT DO FORMULÁRIO:\n" + snap.texto)
        resp = await self.client.messages.create(
            model=MODELO_VERIFIER, max_tokens=600,
            system=[{"type": "text", "text": SYSTEM_VERIFIER,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        orc.registrar(MODELO_VERIFIER, resp.usage, verifier=True)
        texto = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return json.loads(texto.strip().removeprefix("```json").removesuffix("```").strip())
        except json.JSONDecodeError:
            return {"aprovado": False, "divergencias": ["verifier retornou JSON inválido"],
                    "observacao": texto[:200]}

    # ── loop principal ─────────────────────────────────────────────────────
    async def executar(self, job: dict[str, Any], page: Any,
                       falha: FalhaDeterministica,
                       ctx: ContextoSeguranca) -> ResultadoAgente:
        inicio = time.monotonic()
        orc = Orcamento()
        historico: list[str] = []
        trace: list[dict[str, Any]] = []
        cpfs_job = {"".join(filter(str.isdigit, job.get("cpf") or ""))} - {""}
        falhas_seguidas = 0
        submeteu = False

        resultado = ResultadoAgente(
            status=ResultadoStatus.REQUER_HUMANO, job_id=str(job.get("job_id")),
            motivo_fallback=falha.motivo.value, etapa_fallback=falha.etapa,
            detalhe_fallback=falha.detalhe or "")

        passo = 0
        while True:
            passo += 1
            try:
                orc.checar(passo)
            except OrcamentoEstourado as e:
                resultado.diagnostico = f"orçamento estourado: {e}. " \
                    f"Último estado: {historico[-1] if historico else falha.detalhe}"
                break

            snap = await podar(page, cpfs_job)
            replan = falhas_seguidas >= MAX_FALHAS_MESMA_ETAPA
            acao = await self._decidir(orc, job, falha, historico, snap, replan)
            trace.append({"passo": passo, "acao": acao})

            nome = acao.get("acao")

            if nome == "escalar":
                resultado.diagnostico = acao.get("diagnostico", "") or acao.get("racional", "")
                resultado.patch_sugerido = acao.get("patch_sugerido")
                break

            if nome == "verificar":
                veredito = await self._verificar(orc, job, snap)
                ctx.verificacao_aprovada = bool(veredito.get("aprovado"))
                trace.append({"passo": passo, "verifier": veredito})
                if ctx.verificacao_aprovada and self.buscar_guia_existente:
                    existente = await self.buscar_guia_existente(page=page, job=job)
                    ctx.guia_existente_checada = True
                    if existente:
                        resultado.status = ResultadoStatus.CONCLUIDO
                        resultado.protocolo = existente
                        resultado.diagnostico = "guia já existia no portal (idempotência)"
                        break
                historico.append(
                    f"verificação: {'APROVADA' if ctx.verificacao_aprovada else 'REPROVADA'} "
                    + "; ".join(veredito.get("divergencias", [])))
                falhas_seguidas = 0
                continue

            try:
                if nome == "submeter":
                    submeteu = True  # a partir daqui, erro = RESULTADO_INCERTO
                obs = await executar(page, snap, acao, ctx)
                historico.append(f"passo {passo}: {obs} ({acao.get('racional','')})")
                falhas_seguidas = 0
            except AcaoBloqueada as e:
                historico.append(f"passo {passo}: BLOQUEADO — {e}")
                falhas_seguidas += 1
                continue
            except Exception as e:  # noqa: BLE001 — erro de Playwright/rede
                if submeteu:
                    resultado.status = ResultadoStatus.RESULTADO_INCERTO
                    resultado.diagnostico = (
                        f"erro APÓS clique de submissão: {e}. Não é seguro repetir "
                        "(risco de guia dupla). Verificar manualmente no portal.")
                    break
                historico.append(f"passo {passo}: ERRO — {type(e).__name__}: {e}")
                falhas_seguidas += 1
                continue

            if nome == "submeter":
                protocolo = None
                if self.extrair_protocolo:
                    try:
                        protocolo = await self.extrair_protocolo(page=page)
                    except Exception:  # noqa: BLE001
                        protocolo = None
                if protocolo:
                    resultado.status = ResultadoStatus.CONCLUIDO
                    resultado.protocolo = protocolo
                    resultado.diagnostico = "fluxo concluído pelo agente"
                    resultado.patch_sugerido = acao.get("patch_sugerido")
                else:
                    resultado.status = ResultadoStatus.RESULTADO_INCERTO
                    resultado.diagnostico = (
                        "submissão executada mas protocolo não localizado na "
                        "confirmação — verificar manualmente. NUNCA re-submeter.")
                break

        resultado.passos_executados = passo
        resultado.custo = orc.custo
        resultado.duracao_seg = time.monotonic() - inicio
        resultado.trace = trace
        return resultado
