"""
schemas.py — Contrato de ENTRADA do worker (o que o HITL/Orquestrador envia).

Este arquivo E' o contrato. O HITL produz exatamente este JSON quando o
operador da' o "Go". A validacao Pydantic rejeita payload malformado com 422
SINCRONO (o HITL sabe na hora), antes de qualquer browser abrir.

Anexos vao como URLs ASSINADAS (o pedido medico ja' esta no storage do HOP
quando o Go acontece). O worker baixa as URLs; nao trafega bytes no /job.
"""
from pydantic import BaseModel, Field, field_validator, model_validator

import config

SUBTIPOS_VALIDOS = set(config.SUBTIPO_VALUE.keys())  # {"RM", "TC"}


# Convenios cujo portal NAO usa sub_tipo RM/TC (codigo TUSS vai direto; ex.:
# Sassepe, onde a Tabela e' sempre 22 e o exame pode ser mamografia/US/etc.).
# Para esses, sub_tipo e' livre/opcional. Os demais (Unimed) exigem RM/TC.
CONVENIOS_SEM_SUBTIPO = {"sassepe", "sulamerica"}


class ExameItem(BaseModel):
    codigo_tuss: str
    sub_tipo: str | None = None
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
    def _subtipo_norm(cls, v: str | None) -> str | None:
        # So' normaliza. A exigencia RM/TC e' POR CONVENIO, no JobPreAutorizacao
        # (que conhece o convenio). Aqui sub_tipo pode ate' ser None (Sassepe).
        return ((v or "").strip().upper() or None)


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
    # Identificador do beneficiario: a espinha pode carregar OS DOIS; cada
    # adapter decide qual usa. Unimed/Amil usam carteirinha; Sassepe NAO tem
    # carteirinha — elegibilidade por CPF. Ambos opcionais; model_validator
    # exige PELO MENOS UM. Validacao de formato autoritativa no submit do adapter.
    carteirinha: str | None = None
    cpf: str | None = None
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
    def _carteirinha_minima(cls, v: str | None) -> str | None:
        # Gate leniente: so' valida SE veio carteirinha. O split autoritativo
        # (15/16/17 digitos) fica no submit.py do adapter como hard stop.
        if v is None or not v.strip():
            return None
        digitos = "".join(filter(str.isdigit, v))
        if len(digitos) < 15:
            raise ValueError(f"carteirinha com {len(digitos)} digitos (minimo 15)")
        return v.strip()

    @field_validator("cpf")
    @classmethod
    def _cpf_minimo(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        digitos = "".join(filter(str.isdigit, v))
        if len(digitos) != 11:
            raise ValueError(f"cpf com {len(digitos)} digitos (esperado 11)")
        return v.strip()

    @model_validator(mode="after")
    def _identificador_presente(self):
        if not (self.carteirinha or self.cpf):
            raise ValueError(
                "job sem identificador: informe carteirinha ou cpf "
                "(o adapter do convenio escolhe qual usa)"
            )
        return self

    @model_validator(mode="after")
    def _subtipo_por_convenio(self):
        # Exige sub_tipo RM/TC SO' para convenios que usam (Unimed). Sassepe e'
        # isento: codigo TUSS vai direto, sub_tipo nem e' usado pelo adapter.
        if self.convenio not in CONVENIOS_SEM_SUBTIPO:
            for e in self.codigos:
                if e.sub_tipo not in SUBTIPOS_VALIDOS:
                    raise ValueError(
                        f"sub_tipo invalido '{e.sub_tipo}' para convenio "
                        f"'{self.convenio}'; use um de {sorted(SUBTIPOS_VALIDOS)}"
                    )
        return self
