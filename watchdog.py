"""
watchdog.py — aciona a edge `watchdog-autorizacao` (reverte reservas expiradas).

Rodar por CRON na VPS (run_watchdog.sh), ex.: a cada 10 min. Sem estado: faz um
POST autenticado e loga o resultado. TODA a logica (lease expirado -> pendente,
teto de tentativas -> requer_captura_manual, respeitar I1 = nunca re-enfileirar
falha PÓS-submit) vive no HOP; aqui so' disparamos o gatilho periodico.

Handoff: docs/HANDOFF_loop_engineering_gaps.md §2.2.
"""
import asyncio

import httpx

import config


async def _rodar() -> int:
    url = config.watchdog_url()
    headers = {"Authorization": f"Bearer {config.worker_inbound_secret()}"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json={})
    print(f">> watchdog {r.status_code}: {r.text[:500]}", flush=True)
    r.raise_for_status()
    return 0


def main() -> None:
    try:
        asyncio.run(_rodar())
    except Exception as e:
        # Falha do watchdog nao pode derrubar o host do cron; loga e sai != 0.
        import traceback
        print("[watchdog-falhou]", traceback.format_exc(), flush=True)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
