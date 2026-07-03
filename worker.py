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
import importlib

# Registro EXPLICITO convenio -> modulo do adapter (lista branca; nao importar
# string crua vinda do HOP). Adicionar uma linha por convenio novo.
_ADAPTERS = {
    "unimed_recife": "adapters.unimed_recife",
    "amil": "adapters.amil",
    "sassepe": "adapters.sassepe",
    "sulamerica": "adapters.sulamerica",
}


def _carregar_adapter(convenio: str):
    nome_mod = _ADAPTERS.get(convenio)
    if not nome_mod:
        raise ValueError(f"convenio sem adapter registrado: {convenio!r}")
    return importlib.import_module(nome_mod)

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
                "cpf": job.cpf,
                "medico": job.medico,
                "paciente_nome": job.paciente_nome,
                "codigos": [c.model_dump() for c in job.codigos],
                "arquivos": caminhos,
            }
            try:
                adapter = _carregar_adapter(job.convenio)
                resultado = await adapter.submit(dados)
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
    """Consulta proximo-job-autorizacao (POST com corpo {}). Processa se houver
    job. Retorna True se processou um job, False se nao havia (204).
    O 204 e' tratado ANTES de qualquer .json() (corpo vazio nao se parseia)."""
    headers = {"Authorization": f"Bearer {config.worker_inbound_secret()}"}
    # POST com corpo {}: 'pegar o proximo job' tem efeito colateral (claim
    # atomico no HOP) — POST e' o verbo correto. {} mantem corpo+header coerentes
    # e deixa o lugar pronto para {"org_id": ...} no futuro multi-tenant.
    r = await client.post(config.proximo_job_url(), headers=headers, json={})
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


# ── Verificação de senha (Camada 3 do gate) ─────────────────────────────────
def _adapter_por_nome_convenio(nome: str):
    """O job de verificação traz `convenio: {id, nome, registro_ans}` (não o
    slug). Mapeia o NOME para um adapter registrado. None se não reconhecer.
    Normaliza acento ('Sul América' -> 'sul america')."""
    import unicodedata
    n = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    if "unimed" in n:
        slug = "unimed_recife"
    elif "sassepe" in n:
        slug = "sassepe"
    elif "sul" in n and "amer" in n:
        slug = "sulamerica"
    elif "amil" in n:
        slug = "amil"
    else:
        return None
    return _carregar_adapter(slug)


def _erro_verif(classe: str, detalhe: str) -> dict:
    """Resultado de erro no formato do contrato (status_portal='erro')."""
    return {"status_portal": "erro", "classe_erro": classe, "validade": None,
            "qtd_autorizada": None, "evidencia_b64": None, "detalhe": detalhe[:400]}


async def _pollar_verificacao_uma_vez(client: httpx.AsyncClient) -> bool:
    """Consulta proximo-job-verificacao (POST {}). Executa adapter.verificar e
    posta o resultado em receive-verificacao. Retorna True se processou, False
    se 204. Toda exceção do worker vira erro/transitorio (conservador: na dúvida
    o HOP re-tenta em vez de suspender o convênio)."""
    headers = {"Authorization": f"Bearer {config.worker_inbound_secret()}"}
    r = await client.post(config.proximo_job_verificacao_url(), headers=headers, json={})
    if r.status_code == 204:
        return False
    r.raise_for_status()
    job = r.json()

    job_id = job.get("job_id")
    senha = job.get("senha")
    carteira = job.get("numero_carteira")
    conv = job.get("convenio") or {}
    print(f"[verif {job_id}] senha={senha} convenio={conv.get('nome')!r}", flush=True)

    try:
        adapter = _adapter_por_nome_convenio(conv.get("nome", ""))
        if adapter is None or not hasattr(adapter, "verificar"):
            resultado = _erro_verif(
                "estrutural",
                f"verbo 'verificar' indisponivel p/ convenio {conv.get('nome')!r}")
        else:
            # Backstop: o adapter tem timeout interno de 90s; 100s aqui é a rede
            # de segurança do worker.
            resultado = await asyncio.wait_for(
                adapter.verificar(senha, carteira), timeout=100)
    except asyncio.TimeoutError:
        resultado = _erro_verif("transitorio", f"timeout no worker (job {job_id})")
    except Exception as e:
        import traceback
        print(f"[verif {job_id}] erro: {traceback.format_exc()}", flush=True)
        resultado = _erro_verif("transitorio", f"falha no worker: {e}")

    payload = {"job_id": job_id, "resultado": resultado}
    try:
        await callback.enviar_verificacao(payload)
    except Exception:
        import traceback
        print(f"[verif {job_id}] callback-falhou: {traceback.format_exc()}", flush=True)
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


async def _drenar_fila(client, pollar, lote: int, restante: int) -> int:
    """Drena ate' `lote` itens de UMA fila (ou ate' 204/erro/`restante`).
    Retorna quantos processou nesta rodada."""
    n = 0
    while n < lote and n < restante:
        try:
            if not await pollar(client):
                break  # 204 -> fila vazia
        except Exception as e:
            print(f"[poll] erro: {e}", flush=True)
            break
        n += 1
    return n


async def drenar(max_jobs: int = 50):
    """Modo CRON: acorda, intercala SUBMITS e VERIFICACOES ate' esvaziar as filas
    (ou o teto `max_jobs`), e encerra. Sem daemon, sem estado entre execucoes.
    A verificacao so' roda se VERIFICACAO_HABILITADA=true (senao jobs reais
    virariam erro/estrutural e disparariam o circuit breaker do HOP)."""
    print(">> drenar imag-autorizador iniciado (cron)", flush=True)
    verif_on = config.verificacao_habilitada()
    lote = config.VERIFICACAO_LOTE
    total_s = total_v = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while total_s + total_v < max_jobs:
            restante = max_jobs - (total_s + total_v)
            fez_s = await _drenar_fila(client, _pollar_uma_vez, lote, restante)
            total_s += fez_s
            fez_v = 0
            if verif_on:
                restante = max_jobs - (total_s + total_v)
                fez_v = await _drenar_fila(
                    client, _pollar_verificacao_uma_vez, lote, restante)
                total_v += fez_v
            if fez_s == 0 and fez_v == 0:
                break  # ambas as filas vazias
    print(f">> drenar encerrado. {total_s} submit(s), {total_v} verificacao(oes).",
          flush=True)


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
