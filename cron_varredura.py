"""
cron_varredura.py — Entry point do cron diario (Tempo 2), MULTI-CONVENIO.

Roda 1x/dia. Para CADA convenio registrado: coleta as guias da janela recente
no portal e posta UM sweep_result para o HOP. A transicao de estado e'
idempotente do lado do HOP — este script so' raspa e envia.

Isolamento por convenio: a coleta de um convenio que falhar (ex.: credencial
ausente naquela VPS, portal fora do ar) e' logada e NAO derruba os demais.
CRON_CONVENIOS (CSV no env) restringe quais rodam; vazio = todos.

Uso no crontab:
    15 10 * * *  cd /opt/imag-autorizador && ./run_varredura.sh >> logs/varredura.log 2>&1
"""
import asyncio
import os
import traceback
from datetime import datetime

import config
import callback
from adapters.unimed_recife import coletar as coletar_unimed
from adapters.sassepe import coletar as coletar_sassepe
from adapters.sulamerica import coletar as coletar_sulamerica


# (convenio, coletar async(janela_dias)->list). Adicione convenios aqui.
# NOTA: a varredura do SulAmerica ainda e' skeleton (retorna [] sem efeito) ate'
# a sondagem do historico do portal; registrado aqui para nao esquecer.
_VARREDURAS = [
    ("unimed_recife", coletar_unimed),
    ("sassepe", coletar_sassepe),
    ("sulamerica", coletar_sulamerica),
]


def _convenios_ativos():
    filtro = os.environ.get("CRON_CONVENIOS", "").strip()
    if not filtro:
        return _VARREDURAS
    permitidos = {c.strip() for c in filtro.split(",") if c.strip()}
    return [(n, fn) for n, fn in _VARREDURAS if n in permitidos]


async def _varrer_convenio(nome: str, coletar) -> None:
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
    for nome, coletar in ativos:  # sequencial: um portal por vez
        await _varrer_convenio(nome, coletar)
    print(f"[varredura] fim {datetime.now().isoformat()}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
