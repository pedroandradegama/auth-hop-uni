from schemas import JobPreAutorizacao


def _job():
    return JobPreAutorizacao(
        job_id="j1", idempotency_key="k1", org_id="o1",
        convenio="unimed_intercambio", carteirinha="08650004956229017",
        medico="PEDRO ANDRADE GAMA", crm="21798",
        codigos=[{"codigo_tuss": "40901165", "quantidade": 1}])


def test_job_agente_carrega_crm():
    import worker
    dados = {"codigos": [{"codigo_tuss": "40901165", "quantidade": 1}]}
    ja = worker._montar_job_agente(_job(), dados, [])
    assert ja["crm"] == "21798"
    assert ja["medico"] == "PEDRO ANDRADE GAMA"
    assert ja["convenio"] == "unimed_intercambio"
