"""
worker.py — Poller do adapter Unimed na VPS (modelo POLL).

Substitui o endpoint inbound /job (modelo PUSH) pelo loop de poll decidido com
o Orquestrador: o worker PUXA o job de `proximo-job-autorizacao`; o HOP nao
empurra, e a porta 8766 fica fechada ao mundo.

Garantias:
  - SEQUENCIAL: um job por vez. So' polla o proximo depois de terminar o atual.
    Isso serializa o browser (um login Unimed) e complementa o CLAIM atomico do
    lado HOP — duas defesas contra gravar duplo.
  - Dedup local por idempotency_key (rede de seguranca; a autoridade e' o CLAIM
    no proximo-job-autorizacao).
  - Anexos por URL assinada, baixados no inicio; falha de download -> erro_submit.
  - Resultado sempre via callback HMAC (callback.py). O worker nunca toca Postgres.
  - Shutdown gracioso (SIGTERM/SIGINT) para o PM2 reiniciar limpo.

Deploy: PM2 em /opt/imag-autorizador/, processo longo (como o imag-agent).
"""
import os
import signal
import asyncio
import shutil
from datetime import datetime

import httpx

import config
import callback
from schemas import JobPreAutorizacao
from portal import submit

_parar = asyncio.Event()
_jobs_vistos: set[str] = set()  # dedup local (rede de seguranca)


def _nome_seguro(nome: str, i: int) -> str:
    nome = (nome or f"anexo_{i}.bin").replace(" ", "_")
    nome = "".join(c for c in nome if c.isalnum() or c in "._-")
    if "." in nome:
        base, ext = nome.rsplit(".", 1)
        nome = base[:50] + "." + ext[:8]
    return nome or f"anexo_{i}.bin"


async def _baixar_anexos(anexos, pasta: str) -> list[str]:
    """Baixa as URLs assinadas. Levanta excecao em falha — o chamador converte
    em erro_submit (pre-auth sem pedido medico nao segue)."""
    caminhos = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for i, ax in enumerate(anexos):
            r = await client.get(ax.url)
            r.raise_for_status()
            destino = os.path.join(pasta, _nome_seguro(ax.nome, i))
            with open(destino, "wb") as f:
                f.write(r.content)
            caminhos.append(destino)
    return caminhos


async def _processar(job: JobPreAutorizacao):
    """Baixa anexos, executa o submit, posta o callback, limpa."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pasta = os.path.join(config.UPLOADS_DIR, f"{ts}_{job.job_id[:8]}")
    os.makedirs(pasta, exist_ok=True)
    try:
        try:
            caminhos = await _baixar_anexos(job.anexos, pasta)
        except Exception as e:
            resultado = {"status": "erro_submit", "numero_protocolo": None,
                         "evidencias": [], "mensagem": f"Falha ao baixar anexo: {e}"}
        else:
            dados = {
                "carteirinha": job.carteirinha,
                "medico": job.medico,
                "paciente_nome": job.paciente_nome,
                "codigos": [c.model_dump() for c in job.codigos],
                "arquivos": caminhos,
            }
            try:
                resultado = await submit.executar(dados)
            except Exception as e:
                resultado = {"status": "erro_submit", "numero_protocolo": None,
                             "evidencias": [], "mensagem": f"Falha no worker: {e}"}

        payload = {
            "tipo": "submit_result",
            "job_id": job.job_id,
            "idempotency_key": job.idempotency_key,
            "org_id": job.org_id,
            "convenio": job.convenio,
            **resultado,
        }
        try:
            await callback.enviar(payload)
        except Exception:
            import traceback
            print("[callback-falhou]", traceback.format_exc(), flush=True)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


async def _pollar_uma_vez(client: httpx.AsyncClient) -> bool:
    """Consulta proximo-job-autorizacao. Processa se houver job.
    Retorna True se processou um job, False se nao havia (204)."""
    headers = {"Authorization": f"Bearer {config.worker_inbound_secret()}"}
    r = await client.get(config.proximo_job_url(), headers=headers)
    if r.status_code == 204:
        return False
    r.raise_for_status()

    job = JobPreAutorizacao(**r.json())  # 422 logico aqui = job malformado do HOP
    if job.idempotency_key in _jobs_vistos:
        print(f"[poll] job {job.job_id} ja' visto; ignorado.", flush=True)
        return True
    _jobs_vistos.add(job.idempotency_key)

    print(f"[poll] processando job {job.job_id} "
          f"({len(job.codigos)} exame(s))", flush=True)
    await _processar(job)
    return True


async def loop():
    print(">> poller imag-autorizador iniciado (daemon)", flush=True)
    async with httpx.AsyncClient(timeout=30) as client:
        while not _parar.is_set():
            try:
                teve = await _pollar_uma_vez(client)
                intervalo = (config.POLL_INTERVAL_SEG if teve
                             else config.POLL_INTERVAL_OCIOSO_SEG)
            except Exception as e:
                print(f"[poll] erro: {e}", flush=True)
                intervalo = config.POLL_INTERVAL_OCIOSO_SEG
            try:
                await asyncio.wait_for(_parar.wait(), timeout=intervalo)
            except asyncio.TimeoutError:
                pass
    print(">> poller encerrado.", flush=True)


async def drenar(max_jobs: int = 50):
    """Modo CRON: acorda, processa todos os jobs da fila ate' 204 (vazia), e
    encerra. Sem daemon, sem estado entre execucoes — cada rodada comeca limpa.
    `max_jobs` e' um teto de seguranca contra loop acidental."""
    print(">> drenar imag-autorizador iniciado (cron)", flush=True)
    processados = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while processados < max_jobs:
            try:
                teve = await _pollar_uma_vez(client)
            except Exception as e:
                print(f"[poll] erro: {e}", flush=True)
                break
            if not teve:
                break  # fila vazia (204) -> encerra
            processados += 1
    print(f">> drenar encerrado. {processados} job(s) processado(s).", flush=True)


def _instalar_sinais(laco):
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            laco.add_signal_handler(sig, _parar.set)
        except NotImplementedError:
            pass  # ambientes sem suporte (ex.: Windows)


def main():
    os.makedirs(config.UPLOADS_DIR, exist_ok=True)
    # Modo padrao = cron (drenar). Use MODO=daemon para o loop continuo.
    modo = os.environ.get("MODO", "cron").lower()
    laco = asyncio.new_event_loop()
    asyncio.set_event_loop(laco)
    _instalar_sinais(laco)
    try:
        if modo == "daemon":
            laco.run_until_complete(loop())
        else:
            laco.run_until_complete(drenar())
    finally:
        laco.close()


if __name__ == "__main__":
    main()
