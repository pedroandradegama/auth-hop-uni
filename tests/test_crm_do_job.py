"""O CRM do solicitante vem em campo PRÓPRIO do job — não só embutido no nome.

Causa-raiz recorrente (SANDRA PAIVA 07/ago, NAYARA ROCHA 28/ago): o HOP envia
`medico="nayara rocha"` e `crm="23607"` SEPARADOS. Sassepe e SulAmérica só
extraíam o CRM do texto de `medico`, descartavam o campo `crm`, buscavam por
nome e abortavam por ambiguidade (I3) — com o CRM disponível no job o tempo
todo. Só o intercâmbio lia `job["crm"]`.
"""
import contextlib
import importlib

import pytest

from agente import FalhaDeterministica


class _FakePage:
    url = "https://portal.test/x"


def _fake_navegador():
    """Isola o teste do portal real. Sem isto, `executar` abre browser de verdade
    e, numa maquina COM credenciais (a VPS), loga no portal e navega — o teste
    vira integracao ao vivo, flaky e com trafego real. Mesmo padrao de
    tests/test_costura_a_sassepe_sulamerica.py."""
    @contextlib.asynccontextmanager
    async def _nav():
        yield _FakePage()
    return _nav


async def _noop_login(page):
    return None


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
async def test_sulamerica_aceita_crm_do_campo_do_job(monkeypatch):
    """Com o CRM no campo próprio, o pré-flight deixa passar e a execução chega
    a abrir o portal. Provamos isso interceptando o primeiro passo in-portal —
    sem browser, sem rede."""
    submit = importlib.import_module("adapters.sulamerica.submit")
    sessao = importlib.import_module("adapters.sulamerica.sessao")
    monkeypatch.setattr(sessao, "navegador", _fake_navegador())
    monkeypatch.setattr(sessao, "login", _noop_login)

    async def _sentinela(page):
        raise submit.SubmitAbortado("SENTINELA: passou do pre-flight")
    monkeypatch.setattr(submit, "_navegar_para_solicitacao", _sentinela)

    job = {"carteirinha": "01234567890123456789", "medico": "NAYARA ROCHA",
           "crm": "23607", "codigos": [{"codigo_tuss": "40901220"}],
           "arquivos": ["/x"]}
    with pytest.raises(FalhaDeterministica) as ei:
        await submit.executar(job)
    # chegou ao passo in-portal => o pré-flight NÃO barrou por "CRM ausente"
    assert "SENTINELA" in ei.value.detalhe
    assert "CRM do solicitante ausente" not in ei.value.detalhe


@pytest.mark.asyncio
async def test_sulamerica_sem_crm_em_lugar_nenhum_ainda_barra():
    submit = importlib.import_module("adapters.sulamerica.submit")
    job = {"carteirinha": "01234567890123456789", "medico": "NAYARA ROCHA",
           "codigos": [{"codigo_tuss": "40901220"}], "arquivos": ["/x"]}
    r = await submit.executar(job)
    assert r["status"] == "erro_submit"
    assert "CRM do solicitante ausente" in r["mensagem"]
