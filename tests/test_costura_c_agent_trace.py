import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

SEGREDO = "segredo-teste-123"
_capturado = {}


class _H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        corpo = self.rfile.read(n)
        esperado = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
        _capturado["assinatura_ok"] = (self.headers.get("X-HOP-Signature") == esperado)
        _capturado["payload"] = json.loads(corpo)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true,"execucao_id":"exec-1"}')

    def log_message(self, *a):
        pass


@pytest.mark.asyncio
async def test_agent_trace_assinado(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    porta = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    monkeypatch.setenv("HOP_CALLBACK_SECRET", SEGREDO)
    monkeypatch.setenv("HOP_CALLBACK_URL", f"http://127.0.0.1:{porta}/")
    import importlib
    import config
    import callback
    importlib.reload(config)
    importlib.reload(callback)

    from agente import ResultadoAgente, ResultadoStatus
    res = ResultadoAgente(status=ResultadoStatus.REQUER_HUMANO, job_id="job-1",
                          diagnostico="captcha", motivo_fallback="validacao_portal")
    payload = res.para_agent_trace(org_id="org-1", convenio="unimed_recife")
    resp = await callback.enviar_agent_trace(payload)

    srv.shutdown()
    assert resp["ok"] is True
    assert _capturado["assinatura_ok"] is True
    assert _capturado["payload"]["tipo"] == "agent_trace"
    assert _capturado["payload"]["job_id"] == "job-1"
