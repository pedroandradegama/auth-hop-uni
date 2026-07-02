"""
worker_demonstrativo.py — Poller da COLETA de demonstrativos de análise de conta (frente 2).

Espelha worker.py (autorização), mas o verbo é `coletar_demonstrativos` (download), não submit.
Fluxo: POLLA proximo-demonstrativo (claim atômico no HOP) → roteia p/ o adapter do convênio →
coleta o(s) XML no portal → devolve por callback HMAC (receive-demonstrativo), que parseia e
importa no HOP. O worker NUNCA toca Postgres.

Deploy: cron/serviço em /opt/imag-autorizador (venv/). Rodar isolado do worker de autorização.
"""
import asyncio
import importlib
import os
import signal
import traceback

import httpx

import config
import callback

# MODO=cron → drena a fila e encerra (chamado periodicamente por cron; coleta é de baixa frequência).
# Qualquer outro valor → serviço contínuo (poll loop).
_MODO_CRON = os.environ.get("MODO", "").lower() == "cron"

# whitelist convênio → módulo do adapter (só os que implementam coletar_demonstrativos)
_ADAPTERS = {
    "sulamerica": "adapters.sulamerica",
    "sassepe": "adapters.sassepe",
}

_parar = asyncio.Event()


def _carregar_coletor(slug: str):
    nome_mod = _ADAPTERS.get(slug)
    if not nome_mod:
        raise ValueError(f"convênio sem coletor de demonstrativo: {slug!r}")
    mod = importlib.import_module(nome_mod)
    fn = getattr(mod, "coletar_demonstrativos", None)
    if fn is None:
        raise ValueError(f"adapter {slug!r} não expõe coletar_demonstrativos")
    return fn


async def _processar(job: dict):
    coleta_id = job.get("id")
    slug = job.get("convenio_slug")
    try:
        coletor = _carregar_coletor(slug)
        resultado = await coletor(job.get("data_ini"), job.get("data_fim"))
    except Exception as e:
        resultado = {"status": "erro_coleta", "arquivos": [], "evidencias": [],
                     "mensagem": f"Falha no worker: {e}"}
        print("[coleta-erro]", traceback.format_exc(), flush=True)

    payload = {
        "tipo": "coleta_result",
        "coleta_id": coleta_id,
        "convenio_slug": slug,
        "status": resultado.get("status", "erro"),
        "arquivos": resultado.get("arquivos", []),
        "evidencias": resultado.get("evidencias", []),
        "mensagem": resultado.get("mensagem"),
    }
    try:
        r = await callback.enviar_para(config.callback_demonstrativo_url(), payload, timeout=120)
        print(f"[callback] coleta {coleta_id} → {r['status_code']} ({payload['status']}, "
              f"{len(payload['arquivos'])} arq)", flush=True)
    except Exception:
        print("[callback-falhou]", traceback.format_exc(), flush=True)


async def _pollar_uma_vez(client: httpx.AsyncClient) -> bool:
    headers = {"Authorization": f"Bearer {config.worker_inbound_secret()}"}
    r = await client.post(config.proximo_demonstrativo_url(), headers=headers, json={})
    if r.status_code == 204:
        return False
    r.raise_for_status()
    job = r.json()
    print(f"[poll] coletando demonstrativo job {job.get('id')} ({job.get('convenio_slug')} "
          f"{job.get('data_ini')}..{job.get('data_fim')})", flush=True)
    await _processar(job)
    return True


async def main():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _parar.set)
        except NotImplementedError:
            pass
    print(f"[worker-demonstrativo] iniciado (modo={'cron' if _MODO_CRON else 'serviço'}).", flush=True)
    async with httpx.AsyncClient(timeout=180) as client:
        while not _parar.is_set():
            try:
                processou = await _pollar_uma_vez(client)
            except Exception:
                print("[poll-erro]", traceback.format_exc(), flush=True)
                processou = False
            # cron: sem job (204) = fila drenada → encerra.
            if _MODO_CRON and not processou:
                break
            intervalo = config.POLL_INTERVAL_SEG if processou else config.POLL_INTERVAL_OCIOSO_SEG
            try:
                await asyncio.wait_for(_parar.wait(), timeout=intervalo)
            except asyncio.TimeoutError:
                pass
    print("[worker-demonstrativo] encerrado.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
