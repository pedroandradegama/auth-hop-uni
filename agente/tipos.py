# ============================================================================
# agente/tipos.py  (v0.1.0)
# Contratos tipados entre o adapter determinístico e o loop de agente.
# O adapter passa a lançar FalhaDeterministica nos pontos de erro; o runner
# captura e decide se ativa o agente (ver MOTIVOS_AGENTE).
# ============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class MotivoFalha(str, Enum):
    SELETOR_NAO_ACHADO = "seletor_nao_achado"
    ESTADO_INESPERADO = "estado_inesperado"
    VALIDACAO_PORTAL = "validacao_portal"
    SESSAO_EXPIRADA = "sessao_expirada"   # NÃO ativa agente: re-login + retry 1x
    REDE = "rede"                          # NÃO ativa agente: backoff determinístico
    WAF_CAPTCHA = "waf_captcha"            # NÃO ativa agente: requer_humano direto


# Motivos que justificam acionar o loop de agente (custo de token > 0).
MOTIVOS_AGENTE = {
    MotivoFalha.SELETOR_NAO_ACHADO,
    MotivoFalha.ESTADO_INESPERADO,
    MotivoFalha.VALIDACAO_PORTAL,
}


class FalhaDeterministica(Exception):
    """Lançada pelo adapter determinístico com contexto suficiente para o
    agente retomar do ponto de falha (a page do Playwright segue aberta)."""

    def __init__(
        self,
        motivo: MotivoFalha,
        etapa: str,
        detalhe: str = "",
        seletor: Optional[str] = None,
        url: Optional[str] = None,
        screenshot_path: Optional[str] = None,
    ) -> None:
        super().__init__(f"[{motivo.value}] etapa={etapa} {detalhe}")
        self.motivo = motivo
        self.etapa = etapa
        self.detalhe = detalhe
        self.seletor = seletor
        self.url = url
        self.screenshot_path = screenshot_path

    def resumo(self) -> dict[str, Any]:
        return {
            "motivo": self.motivo.value,
            "etapa": self.etapa,
            "detalhe": self.detalhe,
            "seletor": self.seletor,
            "url": self.url,
        }


class ResultadoStatus(str, Enum):
    CONCLUIDO = "concluido"                # protocolo capturado
    REQUER_HUMANO = "requer_humano"        # agente escalou (com dossiê)
    RESULTADO_INCERTO = "resultado_incerto"  # submissão ambígua — NUNCA retry


@dataclass
class CustoExecucao:
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    custo_usd: float = 0.0
    chamadas_executor: int = 0
    chamadas_verifier: int = 0


@dataclass
class ResultadoAgente:
    status: ResultadoStatus
    job_id: str
    protocolo: Optional[str] = None
    diagnostico: str = ""
    # Sugestão de correção do adapter determinístico (seletor novo, etapa nova).
    patch_sugerido: Optional[str] = None
    passos_executados: int = 0
    custo: CustoExecucao = field(default_factory=CustoExecucao)
    duracao_seg: float = 0.0
    motivo_fallback: str = ""
    etapa_fallback: str = ""
    # Mensagem CRUA do passo que abortou (FalhaDeterministica.detalhe). O `trace`
    # so' guarda os passos do agente; sem isto o detalhe do determinístico se
    # perde (handoff loop-engineering §3). Persistir p/ diagnostico consultavel.
    detalhe_fallback: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)

    def para_agent_trace(self, org_id: str, convenio: str) -> dict[str, Any]:
        """Payload do tipo agent_trace para o receive-autorizacao (v1.1.0)."""
        return {
            "tipo": "agent_trace",
            "org_id": org_id,
            "convenio": convenio,
            "job_id": self.job_id,
            "status": self.status.value,
            "protocolo": self.protocolo,
            "motivo_fallback": self.motivo_fallback,
            "etapa_fallback": self.etapa_fallback,
            "detalhe_fallback": self.detalhe_fallback,
            "diagnostico": self.diagnostico,
            "patch_sugerido": self.patch_sugerido,
            "passos": self.passos_executados,
            "tokens_input": self.custo.tokens_input,
            "tokens_output": self.custo.tokens_output,
            "tokens_cache_read": self.custo.tokens_cache_read,
            "tokens_cache_write": self.custo.tokens_cache_write,
            "custo_usd": round(self.custo.custo_usd, 6),
            "duracao_seg": round(self.duracao_seg, 2),
            "trace": self.trace[-40:],  # cap defensivo de tamanho
        }
