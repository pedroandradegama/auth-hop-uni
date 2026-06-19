"""
callback.py — Envio autenticado de resultados para o HOP.

O worker e o cron NUNCA tocam o Postgres. Eles so' fazem POST para a Edge
Function `receive-autorizacao`, assinando o corpo com HMAC-SHA256. A Edge
Function valida a assinatura antes de chamar os RPCs. (Sem service_role no
lado da VPS — padrao consagrado do HOP.)
"""
import hashlib
import hmac
import json

import httpx

import config


def _assinar(corpo: bytes) -> str:
    segredo = config.callback_hmac_secret().encode("utf-8")
    return hmac.new(segredo, corpo, hashlib.sha256).hexdigest()


async def enviar(payload: dict) -> dict:
    """Posta o payload (submit_result ou sweep_result) para o HOP.
    Retorna {"ok": bool, "status_code": int, "body": str}."""
    corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assinatura = _assinar(corpo)
    headers = {
        "Content-Type": "application/json",
        "X-HOP-Signature": f"sha256={assinatura}",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(config.callback_url(), content=corpo, headers=headers)
        return {"ok": resp.is_success, "status_code": resp.status_code,
                "body": resp.text}
