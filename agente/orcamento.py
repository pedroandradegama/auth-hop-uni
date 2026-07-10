# ============================================================================
# agente/orcamento.py  (v0.1.0)
# Guarda de orçamento por job: passos + custo USD. Verificado pelo runtime
# ANTES de cada chamada de modelo. Preços por env (AGENTE_PRECOS_JSON) para
# não exigir deploy quando a tabela de preços mudar.
# Preços em USD por MILHÃO de tokens: {"modelo": {"in","out","cache_read","cache_write"}}
# ============================================================================
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .tipos import CustoExecucao

_PRECOS_DEFAULT = {
    "claude-haiku-4-5":  {"in": 1.0, "out": 5.0,  "cache_read": 0.1, "cache_write": 1.25},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0, "cache_read": 0.3, "cache_write": 3.75},
}


def _precos() -> dict:
    bruto = os.environ.get("AGENTE_PRECOS_JSON", "")
    if not bruto:
        return _PRECOS_DEFAULT
    try:
        return {**_PRECOS_DEFAULT, **json.loads(bruto)}
    except json.JSONDecodeError:
        return _PRECOS_DEFAULT


class OrcamentoEstourado(Exception):
    pass


@dataclass
class Orcamento:
    max_passos: int = int(os.environ.get("AGENTE_MAX_PASSOS", "15"))
    max_custo_usd: float = float(os.environ.get("AGENTE_MAX_CUSTO_USD", "0.60"))
    custo: CustoExecucao = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.custo is None:
            self.custo = CustoExecucao()

    def checar(self, passo: int) -> None:
        if passo > self.max_passos:
            raise OrcamentoEstourado(
                f"max_passos ({self.max_passos}) atingido")
        if self.custo.custo_usd >= self.max_custo_usd:
            raise OrcamentoEstourado(
                f"max_custo_usd (${self.max_custo_usd:.2f}) atingido "
                f"(gasto: ${self.custo.custo_usd:.4f})")

    def registrar(self, modelo: str, usage: object, verifier: bool = False) -> None:
        """Acumula usage de uma resposta da API Anthropic (response.usage)."""
        t_in = getattr(usage, "input_tokens", 0) or 0
        t_out = getattr(usage, "output_tokens", 0) or 0
        t_cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        t_cw = getattr(usage, "cache_creation_input_tokens", 0) or 0

        p = _precos().get(modelo)
        if p is None:  # modelo sem preço cadastrado: usa o mais caro conhecido
            p = max(_precos().values(), key=lambda x: x["out"])

        self.custo.tokens_input += t_in
        self.custo.tokens_output += t_out
        self.custo.tokens_cache_read += t_cr
        self.custo.tokens_cache_write += t_cw
        self.custo.custo_usd += (
            t_in * p["in"] + t_out * p["out"]
            + t_cr * p["cache_read"] + t_cw * p["cache_write"]
        ) / 1_000_000
        if verifier:
            self.custo.chamadas_verifier += 1
        else:
            self.custo.chamadas_executor += 1
