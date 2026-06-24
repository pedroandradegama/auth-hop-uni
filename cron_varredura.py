"""
cron_varredura.py — Entry point do cron diario (Tempo 2).

Roda 1x/dia (sugestao: junto/logo apos o daily report das 07:00 BRT). Coleta
as guias da janela recente no portal e posta UM sweep_result para o HOP. A
transicao de estado e' idempotente do lado do HOP — este script so' raspa e
envia, mesmo que a guia ja tenha sido vista em dias anteriores.

Uso no crontab:
    0 7 * * *  cd /opt/imag-autorizador && /usr/bin/python3 cron_varredura.py >> logs/varredura.log 2>&1
"""
import asyncio
from datetime import datetime

import config
from adapters.unimed_recife import coletar
import callback


async def main():
    inicio = datetime.now().isoformat()
    print(f"[varredura] inicio {inicio}", flush=True)

    try:
        guias = await coletar(config.VARREDURA_JANELA_DIAS)
    except Exception as e:
        import traceback
        print(f"[varredura] FALHA na coleta: {e}\n{traceback.format_exc()}",
              flush=True)
        return

    print(f"[varredura] {len(guias)} guia(s) coletada(s)", flush=True)

    payload = {
        "tipo": "sweep_result",
        "convenio": "unimed_recife",
        "janela_dias": config.VARREDURA_JANELA_DIAS,
        "guias": guias,
    }

    try:
        res = await callback.enviar(payload)
        print(f"[varredura] callback -> {res['status_code']} ok={res['ok']}",
              flush=True)
    except Exception as e:
        import traceback
        print(f"[varredura] FALHA no callback: {e}\n{traceback.format_exc()}",
              flush=True)


if __name__ == "__main__":
    asyncio.run(main())
