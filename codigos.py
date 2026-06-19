"""
codigos.py — Resolucao de codigo de procedimento para o portal Unimed.

Responde a' decisao de contrato (Pergunta 2 do Orquestrador): o de-para de
codigo mora NO WORKER, nunca no HOP. O job carrega `codigo_tuss`; aqui a gente
resolve o que efetivamente vai no campo do portal.

Constatacao do piloto: para a Unimed Recife, o codigo que o portal aceita em
`#codrolmostra` e' o proprio TUSS/ROL (os codigos do codigos_unimed.csv —
ex.: 41101219 RM cranio — entram direto). Logo, a resolucao e' IDENTIDADE hoje.
Se algum dia o portal exigir um codigo proprietario diferente do TUSS, a
traducao passa a morar AQUI (estender o CSV com uma coluna `codigo_portal`),
sem o HOP precisar duplicar tabela de-para alguma.
"""
import csv
import os

import config

_CACHE: dict | None = None


def _carregar() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        caminho = os.path.join(config.BASE_DIR, "codigos_unimed.csv")
        with open(caminho, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cod = (row.get("codigo") or "").strip()
                if cod:
                    _CACHE[cod] = {
                        "nome": (row.get("nome") or "").strip(),
                        "sub_tipo": (row.get("sub_tipo") or "").strip().upper(),
                    }
    return _CACHE


def resolver_codigo_portal(codigo_tuss: str) -> str:
    """Codigo que vai literalmente no campo #codrolmostra. Identidade hoje."""
    return (codigo_tuss or "").strip()


def conhecido(codigo_tuss: str) -> bool:
    """True se o codigo esta no catalogo Unimed conhecido (validacao leve)."""
    return (codigo_tuss or "").strip() in _carregar()


def sub_tipo_de(codigo_tuss: str) -> str | None:
    """Modalidade (RM/TC) do catalogo, se conhecida. Fallback opcional caso o
    HITL nao mande a modalidade (mas o HITL manda, via exames[].modalidade)."""
    item = _carregar().get((codigo_tuss or "").strip())
    return item["sub_tipo"] if item else None
