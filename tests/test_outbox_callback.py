"""O callback ao HOP não pode se perder — principalmente depois de um ato
irreversível.

Revisão externa (29/09/2026): `worker._processar` fazia
`await callback.enviar(payload)` e descartava o retorno. `callback.enviar`
devolve `{"ok": False}` para 4xx/5xx SEM levantar exceção, então um 500 do HOP
era indistinguível de sucesso.

O pior caso não é o watchdog marcar requer_humano 30 min depois. É o submit ter
sido irreversível — guia enviada, protocolo capturado — e o único registro disso
sumir num POST que ninguém conferiu. Reprocessar depois emite guia duplicada,
que é violação direta do I1.
"""
import asyncio
import importlib
import json
import os

import pytest

outbox = importlib.import_module("outbox")


@pytest.fixture
def dir_outbox(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setattr(outbox, "ESPERA_BASE_S", 0)   # sem sleep real no teste
    return tmp_path / "outbox"


def _envio(respostas):
    """Corrotina de envio que devolve as respostas na ordem dada."""
    seq = list(respostas)
    chamadas = []

    async def _fn(payload):
        chamadas.append(payload)
        return seq.pop(0) if seq else {"ok": True, "status_code": 200}
    _fn.chamadas = chamadas
    return _fn


class TestRespostaNegativaNaoEhSucesso:
    @pytest.mark.asyncio
    async def test_500_persiste_o_callback(self, dir_outbox):
        envio = _envio([{"ok": False, "status_code": 500, "body": "boom"}] * 3)
        ok = await outbox.entregar(envio, "submit_result",
                                   {"job_id": "x", "numero_protocolo": "123456"})
        assert ok is False
        pend = outbox.pendentes()
        assert len(pend) == 1
        item = json.load(open(pend[0], encoding="utf-8"))
        assert item["payload"]["numero_protocolo"] == "123456"

    @pytest.mark.asyncio
    async def test_tenta_de_novo_antes_de_desistir(self, dir_outbox):
        envio = _envio([{"ok": False, "status_code": 503, "body": ""},
                        {"ok": True, "status_code": 200, "body": ""}])
        assert await outbox.entregar(envio, "submit_result", {"job_id": "x"}) is True
        assert len(envio.chamadas) == 2
        assert outbox.pendentes() == []

    @pytest.mark.asyncio
    async def test_excecao_de_transporte_tambem_persiste(self, dir_outbox):
        async def _fn(payload):
            raise ConnectionError("rede caiu")
        assert await outbox.entregar(_fn, "submit_result", {"job_id": "x"}) is False
        assert len(outbox.pendentes()) == 1

    @pytest.mark.asyncio
    async def test_sucesso_nao_deixa_residuo(self, dir_outbox):
        envio = _envio([{"ok": True, "status_code": 200, "body": ""}])
        assert await outbox.entregar(envio, "submit_result", {"job_id": "x"}) is True
        assert outbox.pendentes() == []


class TestReentrega:
    @pytest.mark.asyncio
    async def test_reentrega_e_limpa(self, dir_outbox):
        outbox.gravar("submit_result", {"job_id": "x", "numero_protocolo": "9"})
        envio = _envio([{"ok": True, "status_code": 200, "body": ""}])
        n = await outbox.reenviar_pendentes({"submit_result": envio})
        assert n == 1
        assert outbox.pendentes() == []
        assert envio.chamadas[0]["numero_protocolo"] == "9"

    @pytest.mark.asyncio
    async def test_hop_ainda_fora_mantem_o_arquivo(self, dir_outbox):
        outbox.gravar("submit_result", {"job_id": "x"})
        envio = _envio([{"ok": False, "status_code": 502, "body": ""}])
        assert await outbox.reenviar_pendentes({"submit_result": envio}) == 0
        assert len(outbox.pendentes()) == 1      # nada é descartado

    @pytest.mark.asyncio
    async def test_tipo_desconhecido_nao_e_descartado(self, dir_outbox):
        """Worker antigo pode ter gravado um tipo que esta versão não conhece."""
        outbox.gravar("tipo_do_futuro", {"job_id": "x"})
        assert await outbox.reenviar_pendentes({"submit_result": _envio([])}) == 0
        assert len(outbox.pendentes()) == 1

    @pytest.mark.asyncio
    async def test_ordem_e_a_de_gravacao(self, dir_outbox):
        for i in range(3):
            outbox.gravar("submit_result", {"job_id": f"job{i}"})
        envio = _envio([])
        await outbox.reenviar_pendentes({"submit_result": envio})
        assert [c["job_id"] for c in envio.chamadas] == ["job0", "job1", "job2"]

    def test_gravacao_e_atomica(self, dir_outbox):
        """tmp + rename: processo morto no meio não deixa JSON truncado na fila."""
        import inspect
        assert "os.replace(tmp, destino)" in inspect.getsource(outbox.gravar)


class TestWorkerUsaOOutbox:
    def test_nenhum_callback_solto_no_worker(self):
        """Toda chamada direta a callback.enviar* fora do outbox volta a ser
        um 500 silencioso."""
        import inspect
        worker = importlib.import_module("worker")
        src = inspect.getsource(worker)
        for linha in src.splitlines():
            t = linha.strip()
            if t.startswith("await callback.enviar"):
                raise AssertionError(f"callback sem outbox: {t}")

    def test_drenar_reentrega_antes_de_puxar_job_novo(self):
        import inspect
        worker = importlib.import_module("worker")
        corpo = inspect.getsource(worker.drenar)
        assert corpo.index("reenviar_pendentes") < corpo.index("_drenar_fila")
