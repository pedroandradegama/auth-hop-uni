"""Job malformado do HOP não pode virar reserva órfã.

Caso (17/set/2026, job fa134b3f): o HOP mandou o CPF da paciente no campo
`carteirinha` para o Sassepe. O schema reprovou ("carteirinha com 11 digitos,
minimo 15"), o worker imprimiu "[poll] erro:" e seguiu — mas o CLAIM já tinha
acontecido, então a linha ficou `em_execucao` no HOP.

40 minutos depois o watchdog a converteu em `requer_humano` com motivo_negativa
VAZIO. O operador recebeu um job em revisão humana sem nenhuma explicação, e não
havia evidência, telemetria de agente nem log acessível para ele.
"""
import importlib

import pytest

worker = importlib.import_module("worker")


class _CallbackFake:
    def __init__(self, explode=False):
        self.enviados = []
        self.explode = explode

    async def enviar(self, payload):
        if self.explode:
            raise RuntimeError("HOP fora do ar")
        self.enviados.append(payload)
        return {"ok": True}


def _erro_de_carteirinha():
    """O erro real: pydantic reprovando a carteirinha curta."""
    from schemas import JobPreAutorizacao
    try:
        JobPreAutorizacao(**{
            "job_id": "fa134b3f", "idempotency_key": "k1", "org_id": "o1",
            "convenio": "sassepe", "carteirinha": "402.244.904-78",
            "medico": "NAYARA ROCHA", "codigos": [{"codigo_tuss": "40901122"}],
            "anexos": [],
        })
    except Exception as e:
        return e
    raise AssertionError("esperava ValidationError")


class TestResumo:
    def test_traduz_o_erro_do_pydantic_em_uma_linha(self):
        msg = worker._resumir_validacao(_erro_de_carteirinha())
        assert "carteirinha" in msg
        assert "Traceback" not in msg
        assert "errors.pydantic.dev" not in msg   # link de doc não ajuda operador
        assert len(msg) <= 400

    def test_excecao_sem_errors_nao_quebra(self):
        assert "explodiu" in worker._resumir_validacao(RuntimeError("explodiu"))


class TestDevolucao:
    @pytest.mark.asyncio
    async def test_fecha_o_job_no_hop_em_vez_de_deixar_orfao(self, monkeypatch):
        fake = _CallbackFake()
        monkeypatch.setattr(worker, "callback", fake)
        bruto = {"job_id": "fa134b3f", "idempotency_key": "k1",
                 "org_id": "o1", "convenio": "sassepe"}
        await worker._devolver_job_invalido(bruto, _erro_de_carteirinha())

        assert len(fake.enviados) == 1
        p = fake.enviados[0]
        assert p["status"] == "erro_submit"       # nada tocou o portal (I1)
        assert p["job_id"] == "fa134b3f"
        assert p["idempotency_key"] == "k1"
        assert p["numero_protocolo"] is None
        assert "carteirinha" in p["mensagem"]

    @pytest.mark.asyncio
    async def test_sem_job_id_nao_tenta_postar(self, monkeypatch):
        """Sem job_id não há o que fechar; postar seria lixo no HOP."""
        fake = _CallbackFake()
        monkeypatch.setattr(worker, "callback", fake)
        await worker._devolver_job_invalido({}, _erro_de_carteirinha())
        assert fake.enviados == []

    @pytest.mark.asyncio
    async def test_callback_fora_do_ar_nao_derruba_o_worker(self, monkeypatch):
        monkeypatch.setattr(worker, "callback", _CallbackFake(explode=True))
        await worker._devolver_job_invalido(
            {"job_id": "x"}, _erro_de_carteirinha())   # não levanta
