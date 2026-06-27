"""
adapters/sassepe/codigos.py — Resolucao de codigo de procedimento (Sassepe).

Mesma decisao de contrato do Unimed: o de-para mora NO ADAPTER, nunca no HOP.
Constatacao do piloto: o Sassepe aceita o proprio TUSS direto no campo de
"Codigo e descricao do procedimento ou item" (Tabela 22 — Procedimentos e
eventos em saude). Logo, a resolucao e' IDENTIDADE hoje. Se algum dia o portal
exigir um codigo proprio, a traducao passa a morar AQUI (CSV proprio), sem o
HOP duplicar tabela.
"""


def resolver_codigo_portal(codigo_tuss: str) -> str:
    """Codigo que vai literalmente no campo de procedimento. Identidade hoje."""
    return (codigo_tuss or "").strip()
