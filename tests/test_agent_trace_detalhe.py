from agente import ResultadoAgente, ResultadoStatus


def test_agent_trace_inclui_detalhe_fallback():
    res = ResultadoAgente(
        status=ResultadoStatus.REQUER_HUMANO, job_id="job-1",
        motivo_fallback="estado_inesperado", etapa_fallback="submit_sassepe",
        detalhe_fallback="Solicitante 'SANDRA' nao encontrado no dropdown (CRM ausente).")
    trace = res.para_agent_trace(org_id="org-1", convenio="sassepe")
    assert trace["detalhe_fallback"].startswith("Solicitante 'SANDRA'")
    assert trace["etapa_fallback"] == "submit_sassepe"


def test_detalhe_fallback_default_vazio():
    res = ResultadoAgente(status=ResultadoStatus.CONCLUIDO, job_id="j2")
    assert res.para_agent_trace(org_id="o", convenio="c")["detalhe_fallback"] == ""
