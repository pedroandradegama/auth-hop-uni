"""
cron_varredura.py — Entry point do cron diario (Tempo 2), MULTI-CONVENIO.

Roda 1x/dia (sugestao: junto/logo apos o daily report das 07:00 BRT). Para CADA
convenio registrado: coleta as guias da janela recente no portal e posta UM
sweep_result para o HOP. A transicao de estado e' idempotente do lado do HOP —
este script so' raspa e envia, mesmo que a guia ja tenha sido vista antes.

Isolamento por convenio: a coleta de um convenio que falhar (ex.: credencial
ausente naquela VPS, portal fora do ar) e' logada e NAO derruba os demais.

Registro: _VARREDURAS lista (convenio, coletar). Unimed segue em portal/;
convenios novos entram via adapters/<nome> (mesma forma do roteamento do worker).

Uso no crontab:
    0 7 * * *  cd /opt/imag-autorizador && /usr/bin/python3 cron_varredura.py >> logs/varredura.log 2>&1
"""
import asyncio
import os
import traceback
from datetime import datetime

import config
import callback
from portal import varredura as varredura_unimed
from adapters.sassepe import coletar as coletar_sassepe


# (convenio, funcao coletar async(janela_dias)->list). Adicione novos convenios
# aqui. CRON_CONVENIOS (CSV no env) restringe quais rodam; vazio = todos.
_VARREDURAS = [
    ("unimed_recife", varredura_unimed.coletar),
    ("sassepe", coletar_sassepe),
]


def _convenios_ativos():
    filtro = os.environ.get("CRON_CONVENIOS", "").strip()
    if not filtro:
        return _VARREDURAS
    permitidos = {c.strip() for c in filtro.split(",") if c.strip()}
    return [(nome, fn) for nome, fn in _VARREDURAS if nome in permitidos]


async def _varrer_convenio(nome: str, coletar) -> None:
    """Coleta um convenio e posta o sweep_result. Isolado: excecao aqui nao
    afeta os outros convenios (apenas loga)."""
    janela = config.VARREDURA_JANELA_DIAS
    try:
        guias = await coletar(janela)
    except Exception as e:
        print(f"[varredura:{nome}] FALHA na coleta: {e}\n{traceback.format_exc()}",
              flush=True)
        return

    print(f"[varredura:{nome}] {len(guias)} guia(s) coletada(s)", flush=True)

    payload = {
        "tipo": "sweep_result",
        "convenio": nome,
        "janela_dias": janela,
        "guias": guias,
    }
    try:
        res = await callback.enviar(payload)
        print(f"[varredura:{nome}] callback -> {res['status_code']} ok={res['ok']}",
              flush=True)
    except Exception as e:
        print(f"[varredura:{nome}] FALHA no callback: {e}\n{traceback.format_exc()}",
              flush=True)


async def main():
    print(f"[varredura] inicio {datetime.now().isoformat()}", flush=True)
    ativos = _convenios_ativos()
    print(f"[varredura] convenios: {[n for n, _ in ativos]}", flush=True)
    # Sequencial: um portal por vez (serializa browser, como o worker).
    for nome, coletar in ativos:
        await _varrer_convenio(nome, coletar)
    print(f"[varredura] fim {datetime.now().isoformat()}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
