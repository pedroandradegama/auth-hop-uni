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


async def enviar_para(url: str, payload: dict, timeout: int = 60) -> dict:
    """Posta o payload assinado (HMAC) para uma Edge Function do HOP.
    O corpo é assinado exatamente como enviado (bytes crus) — a Edge valida sobre o corpo cru."""
    corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-HOP-Signature": f"sha256={_assinar(corpo)}",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, content=corpo, headers=headers)
        return {"ok": resp.is_success, "status_code": resp.status_code, "body": resp.text}


async def enviar(payload: dict) -> dict:
    """Posta o resultado de autorização (submit_result/sweep_result) p/ receive-autorizacao."""
    return await enviar_para(config.callback_url(), payload, timeout=30)
