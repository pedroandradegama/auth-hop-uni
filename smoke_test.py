"""
smoke_test.py — Validacao local objetiva, SEM portal e SEM credenciais.

Testa so' o que da' para testar offline: imports, logica de carteirinha,
mapa de sub-tipos e o /health do worker. NAO abre browser, NAO loga no portal.

Uso:
    source .venv/bin/activate
    python smoke_test.py
"""
import sys

falhas = []


def checa(nome, fn):
    try:
        fn()
        print(f"  [PASSOU] {nome}")
    except Exception as e:
        print(f"  [FALHOU] {nome}: {e}")
        falhas.append(nome)


print("== imag-autorizador · smoke test ==\n")

# 1. Imports resolvem
def _imports():
    import config, callback, worker            # noqa: F401
    from portal import sessao, submit, varredura  # noqa: F401
checa("imports dos modulos", _imports)

# 2. Config tem os valores de portal esperados
def _config():
    import config
    assert config.SUBTIPO_VALUE == {"RM": "169", "TC": "170"}
    assert config.ESPECIALIDADE_VALUE == "125"
    assert config.VARREDURA_JANELA_DIAS >= 1
    assert config.BROWSER_ENGINE == "firefox"
checa("valores de portal no config", _config)

# 3. Carteirinha — casos validos
def _carteirinha_ok():
    from portal.submit import split_carteirinha
    # 16 digitos
    assert split_carteirinha("0034331000065409") == ("003", "433100006540", "9")
    # com espacos e mascara
    a, b, c = split_carteirinha("0034 331000065409")
    assert (a, b, c) == ("003", "433100006540", "9")
    # 17 digitos -> descarta o primeiro
    assert split_carteirinha("90034331000065409")[0] == "003"
checa("split de carteirinha (validos)", _carteirinha_ok)

# 4. Carteirinha — hard stop em invalida
def _carteirinha_curta():
    from portal.submit import split_carteirinha, SubmitAbortado
    try:
        split_carteirinha("123")
    except SubmitAbortado:
        return
    raise AssertionError("deveria ter abortado em carteirinha curta")
checa("hard stop carteirinha curta", _carteirinha_curta)

# 5. Sub-tipo desconhecido nao quebra silenciosamente
def _subtipo():
    import config
    assert config.SUBTIPO_VALUE.get("XX") is None
checa("sub-tipo desconhecido retorna None", _subtipo)

# 6. Normalizacao de status da varredura (rotulos REAIS do portal)
def _status():
    from portal.varredura import _normalizar_status
    assert _normalizar_status("Autorizado") == "AUTORIZADO"
    assert _normalizar_status("Solicitado") == "EM_ANALISE"
    assert _normalizar_status("Auditoria Administrativa") == "EM_ANALISE"
    assert _normalizar_status("Orientação ao Cliente / Prestador") == "EM_ANALISE"
    assert _normalizar_status("Negado") == "NEGADO"
    assert _normalizar_status("coisa estranha") == "DESCONHECIDO"
checa("normalizacao de status do portal (rotulos reais)", _status)

# 6b. Casamento de nome (truncamento da lista + prefixo numerico + acento)
def _match_nome():
    from portal.varredura import _normalizar_nome, _nomes_casam
    # prefixo "865 - " e acento removidos
    assert _normalizar_nome("865 - SIMONE VENCESLAU DO NASC") == "SIMONE VENCESLAU DO NASC"
    assert _normalizar_nome("994 - GLEYBSON CÉSAR DA SILVA") == "GLEYBSON CESAR DA SILVA"
    real = _normalizar_nome("SIMONE VENCESLAU DO NASCIMENTO")
    lista = _normalizar_nome("865 - SIMONE VENCESLAU DO NASC")   # truncado
    assert _nomes_casam(real, lista) is True            # truncado casa por prefixo
    # nomes diferentes nao casam
    assert _nomes_casam(_normalizar_nome("JOAO DA SILVA"),
                        _normalizar_nome("034 - MARIA DE FATIMA")) is False
    # nome curto demais nao casa (evita falso positivo)
    assert _nomes_casam("ANA", "ANA") is False
checa("casamento de nome (lista truncada, prefixo, acento)", _match_nome)

# 7. Credenciais sem default — getter falha alto se faltar env
def _creds_sem_default():
    import importlib, os, config
    for v in ("UNIMED_USER", "UNIMED_PASS"):
        os.environ.pop(v, None)
    importlib.reload(config)
    try:
        config.unimed_user()
    except RuntimeError:
        return
    raise AssertionError("unimed_user deveria falhar sem env")
checa("credenciais sem default embutido", _creds_sem_default)

