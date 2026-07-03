"""
teste_verificacao.py — Checagem de conectividade do POLL de verificação (dry).

NÃO roda `adapter.verificar` nem posta callback — só confirma que o endpoint
`proximo-job-verificacao` responde com o secret e mostra o shape do job (ou 204).
Útil pós-deploy do HOP, antes de ligar VERIFICACAO_HABILITADA.

Execute: set -a && source .env && set +a && python teste_verificacao.py
"""
import asyncio
import json

import httpx

import config


async def main():
    url = config.proximo_job_verificacao_url()
    headers = {"Authorization": f"Bearer {config.worker_inbound_secret()}"}
    print(f">> POST {url} (dry — não executa verificar)\n")
    async with httpx.AsyncClient(timeout=30) as client:
        # health check primeiro (GET ?health_check)
        try:
            h = await client.get(url, params={"health_check": "1"})
            print(f"health_check: {h.status_code} {h.text[:200]}")
        except Exception as e:
            print(f"health_check falhou: {e}")
        # poll real (claim atômico — consome um job se houver!)
        r = await client.post(url, headers=headers, json={})
        print(f"\npoll: HTTP {r.status_code}")
        if r.status_code == 204:
            print("fila de verificação vazia (204).")
            return
        if r.is_success:
            print("job:", json.dumps(r.json(), ensure_ascii=False, indent=2))
        else:
            print("corpo:", r.text[:400])


if __name__ == "__main__":
    asyncio.run(main())
