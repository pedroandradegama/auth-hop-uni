import pytest

from schemas import JobPreAutorizacao


def _base(**kw):
    d = dict(job_id="j1", idempotency_key="k1", org_id="o1",
             convenio="unimed_intercambio", carteirinha="08650002578827002",
             medico="PEDRO ANDRADE GAMA", crm="21798",
             codigos=[{"codigo_tuss": "40901122", "quantidade": 2}])
    d.update(kw)
    return d


def test_intercambio_sem_anexo_e_valido():
    job = JobPreAutorizacao(**_base())
    assert job.crm == "21798"
    assert job.codigos[0].quantidade == 2
    assert job.anexos == []


def test_intercambio_dispensa_subtipo():
    # CONNECTA nao usa RM/TC (campo Tipo fixo). Nao deve exigir sub_tipo.
    job = JobPreAutorizacao(**_base())
    assert job.codigos[0].sub_tipo is None


def test_unimed_recife_ainda_exige_anexo():
    with pytest.raises(Exception):
        JobPreAutorizacao(job_id="j", idempotency_key="k", org_id="o",
                          convenio="unimed_recife", carteirinha="08650002578827002",
                          medico="X",
                          codigos=[{"codigo_tuss": "41101219", "sub_tipo": "RM"}])
