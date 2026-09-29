"""Outbox durável para os callbacks ao HOP.

Motivo (revisão de 29/09/2026): `worker._processar` fazia
`await callback.enviar(payload)` e DESCARTAVA o retorno. `callback.enviar`
devolve `{"ok": False, ...}` para 4xx/5xx sem levantar exceção — então uma
resposta 500 do HOP era indistinguível de sucesso.

O pior caso não é o job voltar para revisão humana 30 min depois pelo watchdog.
É o submit ter sido IRREVERSÍVEL: guia enviada ao convênio, protocolo capturado,
e o único registro disso perdido num POST que ninguém conferiu. Reprocessar
depois emitiria guia duplicada — violação direta do I1. O protocolo tem que
sobreviver à indisponibilidade do HOP.

Desenho mínimo, de propósito: um arquivo JSON por callback pendente, reentregue
no início da próxima execução. O modo padrão é cron (o processo morre ao fim da
drenagem), então fila em memória não serviria.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import config

# Tentativas dentro do MESMO processo antes de gravar em disco. Cobre o caso
# comum (indisponibilidade de segundos) sem esperar o próximo ciclo do cron.
TENTATIVAS_IMEDIATAS = 3
ESPERA_BASE_S = 2.0


def _garantir_dir() -> str:
    os.makedirs(config.OUTBOX_DIR, exist_ok=True)
    return config.OUTBOX_DIR


def pendentes() -> list[str]:
    """Callbacks não entregues, do mais antigo para o mais novo."""
    d = _garantir_dir()
    return sorted(
        os.path.join(d, n) for n in os.listdir(d) if n.endswith(".json")
    )


def gravar(tipo: str, payload: dict) -> str:
    """Persiste um callback não entregue. Escrita atômica (tmp + rename): um
    processo morto no meio não pode deixar JSON truncado na fila."""
    d = _garantir_dir()
    # Nanossegundo no nome: a ordem de reentrega tem que ser a de gravacao, e
    # varios callbacks cabem no mesmo segundo. Sem isso a ordenacao caia no
    # sufixo aleatorio.
    nome = (f"{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 10**9:09d}"
            f"_{tipo}_{uuid.uuid4().hex[:8]}.json")
    destino = os.path.join(d, nome)
    tmp = destino + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"tipo": tipo, "payload": payload,
                   "gravado_em": time.time()}, f, ensure_ascii=False)
    os.replace(tmp, destino)
    print(f"[outbox] callback {tipo} guardado para reentrega: {nome}", flush=True)
    return destino


async def entregar(enviar_fn, tipo: str, payload: dict) -> bool:
    """Tenta entregar; persiste se não conseguir. Nunca levanta.

    `enviar_fn` é uma corrotina que devolve {"ok": bool, "status_code": int, ...}.
    """
    for tentativa in range(1, TENTATIVAS_IMEDIATAS + 1):
        try:
            res = await enviar_fn(payload)
            if res.get("ok"):
                return True
            print(f"[callback] {tipo} recusado pelo HOP "
                  f"(status={res.get('status_code')}, tentativa {tentativa}/"
                  f"{TENTATIVAS_IMEDIATAS}): {str(res.get('body'))[:200]}",
                  flush=True)
        except Exception as e:
            print(f"[callback] {tipo} falhou no transporte "
                  f"(tentativa {tentativa}/{TENTATIVAS_IMEDIATAS}): {e}",
                  flush=True)
        if tentativa < TENTATIVAS_IMEDIATAS:
            await asyncio.sleep(ESPERA_BASE_S * (2 ** (tentativa - 1)))
    gravar(tipo, payload)
    return False


async def reenviar_pendentes(rotas: dict) -> int:
    """Reentrega o que está no disco. `rotas` mapeia tipo -> corrotina de envio.

    O arquivo só é removido depois de um `ok` do HOP. Tipo desconhecido (versão
    antiga do worker) é mantido, não descartado.
    """
    enviados = 0
    for caminho in pendentes():
        try:
            with open(caminho, encoding="utf-8") as f:
                item = json.load(f)
        except Exception as e:
            print(f"[outbox] ilegivel, mantido para inspecao: {caminho} ({e})",
                  flush=True)
            continue
        envio = rotas.get(item.get("tipo"))
        if envio is None:
            print(f"[outbox] tipo desconhecido {item.get('tipo')!r}, mantido: "
                  f"{os.path.basename(caminho)}", flush=True)
            continue
        try:
            res = await envio(item["payload"])
        except Exception as e:
            print(f"[outbox] reentrega falhou ({e}); fica para a proxima",
                  flush=True)
            continue
        if res.get("ok"):
            os.remove(caminho)
            enviados += 1
            print(f"[outbox] reentregue: {os.path.basename(caminho)}", flush=True)
        else:
            print(f"[outbox] HOP ainda recusa (status={res.get('status_code')}): "
                  f"{os.path.basename(caminho)}", flush=True)
    return enviados
