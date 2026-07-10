def test_pacote_agente_importa():
    from agente import (
        FalhaDeterministica, MotivoFalha, MOTIVOS_AGENTE,
        ResultadoAgente, ResultadoStatus, AgenteFallback, ContextoSeguranca,
    )
    assert MotivoFalha.SELETOR_NAO_ACHADO in MOTIVOS_AGENTE
    assert MotivoFalha.WAF_CAPTCHA not in MOTIVOS_AGENTE
