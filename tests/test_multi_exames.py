"""Multiplos exames por job: dedup (Sassepe) e hard-stop (Intercambio).

Guardam dois invariantes que so' aparecem com N>1 exames — exatamente o cenario
dos testes em escala:
  - Sassepe: o portal recusa o mesmo codigo duas vezes -> agregar somando qty.
  - Intercambio: guia PARCIAL e' inaceitavel (I1) -> qualquer procedimento que
    nao entra aborta o envio, que e' irreversivel.
"""
import importlib

import pytest


# ── Sassepe: agregacao por codigo de portal ───────────────────────────────
def _agregar(codigos):
    submit = importlib.import_module("adapters.sassepe.submit")
    return submit.agregar_por_codigo_portal(codigos)


def test_sassepe_codigos_distintos_preservam_ordem_e_qty():
    fora = _agregar([
        {"codigo_tuss": "40901114", "quantidade": 1},
        {"codigo_tuss": "40808041", "quantidade": 2},
    ])
    assert fora == [("40901114", 1), ("40808041", 2)]


def test_sassepe_mesmo_tuss_vira_um_item_somando_qty():
    # US ombro + US joelho resolvem no MESMO codigo -> 1 procedimento, qty 2
    fora = _agregar([
        {"codigo_tuss": "40901220", "nome": "US ombro"},
        {"codigo_tuss": "40901220", "nome": "US joelho"},
    ])
    assert fora == [("40901220", 2)]


def test_sassepe_mistura_duplicado_e_distinto():
    fora = _agregar([
        {"codigo_tuss": "40901220", "quantidade": 1},
        {"codigo_tuss": "40901114", "quantidade": 1},
        {"codigo_tuss": "40901220", "quantidade": 3},
    ])
    assert fora == [("40901220", 4), ("40901114", 1)]


def test_sassepe_quantidade_ausente_conta_um():
    assert _agregar([{"codigo_tuss": "40901220"}]) == [("40901220", 1)]


# ── Intercambio: TODOS os procedimentos ou nenhum ─────────────────────────
def _mod():
    return importlib.import_module("adapters.unimed_intercambio.submit")


@pytest.mark.asyncio
async def test_intercambio_todos_ok_nao_gera_erro():
    chamadas = []

    async def _add(page, codigo, qtd):
        chamadas.append((codigo, qtd))
        return True, None

    erros = await _mod().adicionar_todos_procedimentos(
        None, [{"codigo": "40901114", "quantidade": 1},
               {"codigo": "40808041", "quantidade": 2}], adicionar=_add)
    assert erros == []
    assert chamadas == [("40901114", 1), ("40808041", 2)]


@pytest.mark.asyncio
async def test_intercambio_falha_parcial_e_reportada():
    """1 de 3 falha -> erro devolvido (o chamador aborta; nada de guia parcial)."""
    async def _add(page, codigo, qtd):
        if codigo == "40808041":
            return False, "codigo nao encontrado no portal"
        return True, None

    erros = await _mod().adicionar_todos_procedimentos(
        None, [{"codigo": "40901114"}, {"codigo": "40808041"},
               {"codigo": "40901220"}], adicionar=_add)
    assert len(erros) == 1
    assert "nao encontrado" in erros[0]


@pytest.mark.asyncio
async def test_intercambio_codigo_vazio_conta_como_erro():
    """De-para que nao resolveu o TUSS nao pode sumir calado."""
    async def _add(page, codigo, qtd):
        return True, None

    erros = await _mod().adicionar_todos_procedimentos(
        None, [{"codigo": ""}, {"codigo": "40901114"}], adicionar=_add)
    assert len(erros) == 1
    assert "vazio" in erros[0]