# 8. Poll: worker puxa job, manda Bearer, processa 200, dorme em 204, dedup
def _poll():
    import os, asyncio, httpx, worker
    os.environ["WORKER_INBOUND_SECRET"] = "teste"
    os.environ["HOP_PROXIMO_JOB_URL"] = "https://hop.local/proximo-job-autorizacao"

    job = {
        "job_id": "sessao-123", "idempotency_key": "sessao-123", "org_id": "o1",
        "carteirinha": "0034331000065409", "medico": "DR FULANO",
        "codigos": [{"codigo_tuss": "41101219", "sub_tipo": "RM"}],
        "anexos": [{"url": "https://x/y.jpg"}],
    }
    processados = []
    async def _fake_proc(j):
        processados.append(j.job_id)
    worker._processar = _fake_proc
    worker._jobs_vistos.clear()

    estado = {"n": 0}
    def handler(request):
        assert request.method == "POST", f"poll deve ser POST, veio {request.method}"
        assert request.headers.get("Authorization") == "Bearer teste", "Bearer ausente"
        estado["n"] += 1
        if estado["n"] == 1:
            return httpx.Response(200, json=job)      # 1a vez: entrega job
        if estado["n"] == 2:
            return httpx.Response(200, json=job)      # 2a: MESMO job (testa dedup)
        return httpx.Response(204)                    # 3a: sem job

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as c:
            t1 = await worker._pollar_uma_vez(c)  # processa
            t2 = await worker._pollar_uma_vez(c)  # mesmo job -> dedup, nao reprocessa
            t3 = await worker._pollar_uma_vez(c)  # 204
        return t1, t2, t3

    t1, t2, t3 = asyncio.run(run())
    assert t1 is True and t2 is True and t3 is False
    assert processados == ["sessao-123"], f"dedup falhou: {processados}"
checa("poll: puxa job, Bearer, processa, dedup, 204", _poll)

# 8b. Drenar (modo cron): processa ate' 204 e encerra
def _drenar():
    import os, asyncio, httpx, worker
    os.environ["WORKER_INBOUND_SECRET"] = "teste"
    os.environ["HOP_PROXIMO_JOB_URL"] = "https://hop.local/proximo-job-autorizacao"
    job = {
        "job_id": "s1", "idempotency_key": "s1", "org_id": "o1",
        "carteirinha": "0034331000065409", "medico": "DR FULANO",
        "codigos": [{"codigo_tuss": "41101219", "sub_tipo": "RM"}],
        "anexos": [{"url": "https://x/y.jpg"}],
    }
    job2 = dict(job, job_id="s2", idempotency_key="s2")
    processados = []
    async def _fake_proc(j):
        processados.append(j.job_id)
    worker._processar = _fake_proc
    worker._jobs_vistos.clear()

    estado = {"n": 0}
    def handler(request):
        estado["n"] += 1
        if estado["n"] == 1:
            return httpx.Response(200, json=job)
        if estado["n"] == 2:
            return httpx.Response(200, json=job2)
        return httpx.Response(204)   # fila vazia -> drenar encerra
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as c:
            # injeta o client no _pollar_uma_vez via drenar nao da' (drenar cria o seu);
            # entao exercitamos a logica chamando _pollar_uma_vez em sequencia.
            n = 0
            while n < 10:
                if not await worker._pollar_uma_vez(c):
                    break
                n += 1
            return n
    n = asyncio.run(run())
    assert n == 2, f"esperava drenar 2 jobs, drenou {n}"
    assert processados == ["s1", "s2"]
checa("drenar (cron): processa fila ate' 204", _drenar)

# 9. Schema do job — payload valido passa, invalido falha
def _schema():
    from schemas import JobPreAutorizacao
    from pydantic import ValidationError
    valido = {
        "job_id": "j1", "idempotency_key": "k1", "org_id": "o1",
        "carteirinha": "0034331000065409", "medico": "DR FULANO",
        "codigos": [{"codigo_tuss": "41101219", "sub_tipo": "rm"}],
        "anexos": [{"url": "https://x/y.jpg", "nome": "pedido.jpg"}],
    }
    j = JobPreAutorizacao(**valido)
    assert j.codigos[0].sub_tipo == "RM"  # normalizado pra maiuscula
    # sub_tipo invalido
    for campo, mut in [
        ("sub_tipo", lambda d: d["codigos"][0].update(sub_tipo="XX")),
        ("anexos", lambda d: d.update(anexos=[])),
        ("codigos", lambda d: d.update(codigos=[])),
        ("carteirinha", lambda d: d.update(carteirinha="123")),
    ]:
        import copy
        ruim = copy.deepcopy(valido)
        mut(ruim)
        try:
            JobPreAutorizacao(**ruim)
        except ValidationError:
            continue
        raise AssertionError(f"deveria rejeitar {campo} invalido")
checa("schema do job (valido passa, invalido falha)", _schema)

print()
if falhas:
    print(f"RESULTADO: {len(falhas)} falha(s) -> {falhas}")
    sys.exit(1)
print("RESULTADO: tudo passou. Login, varredura e captura de protocolo via lista")
print("validados no portal real. Resta a senha (drill-down em AUTORIZADO) e o")
print("lado HOP (Edge Functions + RPCs).")
