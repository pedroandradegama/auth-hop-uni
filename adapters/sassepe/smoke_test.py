"""
smoke_test.py (Sassepe) — validacao offline, SEM portal e SEM credenciais reais.
Testa imports/contrato, CPF hard stop, parse de card do historico, status,
e o schema com cpf. Execute: python adapters/sassepe/smoke_test.py
"""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("SASSEPE_USER", "smoke")
os.environ.setdefault("SASSEPE_PASS", "smoke")

falhas = []


def checa(nome, fn):
    try:
        fn()
        print(f"  [PASSOU] {nome}")
    except Exception as e:
        print(f"  [FALHOU] {nome}: {e}")
        falhas.append(nome)


print("== adapter sassepe · smoke test (offline) ==\n")


def _contrato():
    import adapters.sassepe as sx
    assert sx.NOME == "sassepe"
    assert inspect.iscoroutinefunction(sx.submit)
    assert inspect.iscoroutinefunction(sx.coletar)
checa("adapter expoe submit/coletar async, NOME=sassepe", _contrato)


def _roteamento():
    import worker
    assert worker._ADAPTERS.get("sassepe") == "adapters.sassepe"
    mod = worker._carregar_adapter("sassepe")
    assert hasattr(mod, "submit") and hasattr(mod, "coletar")
checa("worker registra e carrega o adapter sassepe", _roteamento)


def _cpf():
    from adapters.sassepe.submit import normalizar_cpf, SubmitAbortado
    assert normalizar_cpf("643.877.204-68") == "64387720468"
    for ruim in ("123", "", "abc"):
        try:
            normalizar_cpf(ruim)
        except SubmitAbortado:
            continue
        raise AssertionError(f"CPF invalido deveria abortar: {ruim!r}")
checa("CPF: normaliza valido, hard stop em invalido", _cpf)


def _split_medico():
    from adapters.sassepe.submit import _split_medico
    assert _split_medico("11419 FABIO CAMARA") == ("11419", "FABIO CAMARA")
    assert _split_medico("11419 - FABIO CAMARA") == ("11419", "FABIO CAMARA")
    assert _split_medico("FABIO CAMARA") == (None, "FABIO CAMARA")
checa("solicitante: split numero+nome (metodo do piloto)", _split_medico)


def _parse_card():
    from adapters.sassepe.varredura import _parse_card
    txt = ("Guia de SP/SADT - Número da guia: 1189780 Data de emissão da guia: "
           "26/06/2026 Prestador: IMAG Autorizada Beneficiário: AUREA BARBOSA "
           "DA SILVA FISCHLER CPF: 643.877.204-68 Cartão do beneficiário: "
           "SASSE059837004")
    c = _parse_card(txt)
    assert c["numero_protocolo"] == "1189780"
    assert c["status_portal"] == "AUTORIZADO" and c["status_raw"] == "Autorizada"
    assert c["cpf"] == "643.877.204-68"
    assert _parse_card("lixo") is None
checa("parse de card do historico", _parse_card)


def _schema_cpf():
    from schemas import JobPreAutorizacao
    from pydantic import ValidationError
    base = dict(job_id="j", idempotency_key="k", org_id="o", medico="DR X",
                codigos=[{"codigo_tuss": "40808041", "sub_tipo": "RM"}],
                anexos=[{"url": "https://x/y.png"}])
    j = JobPreAutorizacao(**base, cpf="643.877.204-68", convenio="sassepe")
    assert j.cpf and j.carteirinha is None
    # carteirinha-only (unimed/amil) ainda valido
    j2 = JobPreAutorizacao(**base, carteirinha="0034331000065409")
    assert j2.carteirinha and j2.cpf is None
    try:
        JobPreAutorizacao(**base)  # sem identificador
    except ValidationError:
        pass
    else:
        raise AssertionError("job sem cpf/carteirinha deveria ser rejeitado")
checa("schema: cpf opcional, exige ao menos um identificador", _schema_cpf)


print()
if falhas:
    print(f"RESULTADO: {len(falhas)} falha(s) -> {falhas}")
    sys.exit(1)
print("RESULTADO: tudo passou (offline). Fluxo real validado em sessao separada.")
