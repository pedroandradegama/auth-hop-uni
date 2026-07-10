from agente import ResultadoAgente, ResultadoStatus


def _res(status, **kw):
    return ResultadoAgente(status=status, job_id="job-1", **kw)


def test_mapa_concluido():
    import worker
    r = worker._mapear_resultado_agente(_res(ResultadoStatus.CONCLUIDO, protocolo="123"))
    assert r["status"] == "protocolado"
    assert r["numero_protocolo"] == "123"
    assert r.get("requer_captura_manual") is not True


def test_mapa_requer_humano():
    import worker
    r = worker._mapear_resultado_agente(_res(ResultadoStatus.REQUER_HUMANO,
                                             diagnostico="captcha"))
    assert r["status"] == "requer_humano"
    assert r["numero_protocolo"] is None
    assert r["requer_captura_manual"] is True
    assert "captcha" in r["mensagem"]


def test_mapa_resultado_incerto_nunca_reenfileira():
    import worker
    r = worker._mapear_resultado_agente(_res(ResultadoStatus.RESULTADO_INCERTO,
                                             diagnostico="erro pos-submit"))
    assert r["status"] == "requer_humano"
    assert r["requer_captura_manual"] is True
    assert r.get("reenfileirar") is not True
