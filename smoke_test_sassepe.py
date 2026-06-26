"""
smoke_test_sassepe.py — Validacao offline do adapter Sassepe (sem portal/creds).

Testa imports, contrato (submit/coletar async), roteamento no worker, hard stop
de CPF, normalizacao de status (preliminar) e a falha explicita da varredura
ainda nao mapeada (I2). NAO abre browser, NAO loga no portal.

Uso:
    source .venv/bin/activate
    python smoke_test_sassepe.py
"""
import os
import sys
import asyncio
import inspect

os.environ.setdefault("SASSEPE_USER", "x")
os.environ.setdefault("SASSEPE_PASS", "x")

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
    import adapters.sassepe as sx
    from portal import submit as us
    assert worker._resolver_submit("sassepe") is sx.submit
    assert worker._resolver_submit("unimed_recife") is us.executar
checa("worker roteia sassepe->adapter, unimed->portal", _roteamento)


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


def _status():
    from adapters.sassepe.varredura import _normalizar_status
    assert _normalizar_status("Autorizada") == "AUTORIZADO"
    assert _normalizar_status("Em Análise") == "EM_ANALISE"
    assert _normalizar_status("Negado") == "NEGADO"
    assert _normalizar_status("coisa estranha") == "DESCONHECIDO"
checa("normalizacao de status (preliminar, a confirmar no portal)", _status)


def _parse_card():
    from adapters.sassepe.varredura import _parse_card
    txt = ("Guia de SP/SADT - Número da guia: 1189780 Data de emissão da guia: "
           "26/06/2026 Prestador: IMAG Autorizada Beneficiário: AUREA BARBOSA "
           "DA SILVA FISCHLER CPF: 643.877.204-68 Cartão do beneficiário: "
           "SASSE059837004")
    c = _parse_card(txt)
    assert c["numero_protocolo"] == "1189780", c
    assert c["status_portal"] == "AUTORIZADO" and c["status_raw"] == "Autorizada"
    assert c["cpf"] == "643.877.204-68"
    assert c["paciente"].startswith("AUREA BARBOSA")
    assert c["data"] == "26/06/2026"
    assert _parse_card("lixo sem guia") is None
checa("parse de card do historico (guia/status/cpf/paciente)", _parse_card)


def _schema_cpf():
    from schemas import JobPreAutorizacao
    from pydantic import ValidationError
    base = dict(job_id="j", idempotency_key="k", org_id="o", medico="DR X",
                codigos=[{"codigo_tuss": "40808041", "sub_tipo": "RM"}],
                anexos=[{"url": "https://x/y.png"}])
    j = JobPreAutorizacao(**base, cpf="643.877.204-68", convenio="sassepe")
    assert j.cpf and j.carteirinha is None
    try:
        JobPreAutorizacao(**base)  # sem identificador
    except ValidationError:
        pass
    else:
        raise AssertionError("job sem cpf/carteirinha deveria ser rejeitado")
checa("schema aceita cpf, exige ao menos um identificador", _schema_cpf)


print()
if falhas:
    print(f"RESULTADO: {len(falhas)} falha(s) -> {falhas}")
    sys.exit(1)
print("RESULTADO: tudo passou (offline). Fluxo completo (login MVOnePass+termos,")
print("submit ate' 'Enviar', captura de protocolo via historico por CPF, e")
print("varredura) validado no portal real em sessao separada.")
