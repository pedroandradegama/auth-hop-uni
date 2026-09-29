import pytest



@pytest.fixture(autouse=True)
def _outbox_isolado(tmp_path, monkeypatch):
    """Nenhum teste escreve na outbox real nem dorme o backoff de verdade.

    Sem isto, qualquer teste que exercite um callback recusado grava JSON dentro
    do repositório e paga 6s de espera (2s + 4s) — foi o que aconteceu ao
    introduzir a outbox, em `test_callback_fora_do_ar_nao_derruba_o_worker`.
    """
    import config
    import outbox
    monkeypatch.setattr(config, "OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setattr(outbox, "ESPERA_BASE_S", 0)
