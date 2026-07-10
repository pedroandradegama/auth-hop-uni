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


async def _enviar_para(url: str, payload: dict) -> dict:
    """Assina o corpo CRU (HMAC) e posta para `url`. NUNCA re-serializa o JSON
    depois de assinar — a Edge valida a assinatura sobre os bytes exatos."""
    corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assinatura = _assinar(corpo)
    headers = {
        "Content-Type": "application/json",
        "X-HOP-Signature": f"sha256={assinatura}",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, content=corpo, headers=headers)
        return {"ok": resp.is_success, "status_code": resp.status_code,
                "body": resp.text}


async def enviar(payload: dict) -> dict:
    """Posta o payload (submit_result ou sweep_result) p/ receive-autorizacao.
    Retorna {"ok": bool, "status_code": int, "body": str}."""
    return await _enviar_para(config.callback_url(), payload)


async def enviar_verificacao(payload: dict) -> dict:
    """Posta o resultado de verificacao de senha (Camada 3) p/ receive-verificacao.
    Mesmo HMAC (HOP_CALLBACK_SECRET); corpo `{job_id, resultado}`."""
    return await _enviar_para(config.callback_verificacao_url(), payload)


async def enviar_agent_trace(payload: dict) -> dict:
    """Telemetria do loop de agente (tipo=agent_trace) p/ receive-autorizacao.
    MESMO endpoint e MESMO HMAC do submit_result. Best-effort: o chamador
    engole excecao (telemetria nunca derruba o circuito principal)."""
    return await _enviar_para(config.callback_url(), payload)
