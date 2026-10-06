"""O canario nao pode drenar a fila inteira por acidente."""
import importlib

import pytest


worker = importlib.import_module("worker")


def test_limite_padrao_preserva_o_cron_atual(monkeypatch):
    monkeypatch.delenv("DRENAR_MAX_JOBS", raising=False)
    assert worker._limite_drenagem_do_ambiente() == 50


def test_limite_um_permite_canario(monkeypatch):
    monkeypatch.setenv("DRENAR_MAX_JOBS", "1")
    assert worker._limite_drenagem_do_ambiente() == 1


@pytest.mark.parametrize("valor", ["0", "-1", "um", "1.5"])
def test_limite_invalido_recusa_drenagem(monkeypatch, valor):
    monkeypatch.setenv("DRENAR_MAX_JOBS", valor)
    with pytest.raises(RuntimeError, match="DRENAR_MAX_JOBS invalido"):
        worker._limite_drenagem_do_ambiente()


def test_script_do_canario_reusa_lock_do_cron_e_limite():
    script = open("run_sassepe_canary.sh", encoding="utf-8").read()
    assert "DRENAR_MAX_JOBS=1" in script
    assert "/usr/bin/flock -n /tmp/autorizador.lock" in script


@pytest.mark.asyncio
async def test_erro_de_poll_identifica_fila_e_classe(capsys):
    async def _falha(_client):
        raise RuntimeError("diagnostico local")

    assert await worker._drenar_fila(None, _falha, lote=1, restante=1,
                                     fila="submit") == 0
    saida = capsys.readouterr().out
    assert "fila=submit" in saida
    assert "classe=RuntimeError" in saida
