"""
adapters/sulamerica/codigos.py — Mapeamento de codigo TUSS -> codigo do portal.

No SulAmerica o codigo de procedimento e' digitado direto (campo
'codigo-procedimento'), entao o mapeamento e' IDENTIDADE por enquanto. Mantido
como ponto de extensao (espelha sassepe/codigos.py): se algum dia o portal
exigir um codigo proprio != TUSS, a traducao mora aqui.
"""


def resolver_codigo_portal(codigo_tuss: str) -> str:
    return (codigo_tuss or "").strip()
