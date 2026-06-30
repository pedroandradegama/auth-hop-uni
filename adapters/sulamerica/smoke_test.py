"""
smoke_test.py (SulAmerica) — validacao offline, SEM portal e SEM credenciais.
Testa imports/contrato, split de carteirinha (20 digitos) e medico (CRM NOME),
validacao de arquivo e o schema (carteirinha + sem sub_tipo).
Execute: python adapters/sulamerica/smoke_test.py
"""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("SULAMERICA_CODIGO", "smoke")
os.environ.setdefault("SULAMERICA_SENHA", "smoke")

falhas = []


def checa(nome, fn):
    try:
        fn()
        print(f"  [PASSOU] {nome}")
    except Exception as e:
        print(f"  [FALHOU] {nome}: {e}")
        falhas.append(nome)


print("== adapter sulamerica · smoke test (offline) ==\n")


def _contrato():
    from adapters import sulamerica
    assert inspect.iscoroutinefunction(sulamerica.submit), "submit deve ser async"
    assert inspect.iscoroutinefunction(sulamerica.coletar), "coletar deve ser async"
    assert sulamerica.NOME == "sulamerica"


def _split_carteirinha():
    from adapters.sulamerica import _ui
    a, b, c, d, e = _ui.split_carteirinha("123 45678 9012 3456 7890")
    assert (a, b, c, d, e) == ("123", "45678", "9012", "3456", "7890"), (a, b, c, d, e)
    try:
        _ui.split_carteirinha("123")  # < 20 digitos
        raise AssertionError("deveria ter rejeitado carteirinha curta")
    except ValueError:
        pass


def _split_medico():
    from adapters.sulamerica import _ui
    assert _ui.split_medico("16188 NUBIA ROSA LOPES") == ("16188", "NUBIA ROSA LOPES")
    assert _ui.split_medico("16188 - Nubia Rosa Lopes") == ("16188", "NUBIA ROSA LOPES")
    assert _ui.split_medico("Nubia Rosa Lopes") == (None, "NUBIA ROSA LOPES")


def _validar_arquivo():
    from adapters.sulamerica import _ui
    ok, motivo = _ui.validar_arquivo("/tmp/pedido.pdf")
    assert ok and motivo is None, (ok, motivo)
    bad, motivo = _ui.validar_arquivo("/tmp/pedido.docx")
    assert bad is None and motivo, (bad, motivo)


def _schema_carteirinha_sem_subtipo():
    from schemas import JobPreAutorizacao
    job = JobPreAutorizacao(
        job_id="x", idempotency_key="x", org_id="o", convenio="sulamerica",
        carteirinha="12345678901234567890", medico="16188 NUBIA ROSA LOPES",
        codigos=[{"codigo_tuss": "40901114", "nome": "USG MAMAS"}],
        anexos=[{"url": "https://x/y.pdf", "nome": "y.pdf"}],
    )
    assert job.convenio == "sulamerica"
    assert job.codigos[0].sub_tipo is None  # sulamerica nao exige RM/TC


def _submit_preflight_erros():
    # sem rede: preflight deve falhar cedo (carteirinha invalida).
    # NB: 'adapters.sulamerica.submit' resolve para a FUNCAO (alias no __init__);
    # o modulo e' importado pelo caminho completo.
    from adapters.sulamerica.submit import executar
    r = asyncio.run(executar({"carteirinha": "123", "medico": "1 X",
                              "codigos": [{"codigo_tuss": "1"}],
                              "arquivos": ["/tmp/x.pdf"]}))
    assert r["status"] == "erro_submit", r
    assert "Carteirinha" in r["mensagem"], r


checa("contrato (submit/coletar async, NOME)", _contrato)
checa("split_carteirinha 3-5-4-4-4 + hard stop", _split_carteirinha)
checa("split_medico (CRM NOME)", _split_medico)
checa("validar_arquivo (ext)", _validar_arquivo)
checa("schema carteirinha + sem sub_tipo", _schema_carteirinha_sem_subtipo)
checa("submit preflight rejeita carteirinha invalida", _submit_preflight_erros)

print()
if falhas:
    print(f"== {len(falhas)} FALHA(S): {falhas} ==")
    sys.exit(1)
print("== TODOS OS SMOKES PASSARAM ==")
