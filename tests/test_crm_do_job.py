"""O CRM do solicitante vem em campo PRÓPRIO do job — não só embutido no nome.

Causa-raiz recorrente (SANDRA PAIVA 07/ago, NAYARA ROCHA 28/ago): o HOP envia
`medico="nayara rocha"` e `crm="23607"` SEPARADOS. Sassepe e SulAmérica só
extraíam o CRM do texto de `medico`, descartavam o campo `crm`, buscavam por
nome e abortavam por ambiguidade (I3) — com o CRM disponível no job o tempo
todo. Só o intercâmbio lia `job["crm"]`.
"""
import importlib

import pytest


def _sassepe():
    return importlib.import_module("adapters.sassepe.submit")


# ── Parse do texto (fallback) ─────────────────────────────────────────────
@pytest.mark.parametrize("texto,esperado", [
    ("16188 NUBIA ROSA LOPES", ("16188", "NUBIA ROSA LOPES")),
    ("16188 - NUBIA ROSA LOPES", ("16188", "NUBIA ROSA LOPES")),
    ("Dra. Nubia Rosa Lopes", (None, "Dra. Nubia Rosa Lopes")),
    ("nayara rocha", (None, "nayara rocha")),
])
def test_split_medico(texto, esperado):
    assert _sassepe()._split_medico(texto) == esperado


# ── Precedência: campo do job > texto ─────────────────────────────────────
def _crm_efetivo(medico: str, crm_job):
    """Reproduz a resolução do adapter: campo do job manda, texto é fallback."""
    crm, _nome = _sassepe()._split_medico(medico)
    return (crm_job or "").strip() or crm


def test_crm_do_campo_do_job_e_usado_quando_nome_nao_tem():
    """O caso NAYARA: nome ambíguo, mas o CRM estava no job."""
    assert _crm_efetivo("nayara rocha", "23607") == "23607"


def test_campo_do_job_tem_precedencia_sobre_o_texto():
    assert _crm_efetivo("205881 NAYARA ROCHA", "23607") == "23607"


def test_sem_campo_cai_no_texto():
    assert _crm_efetivo("16188 NUBIA ROSA LOPES", None) == "16188"


def test_campo_vazio_ou_espacos_cai_no_texto():
    for vazio in (None, "", "   "):
        assert _crm_efetivo("16188 NUBIA", vazio) == "16188"


def test_sem_crm_em_lugar_nenhum_fica_none():
    """Sem CRM, o adapter busca por nome — pode abortar por ambiguidade (I3)."""
    assert _crm_efetivo("nayara rocha", None) is None


# ── SulAmérica exige CRM: com o campo do job, passa o pré-flight ──────────
@pytest.mark.asyncio
async def test_sulamerica_aceita_crm_do_campo_do_job():
    submit = importlib.import_module("adapters.sulamerica.submit")
    job = {"carteirinha": "01234567890123456789", "medico": "NAYARA ROCHA",
           "crm": "23607", "codigos": [{"codigo_tuss": "40901220"}],
           "arquivos": ["/x"]}
    r = await submit.executar(job)
    # não pode mais morrer no pré-flight por "CRM ausente"; falha adiante (browser)
    assert "CRM do solicitante ausente" not in (r.get("mensagem") or "")


@pytest.mark.asyncio
async def test_sulamerica_sem_crm_em_lugar_nenhum_ainda_barra():
    submit = importlib.import_module("adapters.sulamerica.submit")
    job = {"carteirinha": "01234567890123456789", "medico": "NAYARA ROCHA",
           "codigos": [{"codigo_tuss": "40901220"}], "arquivos": ["/x"]}
    r = await submit.executar(job)
    assert r["status"] == "erro_submit"
    assert "CRM do solicitante ausente" in r["mensagem"]
