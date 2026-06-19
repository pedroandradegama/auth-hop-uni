"""
schemas.py — Contrato de ENTRADA do worker (o que o HITL/Orquestrador envia).

Este arquivo E' o contrato. O HITL produz exatamente este JSON quando o
operador da' o "Go". A validacao Pydantic rejeita payload malformado com 422
SINCRONO (o HITL sabe na hora), antes de qualquer browser abrir.

Anexos vao como URLs ASSINADAS (o pedido medico ja' esta no storage do HOP
quando o Go acontece). O worker baixa as URLs; nao trafega bytes no /job.
"""
from pydantic import BaseModel, Field, field_validator

import config

SUBTIPOS_VALIDOS = set(config.SUBTIPO_VALUE.keys())  # {"RM", "TC"}


class ExameItem(BaseModel):
    codigo_tuss: str
    sub_tipo: str
    nome: str | None = None

    @field_validator("codigo_tuss")
    @classmethod
    def _codigo_nao_vazio(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("codigo_tuss vazio")
        return v

    @field_validator("sub_tipo")
    @classmethod
    def _subtipo_valido(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in SUBTIPOS_VALIDOS:
            raise ValueError(
                f"sub_tipo invalido '{v}'; use um de {sorted(SUBTIPOS_VALIDOS)}"
            )
        return v


class AnexoItem(BaseModel):
    url: str
    nome: str | None = None

    @field_validator("url")
    @classmethod
    def _url_http(cls, v: str) -> str:
        if not (v or "").startswith(("http://", "https://")):
            raise ValueError("url de anexo deve ser http(s) (URL assinada do storage)")
        return v


class JobPreAutorizacao(BaseModel):
    # Identidade / idempotencia
    job_id: str
    idempotency_key: str
    org_id: str

    # Contexto
    convenio: str = "unimed_recife"
    paciente_cadastro_id: str | None = None
    paciente_nome: str | None = None  # usado p/ casar o protocolo na lista pos-gravar

    # Dados da solicitacao
    carteirinha: str
    medico: str
    codigos: list[ExameItem] = Field(min_length=1)
    anexos: list[AnexoItem] = Field(
        min_length=1,
        description="Pedido medico obrigatorio: pre-auth sem anexo seria negada.",
    )

    @field_validator("job_id", "idempotency_key", "org_id", "medico")
    @classmethod
    def _obrigatorio_nao_vazio(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("campo obrigatorio vazio")
        return v.strip()

    @field_validator("carteirinha")
    @classmethod
    def _carteirinha_minima(cls, v: str) -> str:
        # Gate leniente: pega erro grosseiro cedo (422). O split autoritativo
        # (regra 15/16/17 digitos) fica no submit.py como hard stop.
        digitos = "".join(filter(str.isdigit, v or ""))
        if len(digitos) < 15:
            raise ValueError(
                f"carteirinha com {len(digitos)} digitos (minimo 15)"
            )
        return v.strip()
