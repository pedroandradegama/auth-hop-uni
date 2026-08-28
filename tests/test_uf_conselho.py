"""UF do conselho do solicitante: a do job manda, com padrão configurável.

Causa-raiz real do job de 27/ago: o CRM era do RJ, mas o adapter mandava PE
fixo. O portal falhou a validação no CFM e abriu modal que bloqueou o
formulário. ~99% dos solicitantes são locais, mas CRM de outro estado existe.
"""
import importlib

import pytest

import config as raiz
import schemas


# ── Resolução da UF (raiz) ────────────────────────────────────────────────
def test_uf_do_job_tem_prioridade():
    assert raiz.uf_conselho("RJ") == "RJ"


def test_uf_normaliza_minuscula_e_espaco():
    assert raiz.uf_conselho(" rj ") == "RJ"


def test_sem_uf_usa_padrao_do_deploy():
    assert raiz.uf_conselho(None) == raiz.UF_CONSELHO_PADRAO


def test_uf_invalida_cai_no_padrao():
    """Lixo não pode vazar pro portal — vira o padrão."""
    for ruim in ("XPTO", "P", "12", ""):
        assert raiz.uf_conselho(ruim) == raiz.UF_CONSELHO_PADRAO


def test_padrao_e_pe_salvo_override_de_ambiente():
    assert raiz.UF_CONSELHO_PADRAO == "PE"


# ── Schema: job carrega crm_uf ────────────────────────────────────────────
def _job(**extra):
    base = dict(job_id="j1", idempotency_key="k1", org_id="o1",
                convenio="sulamerica", carteirinha="01234567890123456789",
                medico="16188 NOME", crm="16188",
                codigos=[{"codigo_tuss": "40901220"}],
                anexos=[{"url": "https://x/y.pdf", "nome": "y.pdf"}])
    base.update(extra)
    return schemas.JobPreAutorizacao(**base)


def test_schema_aceita_e_normaliza_crm_uf():
    assert _job(crm_uf="rj").crm_uf == "RJ"


def test_schema_crm_uf_ausente_fica_none():
    assert _job().crm_uf is None


def test_schema_crm_uf_invalida_vira_none():
    """None deixa o adapter cair no padrão, em vez de propagar UF inválida."""
    assert _job(crm_uf="XPTO").crm_uf is None


# ── Adapters resolvem a UF ────────────────────────────────────────────────
@pytest.mark.parametrize("mod", ["adapters.unimed_intercambio.config",
                                 "adapters.sulamerica.config"])
def test_adapters_expoem_uf_conselho(mod):
    c = importlib.import_module(mod)
    assert c.uf_conselho("RJ") == "RJ"
    assert c.uf_conselho(None) == raiz.UF_CONSELHO_PADRAO


# ── SulAmérica: casa a UF pelo TEXTO da <option> (o value é código, 26=PE) ──
class _FakeLocator:
    def __init__(self, opcoes, escolhido):
        self._opcoes, self._escolhido = opcoes, escolhido

    async def evaluate(self, _js):
        return self._opcoes

    async def select_option(self, value):
        self._escolhido.append(value)


class _FakeFrame:
    def __init__(self, opcoes):
        self._opcoes, self.escolhido = opcoes, []

    def locator(self, _sel):
        return _FakeLocator(self._opcoes, self.escolhido)


def _ui():
    return importlib.import_module("adapters.sulamerica._ui")


@pytest.mark.asyncio
@pytest.mark.parametrize("texto", ["RJ", "33 - RJ", "RJ - Rio de Janeiro"])
async def test_sulamerica_casa_uf_em_varios_formatos(texto):
    f = _FakeFrame([{"value": "26", "text": "PE"}, {"value": "33", "text": texto}])
    await _ui().selecionar_uf_conselho(f, "#uf", "RJ")
    assert f.escolhido == ["33"]   # escolheu pelo código correto do RJ


@pytest.mark.asyncio
async def test_sulamerica_nao_confunde_sigla_dentro_de_palavra():
    """'PE' não pode casar com 'PERNAMBUCO' de outra UF nem com 'ES' em 'TESTE'."""
    f = _FakeFrame([{"value": "32", "text": "ES - Espirito Santo"},
                    {"value": "26", "text": "PE - Pernambuco"}])
    await _ui().selecionar_uf_conselho(f, "#uf", "PE")
    assert f.escolhido == ["26"]


@pytest.mark.asyncio
async def test_sulamerica_usa_fallback_quando_nao_acha():
    f = _FakeFrame([{"value": "26", "text": "PE"}])
    await _ui().selecionar_uf_conselho(f, "#uf", "RJ", valor_fallback="26")
    assert f.escolhido == ["26"]


@pytest.mark.asyncio
async def test_sulamerica_falha_alto_listando_opcoes_reais():
    """Sem fallback, erra explícito com as opções — o formato aparece no log."""
    f = _FakeFrame([{"value": "26", "text": "PE"}])
    with pytest.raises(ValueError) as ei:
        await _ui().selecionar_uf_conselho(f, "#uf", "RJ")
    assert "RJ" in str(ei.value) and "PE" in str(ei.value)
