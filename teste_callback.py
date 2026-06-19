"""
teste_callback.py — Prova o caminho de VOLTA (worker -> Edge Function) sem a
Edge Function real existir.

Sobe um servidor de mentira que finge ser a `receive-autorizacao`: recebe o
POST do callback.enviar(), recalcula o HMAC sobre o CORPO CRU e compara. Se
bater, 200; se nao, 401. Tambem testa um caso adulterado (deve falhar).

>>> PEGADINHA QUE O CHAT DO ORQUESTRADOR PRECISA SABER <<<
A assinatura e' sobre os BYTES EXATOS do corpo recebido. A Edge Function NAO
pode re-serializar o JSON e assinar de novo — reordenar chaves ou mudar
espacamento muda os bytes e a assinatura nao bate. Validar sempre sobre o
corpo cru (req.text/raw body), nunca sobre JSON.parse + re-stringify.

Uso (venv ativo):
    python teste_callback.py
"""
import os
import hmac
import hashlib
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Segredo de teste — definido ANTES de importar callback (leitura preguicosa).
SEGREDO = "segredo-de-teste-123"
PORTA = 8799
os.environ["HOP_CALLBACK_SECRET"] = SEGREDO
os.environ["HOP_CALLBACK_URL"] = f"http://127.0.0.1:{PORTA}/receive-autorizacao"

import callback  # noqa: E402  (depois de setar o env)

_resultado = {"recebeu": False, "assinatura_valida": None, "payload_tipo": None}


class FakeEdgeFunction(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencia o log padrao do http.server
        pass

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo_cru = self.rfile.read(tamanho)  # BYTES CRUS — nao re-serializar
        recebida = self.headers.get("X-HOP-Signature", "")

        esperada = "sha256=" + hmac.new(
            SEGREDO.encode("utf-8"), corpo_cru, hashlib.sha256
        ).hexdigest()
        valida = hmac.compare_digest(recebida, esperada)  # tempo constante

        _resultado["recebeu"] = True
        _resultado["assinatura_valida"] = valida
        try:
            import json
            _resultado["payload_tipo"] = json.loads(corpo_cru).get("tipo")
        except Exception:
            pass

        self.send_response(200 if valida else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}' if valida else b'{"ok": false}')


def _subir_servidor():
    srv = HTTPServer(("127.0.0.1", PORTA), FakeEdgeFunction)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


async def main():
    print("== teste de callback (worker -> Edge Function) ==\n")
    srv = _subir_servidor()
    await asyncio.sleep(0.3)  # da' tempo do servidor subir

    payload = {
        "tipo": "submit_result",
        "job_id": "teste-1",
        "idempotency_key": "teste-1",
        "org_id": "imag-org-uuid",
        "convenio": "unimed_recife",
        "status": "protocolado",
        "numero_protocolo": "2026000123456",
        "evidencias": [],
        "mensagem": "teste",
    }

    # Caso 1: envio normal — assinatura deve bater
    res = await callback.enviar(payload)
    ok1 = (res["status_code"] == 200 and _resultado["assinatura_valida"] is True
           and _resultado["payload_tipo"] == "submit_result")
    print(f"  [{'PASSOU' if ok1 else 'FALHOU'}] callback assinado e' aceito "
          f"(status={res['status_code']}, assinatura_valida={_resultado['assinatura_valida']})")

    # Caso 2: assinatura adulterada — servidor deve recusar
    import json
    corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            os.environ["HOP_CALLBACK_URL"], content=corpo,
            headers={"Content-Type": "application/json",
                     "X-HOP-Signature": "sha256=deadbeef"},
        )
    ok2 = r.status_code == 401
    print(f"  [{'PASSOU' if ok2 else 'FALHOU'}] callback com assinatura falsa e' "
          f"recusado (status={r.status_code})")

    srv.shutdown()
    print()
    if ok1 and ok2:
        print("RESULTADO: caminho de volta validado. A Edge Function real so'")
        print("precisa repetir esta validacao HMAC sobre o corpo CRU.")
    else:
        print("RESULTADO: FALHOU — revisar callback.py / assinatura.")


if __name__ == "__main__":
    asyncio.run(main())
