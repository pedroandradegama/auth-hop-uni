# Agente Híbrido — Costuras A/B/C (Fase F0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the delivered `agente/` LLM-fallback package into the VPS worker so that, when the deterministic Unimed submit hits a well-understood in-portal wall, an LLM loop takes over to diagnose and escalate (never submit) — Fase F0.

**Architecture:** Three seams. **A** — `adapters/unimed_recife/submit.py` raises `FalhaDeterministica` (classified) at three in-portal hard stops instead of returning `erro_submit`. **B** — `worker._processar` catches `FalhaDeterministica`, and if the agent is enabled and the motive is agent-eligible, opens a **fresh** Playwright page (§6.1a decision: the agent re-logins, it does NOT resume the adapter's page), runs `AgenteFallback.executar`, and maps the result back to the existing `submit_result` dict contract. **C** — after the (unchanged) `submit_result` callback, a best-effort second callback posts the `agent_trace` telemetry with the same HMAC.

**Tech Stack:** Python 3.12, Playwright async, `anthropic` SDK (new dep), httpx, pytest.

## Global Constraints

- **F0 = submit desabilitado.** `AGENTE_SUBMETER_HABILITADO=false` no primeiro deploy. O agente diagnostica e escala, nunca submete. (handoff VPS §4.2)
- **`RESULTADO_INCERTO` nunca volta pra fila.** Mapeia para revisão humana. (§4.1)
- **Invariante I3 — conservador:** sem certeza → `requer_captura_manual`/humano, nunca chuta. (handoff Camada3 §7)
- **Invariante I2 — falha explícita**, nunca silenciosa.
- **HMAC inalterado:** assinatura SHA-256 sobre o corpo cru, header `X-HOP-Signature: sha256=<hex>`, via `callback._assinar` / `callback._enviar_para`. Nunca re-serializar após assinar.
- **Telemetria best-effort:** falha no `agent_trace` loga e SEGUE; nunca derruba o circuito principal. (§C)
- **PII já mascarada pelo pruner** no trace; não adicionar DOM cru nem screenshots ao payload `agent_trace`. (§4.3)
- **§6.1a (decisão do Pedro):** page própria fresh — o agente recomeça do login, zero refactor no adapter. `FalhaDeterministica` é um portador de dados (motivo/etapa/detalhe/seletor/url); a page do adapter fecha normalmente.
- **Só Unimed nesta fase.** Sassepe/SulAmérica/Amil não recebem Costura A agora.
- Manter o padrão do repo: getters de env em `config.py` com `_req`/`os.environ.get`; adapters self-contained; worker nunca toca Postgres.

---

## File Structure

- **Create** `agente/` (vendorizar 6 arquivos do pacote entregue, sem alteração) — `tipos.py`, `pruner.py`, `acoes.py`, `orcamento.py`, `loop.py`, `__init__.py`. Raiz do repo, ao lado de `worker.py`, para `from agente import ...` resolver.
- **Modify** `requirements.txt` — adicionar `anthropic`.
- **Modify** `config.py` — helpers `agente_habilitado()`, `agente_submeter_habilitado()`, `_env_bool()`.
- **Modify** `adapters/unimed_recife/submit.py` — Costura A: 3 hard stops in-portal passam a `raise FalhaDeterministica`.
- **Modify** `adapters/unimed_recife/__init__.py` — reexportar `sessao` e expor `DOMINIO`.
- **Modify** `worker.py` — Costura B (catch + agente + mapeamento) e Costura C (segundo callback `agent_trace`).
- **Modify** `callback.py` — helper `enviar_agent_trace()` (mesmo endpoint, mesmo HMAC).
- **Modify** `.env.example` — novas envs do agente.
- **Create** `tests/test_costura_a_falha.py`, `tests/test_costura_b_mapeamento.py`, `tests/test_costura_c_agent_trace.py`.
- **Create** `docs/DEPLOY_F0_AGENTE.md` — checklist de deploy manual.

---

### Task 1: Vendorizar o pacote `agente/` + dependência

**Files:**
- Create: `agente/tipos.py`, `agente/pruner.py`, `agente/acoes.py`, `agente/orcamento.py`, `agente/loop.py`, `agente/__init__.py`
- Modify: `requirements.txt`
- Test: `tests/test_agente_import.py`

**Interfaces:**
- Produces: `from agente import FalhaDeterministica, MotivoFalha, MOTIVOS_AGENTE, ResultadoAgente, ResultadoStatus, AgenteFallback, ContextoSeguranca`

- [ ] **Step 1: Copiar os 6 arquivos do pacote entregue para `agente/` (sem editar)**

```bash
SRC=~/Downloads/handoff-vps-agente-v0.1.0/worker/agente
DST=/Users/pedro/Documents/imag-autorizador/imag-autorizador/agente
mkdir -p "$DST"
cp "$SRC/tipos.py" "$SRC/pruner.py" "$SRC/acoes.py" "$SRC/orcamento.py" "$SRC/loop.py" "$SRC/__init__.py" "$DST/"
ls "$DST"
```
Expected: os 6 arquivos listados.

- [ ] **Step 2: Adicionar `anthropic` ao requirements**

Ler `requirements.txt` e acrescentar a linha `anthropic` (uma por linha, seguindo o formato existente). Não fixar versão salvo se o repo já fixa as demais.

- [ ] **Step 3: Instalar no venv da VPS/local**

```bash
cd /Users/pedro/Documents/imag-autorizador/imag-autorizador
.venv/bin/pip install anthropic
```
Expected: `Successfully installed anthropic-...`

- [ ] **Step 4: Escrever o teste de import (delivery check #1 do handoff §7.1)**

```python
# tests/test_agente_import.py
def test_pacote_agente_importa():
    from agente import (
        FalhaDeterministica, MotivoFalha, MOTIVOS_AGENTE,
        ResultadoAgente, ResultadoStatus, AgenteFallback, ContextoSeguranca,
    )
    assert MotivoFalha.SELETOR_NAO_ACHADO in MOTIVOS_AGENTE
    assert MotivoFalha.WAF_CAPTCHA not in MOTIVOS_AGENTE
```

- [ ] **Step 5: Rodar o teste**

Run: `cd /Users/pedro/Documents/imag-autorizador/imag-autorizador && .venv/bin/python -m pytest tests/test_agente_import.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agente/ requirements.txt tests/test_agente_import.py
git commit -m "feat(agente): vendoriza pacote de fallback LLM v0.1.0 + dep anthropic"
```

---

### Task 2: Helpers de env do agente em `config.py`

**Files:**
- Modify: `config.py`
- Test: `tests/test_config_agente.py`

**Interfaces:**
- Produces: `config.agente_habilitado() -> bool`, `config.agente_submeter_habilitado() -> bool`

- [ ] **Step 1: Escrever o teste (monkeypatch de env)**

```python
# tests/test_config_agente.py
import importlib

def test_agente_flags(monkeypatch):
    import config
    monkeypatch.setenv("AGENTE_HABILITADO", "true")
    monkeypatch.delenv("AGENTE_SUBMETER_HABILITADO", raising=False)
    importlib.reload(config)
    assert config.agente_habilitado() is True
    assert config.agente_submeter_habilitado() is False  # default F0

def test_agente_flags_desligado(monkeypatch):
    import config
    monkeypatch.setenv("AGENTE_HABILITADO", "false")
    importlib.reload(config)
    assert config.agente_habilitado() is False
```

- [ ] **Step 2: Rodar — deve falhar (helpers não existem)**

Run: `.venv/bin/python -m pytest tests/test_config_agente.py -v`
Expected: FAIL com `AttributeError: module 'config' has no attribute 'agente_habilitado'`.

- [ ] **Step 3: Implementar os helpers (fim de `config.py`, após `verificacao_habilitada`)**

```python
# ── Agente híbrido de fallback (Costuras A/B/C) ──────────────────────────
def _env_bool(nome: str, padrao: bool = False) -> bool:
    return os.environ.get(nome, "true" if padrao else "false").lower() == "true"


def agente_habilitado() -> bool:
    """Liga o loop de agente quando o determinístico lança FalhaDeterministica
    com motivo agent-elegível. OFF por padrão."""
    return _env_bool("AGENTE_HABILITADO", False)


def agente_submeter_habilitado() -> bool:
    """F0: False. O agente diagnostica e escala, nunca submete. Só vira True
    após validação do Pedro na vw_rpa_agente_diario (F1)."""
    return _env_bool("AGENTE_SUBMETER_HABILITADO", False)
```

- [ ] **Step 4: Rodar — deve passar**

Run: `.venv/bin/python -m pytest tests/test_config_agente.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config_agente.py
git commit -m "feat(config): flags AGENTE_HABILITADO/AGENTE_SUBMETER_HABILITADO"
```

---

### Task 3: Costura A — Unimed submit lança `FalhaDeterministica`

Converter os TRÊS hard stops **in-portal** de `submit.executar` para `raise FalhaDeterministica` classificado. Os pre-flights em memória (carteirinha inválida, sem códigos) continuam retornando `erro_submit` — são dados ruins do job, não caso de agente. O catch-all genérico também continua retornando `erro_submit` — desconhecido não aciona agente (conservador em F0).

**Files:**
- Modify: `adapters/unimed_recife/submit.py`
- Test: `tests/test_costura_a_falha.py`

**Interfaces:**
- Consumes: `from agente import FalhaDeterministica, MotivoFalha`
- Produces: `submit.executar` pode `raise FalhaDeterministica` com `motivo ∈ {VALIDACAO_PORTAL, SELETOR_NAO_ACHADO}`, carregando `etapa`, `detalhe`, `seletor`, `url`.

**Mapeamento de motivo (handoff §3):**
| hard stop | etapa | motivo |
|---|---|---|
| beneficiário não encontrado (`#emailprestador` timeout pós-buscar) | `buscar_beneficiario` | `VALIDACAO_PORTAL` |
| código não adicionado (`filleprocedimento` timeout/não selecionável) | `adicionar_procedimento` | `SELETOR_NAO_ACHADO` |
| anexo falhou (`#box1`/iframe file input) | `anexar_pedido` | `SELETOR_NAO_ACHADO` |

- [ ] **Step 1: Escrever o teste com page falsa que estoura no beneficiário**

```python
# tests/test_costura_a_falha.py
import contextlib
import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from agente import FalhaDeterministica, MotivoFalha


class _FakeLocator:
    async def click(self, *a, **k): return None
    async def wait_for(self, *a, **k): return None

class _FakeByRole:
    def click(self): return _await_none()

async def _await_none(): return None

class _FakePage:
    """Simula o portal até o 1o hard stop: tudo passa, menos o
    wait_for_selector('#emailprestador'), que estoura como no portal real
    quando a carteirinha não retorna beneficiário."""
    url = "https://autorizador.unimedrecife.com.br/gerar.php"
    def get_by_role(self, *a, **k): return _FakeByRole()
    async def fill(self, *a, **k): return None
    async def click(self, *a, **k): return None
    async def wait_for_load_state(self, *a, **k): return None
    async def wait_for_timeout(self, *a, **k): return None
    async def screenshot(self, *a, **k): return None
    def locator(self, *a, **k): return _FakeLocator()
    async def select_option(self, *a, **k): return None
    async def wait_for_selector(self, seletor, *a, **k):
        if "emailprestador" in seletor:
            raise PlaywrightTimeoutError("emailprestador ausente")
        return None


@pytest.mark.asyncio
async def test_beneficiario_nao_encontrado_lanca_falha(monkeypatch):
    from adapters.unimed_recife import submit, sessao

    @contextlib.asynccontextmanager
    async def _fake_navegador():
        yield _FakePage()

    monkeypatch.setattr(sessao, "navegador", _fake_navegador)
    async def _noop_login(page): return None
    monkeypatch.setattr(sessao, "login", _noop_login)

    job = {
        "carteirinha": "0" * 16, "medico": "DR FULANO",
        "codigos": [{"codigo_tuss": "40901114", "sub_tipo": "RM"}],
        "arquivos": [], "paciente_nome": "PACIENTE X",
    }
    with pytest.raises(FalhaDeterministica) as ei:
        await submit.executar(job)
    falha = ei.value
    assert falha.motivo == MotivoFalha.VALIDACAO_PORTAL
    assert falha.etapa == "buscar_beneficiario"
    assert "autorizador.unimedrecife.com.br" in (falha.url or "")
```

- [ ] **Step 2: Rodar — deve falhar (ainda retorna erro_submit, não levanta)**

Run: `.venv/bin/python -m pytest tests/test_costura_a_falha.py -v`
Expected: FAIL — `DID NOT RAISE FalhaDeterministica` (hoje o hard stop vira `SubmitAbortado` → `erro_submit`).

- [ ] **Step 3: Import no topo de `submit.py`**

Adicionar após os imports existentes (`from . import sessao, varredura`):

```python
from agente import FalhaDeterministica, MotivoFalha
```

- [ ] **Step 4: Hard stop 1 — beneficiário (substituir o bloco atual `raise SubmitAbortado`)**

Localizar (submit.py ~154-161):
```python
            try:
                await page.wait_for_selector('#emailprestador', timeout=8000)
            except PlaywrightTimeoutError:
                await _snap(page, "erro_carteirinha", evidencias)
                raise SubmitAbortado(
                    f"Beneficiario nao encontrado para a carteirinha "
                    f"'{job['carteirinha']}'."
                )
```
Substituir por:
```python
            try:
                await page.wait_for_selector('#emailprestador', timeout=8000)
            except PlaywrightTimeoutError:
                await _snap(page, "erro_carteirinha", evidencias)
                raise FalhaDeterministica(
                    motivo=MotivoFalha.VALIDACAO_PORTAL,
                    etapa="buscar_beneficiario",
                    detalhe=(f"Beneficiario nao encontrado para a carteirinha "
                             f"'{job['carteirinha']}' (ou layout mudou)."),
                    seletor="#emailprestador",
                    url=page.url,
                )
```

- [ ] **Step 5: Hard stop 2 — procedimento (substituir o bloco `if not ok`)**

Localizar (submit.py ~188-193):
```python
                if not ok:
                    await _snap(page, "erro_codigo", evidencias)
                    raise SubmitAbortado(
                        f"Codigo nao adicionado: {erro} "
                        "(gravar abortado para nao gerar guia parcial)."
                    )
```
Substituir por:
```python
                if not ok:
                    await _snap(page, "erro_codigo", evidencias)
                    raise FalhaDeterministica(
                        motivo=MotivoFalha.SELETOR_NAO_ACHADO,
                        etapa="adicionar_procedimento",
                        detalhe=(f"Codigo nao adicionado: {erro} "
                                 "(gravar abortado para nao gerar guia parcial)."),
                        seletor='td[onclick*="filleprocedimento"]',
                        url=page.url,
                    )
```

- [ ] **Step 6: Hard stop 3 — anexo (substituir o bloco `except Exception as e` do anexo)**

Localizar (submit.py ~233-238):
```python
                except Exception as e:
                    await _snap(page, "erro_anexo", evidencias)
                    raise SubmitAbortado(
                        f"Falha ao anexar '{os.path.basename(arquivo)}': {e} "
                        "(gravar abortado para nao gravar sem pedido medico)."
                    )
```
Substituir por:
```python
                except Exception as e:
                    await _snap(page, "erro_anexo", evidencias)
                    raise FalhaDeterministica(
                        motivo=MotivoFalha.SELETOR_NAO_ACHADO,
                        etapa="anexar_pedido",
                        detalhe=(f"Falha ao anexar '{os.path.basename(arquivo)}': {e} "
                                 "(gravar abortado para nao gravar sem pedido medico)."),
                        seletor="#box1",
                        url=page.url,
                    )
```

- [ ] **Step 7: Garantir que `FalhaDeterministica` propaga (não é engolida pelo catch-all)**

O `except Exception as e:` final de `executar` (submit.py ~303) capturaria `FalhaDeterministica`. Adicionar um re-raise explícito ANTES dele. Localizar:
```python
    except SubmitAbortado as e:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": evidencias, "mensagem": str(e)}
    except PlaywrightTimeoutError as e:
```
Inserir entre o `except SubmitAbortado` e o `except PlaywrightTimeoutError`:
```python
    except FalhaDeterministica:
        raise  # Costura A: o runner (worker) decide se aciona o agente.
```

- [ ] **Step 8: Rodar — deve passar**

Run: `.venv/bin/python -m pytest tests/test_costura_a_falha.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add adapters/unimed_recife/submit.py tests/test_costura_a_falha.py
git commit -m "feat(unimed): Costura A — hard stops in-portal lancam FalhaDeterministica"
```

---

### Task 4: Expor `sessao` e `DOMINIO` no adapter Unimed

O runner (Costura B) precisa abrir uma page fresh (§6.1a) via `adapter.sessao.navegador()` + `adapter.sessao.login()`, e do domínio do portal para o `ContextoSeguranca`.

**Files:**
- Modify: `adapters/unimed_recife/__init__.py`
- Test: `tests/test_adapter_exports.py`

**Interfaces:**
- Produces: `adapter.sessao` (módulo), `adapter.DOMINIO -> str` (ex.: `"autorizador.unimedrecife.com.br"`)

- [ ] **Step 1: Escrever o teste**

```python
# tests/test_adapter_exports.py
def test_unimed_expoe_sessao_e_dominio():
    import importlib
    adapter = importlib.import_module("adapters.unimed_recife")
    assert hasattr(adapter, "sessao")
    assert callable(adapter.sessao.navegador)
    assert callable(adapter.sessao.login)
    assert adapter.DOMINIO == "autorizador.unimedrecife.com.br"
```

- [ ] **Step 2: Rodar — deve falhar (`DOMINIO` inexistente)**

Run: `.venv/bin/python -m pytest tests/test_adapter_exports.py -v`
Expected: FAIL com `AttributeError: module 'adapters.unimed_recife' has no attribute 'DOMINIO'`.

- [ ] **Step 3: Editar `adapters/unimed_recife/__init__.py`**

```python
from urllib.parse import urlparse

from . import sessao                      # exposto p/ o runner abrir page fresh
from .submit import executar as submit
from .varredura import coletar
from .verificar import verificar          # async verificar(senha, numero_carteira) -> dict
import config

NOME = "unimed_recife"
DOMINIO = urlparse(config.PORTAL_URL).netloc   # "autorizador.unimedrecife.com.br"
```

- [ ] **Step 4: Rodar — deve passar**

Run: `.venv/bin/python -m pytest tests/test_adapter_exports.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add adapters/unimed_recife/__init__.py tests/test_adapter_exports.py
git commit -m "feat(unimed): expoe sessao + DOMINIO p/ runner do agente"
```

---

### Task 5: Costura B — worker aciona o agente e mapeia o resultado

`worker._processar` passa a envolver `adapter.submit`. Numa `FalhaDeterministica`: se `agente_habilitado()` e `falha.motivo ∈ MOTIVOS_AGENTE`, abre page fresh, roda `AgenteFallback.executar`, e mapeia `ResultadoAgente.status` para o dict `submit_result`. Senão (ou motivo não elegível), retorna `erro_submit` (comportamento atual). Extrai-se o mapeamento em função pura testável.

**Files:**
- Modify: `worker.py`
- Test: `tests/test_costura_b_mapeamento.py`

**Interfaces:**
- Consumes: `config.agente_habilitado`, `config.agente_submeter_habilitado`, `adapter.sessao`, `adapter.DOMINIO`, `from agente import AgenteFallback, MOTIVOS_AGENTE, ContextoSeguranca, FalhaDeterministica, ResultadoAgente, ResultadoStatus`
- Produces: `worker._mapear_resultado_agente(res: ResultadoAgente) -> dict`; `worker._rodar_agente(job, dados, falha, caminhos) -> dict`

- [ ] **Step 1: Escrever o teste do mapeamento (função pura, sem rede)**

```python
# tests/test_costura_b_mapeamento.py
from agente import ResultadoAgente, ResultadoStatus


def _res(status, **kw):
    return ResultadoAgente(status=status, job_id="job-1", **kw)

def test_mapa_concluido():
    import worker
    r = worker._mapear_resultado_agente(_res(ResultadoStatus.CONCLUIDO, protocolo="123"))
    assert r["status"] == "protocolado"
    assert r["numero_protocolo"] == "123"
    assert r.get("requer_captura_manual") is not True

def test_mapa_requer_humano():
    import worker
    r = worker._mapear_resultado_agente(_res(ResultadoStatus.REQUER_HUMANO,
                                             diagnostico="captcha"))
    assert r["status"] == "requer_humano"
    assert r["numero_protocolo"] is None
    assert r["requer_captura_manual"] is True
    assert "captcha" in r["mensagem"]

def test_mapa_resultado_incerto_nunca_reenfileira():
    import worker
    r = worker._mapear_resultado_agente(_res(ResultadoStatus.RESULTADO_INCERTO,
                                             diagnostico="erro pos-submit"))
    assert r["status"] == "requer_humano"
    assert r["requer_captura_manual"] is True
    assert r.get("reenfileirar") is not True
```

- [ ] **Step 2: Rodar — deve falhar (`_mapear_resultado_agente` inexistente)**

Run: `.venv/bin/python -m pytest tests/test_costura_b_mapeamento.py -v`
Expected: FAIL com `AttributeError`.

- [ ] **Step 3: Adicionar imports no topo de `worker.py`**

Após `from schemas import JobPreAutorizacao`:
```python
from agente import (AgenteFallback, MOTIVOS_AGENTE, ContextoSeguranca,
                    FalhaDeterministica, ResultadoAgente, ResultadoStatus)
```

- [ ] **Step 4: Implementar `_mapear_resultado_agente` (função pura, antes de `_processar`)**

```python
def _mapear_resultado_agente(res: "ResultadoAgente") -> dict:
    """Traduz ResultadoAgente -> dict submit_result (contrato inalterado).
    CONCLUIDO -> protocolado; REQUER_HUMANO/RESULTADO_INCERTO -> requer_humano
    com requer_captura_manual (NUNCA re-enfileira; risco de guia dupla)."""
    if res.status == ResultadoStatus.CONCLUIDO:
        return {"status": "protocolado", "numero_protocolo": res.protocolo,
                "evidencias": [],
                "mensagem": res.diagnostico or "Concluido pelo agente."}
    # REQUER_HUMANO e RESULTADO_INCERTO: escala, sem re-fila.
    return {"status": "requer_humano", "numero_protocolo": None,
            "requer_captura_manual": True, "evidencias": [],
            "mensagem": res.diagnostico or "Escalado pelo agente."}
```

- [ ] **Step 5: Implementar `_rodar_agente` (abre page fresh §6.1a, roda o loop)**

Adicionar após `_mapear_resultado_agente`:
```python
async def _rodar_agente(job: JobPreAutorizacao, dados: dict,
                        falha: FalhaDeterministica,
                        caminhos: list[str]) -> tuple[dict, "ResultadoAgente"]:
    """§6.1a: page própria fresh. O agente re-loga e retoma pelo snapshot.
    Retorna (dict submit_result, ResultadoAgente) — o segundo p/ Costura C."""
    adapter = _carregar_adapter(job.convenio)
    job_agente = {
        "job_id": job.job_id, "convenio": job.convenio,
        "carteirinha": job.carteirinha, "cpf": job.cpf,
        "medico": job.medico, "paciente_nome": job.paciente_nome,
        "codigos": dados["codigos"],
        "anexos": [{"nome": os.path.basename(p), "path": p} for p in caminhos],
    }
    ctx = ContextoSeguranca(
        dominio_portal=adapter.DOMINIO,
        anexos_permitidos={os.path.basename(p): p for p in caminhos},
        submeter_habilitado=config.agente_submeter_habilitado(),  # F0: False
    )
    agente = AgenteFallback(
        buscar_guia_existente=None,   # F0: submit off; gate de guia não exercido (Q1 -> F1)
        extrair_protocolo=None,       # F0 (Q2 -> F1)
    )
    async with adapter.sessao.navegador() as page:
        await adapter.sessao.login(page)
        res = await agente.executar(job_agente, page, falha, ctx)
    print(f"[agente] job {job.job_id} -> {res.status.value} "
          f"({res.passos_executados} passos, ${res.custo.custo_usd:.4f})", flush=True)
    return _mapear_resultado_agente(res), res
```

- [ ] **Step 6: Alterar o bloco de submit em `_processar` para capturar `FalhaDeterministica`**

Localizar (worker.py ~97-102):
```python
            try:
                adapter = _carregar_adapter(job.convenio)
                resultado = await adapter.submit(dados)
            except Exception as e:
                resultado = {"status": "erro_submit", "numero_protocolo": None,
                             "evidencias": [], "mensagem": f"Falha no worker: {e}"}
```
Substituir por:
```python
            res_agente = None
            try:
                adapter = _carregar_adapter(job.convenio)
                resultado = await adapter.submit(dados)
            except FalhaDeterministica as falha:
                if config.agente_habilitado() and falha.motivo in MOTIVOS_AGENTE:
                    try:
                        resultado, res_agente = await _rodar_agente(
                            job, dados, falha, caminhos)
                    except Exception as e:
                        import traceback
                        print("[agente-falhou]", traceback.format_exc(), flush=True)
                        resultado = {"status": "requer_humano",
                                     "numero_protocolo": None,
                                     "requer_captura_manual": True, "evidencias": [],
                                     "mensagem": f"Falha determ.: {falha}; "
                                                 f"agente abortou: {e}"}
                else:
                    resultado = {"status": "erro_submit", "numero_protocolo": None,
                                 "evidencias": [],
                                 "mensagem": f"Falha deterministica "
                                             f"({falha.motivo.value}): {falha}"}
            except Exception as e:
                resultado = {"status": "erro_submit", "numero_protocolo": None,
                             "evidencias": [], "mensagem": f"Falha no worker: {e}"}
```

Nota: `res_agente` é consumido na Costura C (Task 6). Deixar declarado agora evita `NameError` quando a Task 6 adicionar o segundo callback.

- [ ] **Step 7: Rodar — mapeamento deve passar**

Run: `.venv/bin/python -m pytest tests/test_costura_b_mapeamento.py -v`
Expected: PASS.

- [ ] **Step 8: Sanidade — worker importa sem erro**

Run: `.venv/bin/python -c "import worker; print('ok')"`
Expected: `ok`.

- [ ] **Step 9: Commit**

```bash
git add worker.py tests/test_costura_b_mapeamento.py
git commit -m "feat(worker): Costura B — aciona agente (page fresh) + mapeia resultado (F0)"
```

---

### Task 6: Costura C — segundo callback `agent_trace` (best-effort)

Após o callback `submit_result` (inalterado), se um `ResultadoAgente` foi produzido, postar `res.para_agent_trace(org_id, convenio)` ao mesmo endpoint `receive-autorizacao`, mesmo HMAC. Falha aqui: loga e SEGUE.

**Files:**
- Modify: `callback.py`, `worker.py`
- Test: `tests/test_costura_c_agent_trace.py`

**Interfaces:**
- Consumes: `ResultadoAgente.para_agent_trace(org_id, convenio) -> dict`, `config.callback_url()`
- Produces: `callback.enviar_agent_trace(payload: dict) -> dict`

- [ ] **Step 1: Escrever o teste (assinatura HMAC sobre o corpo cru do agent_trace)**

Espelha `teste_callback.py`: sobe um HTTP server local, valida a assinatura sobre os bytes recebidos.

```python
# tests/test_costura_c_agent_trace.py
import hashlib, hmac, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest

SEGREDO = "segredo-teste-123"
_capturado = {}

class _H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        corpo = self.rfile.read(n)
        esperado = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
        _capturado["assinatura_ok"] = (self.headers.get("X-HOP-Signature") == esperado)
        _capturado["payload"] = json.loads(corpo)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true,"execucao_id":"exec-1"}')
    def log_message(self, *a): pass


@pytest.mark.asyncio
async def test_agent_trace_assinado(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    porta = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    monkeypatch.setenv("HOP_CALLBACK_SECRET", SEGREDO)
    monkeypatch.setenv("HOP_CALLBACK_URL", f"http://127.0.0.1:{porta}/")
    import importlib, config, callback
    importlib.reload(config); importlib.reload(callback)

    from agente import ResultadoAgente, ResultadoStatus
    res = ResultadoAgente(status=ResultadoStatus.REQUER_HUMANO, job_id="job-1",
                          diagnostico="captcha", motivo_fallback="validacao_portal")
    payload = res.para_agent_trace(org_id="org-1", convenio="unimed_recife")
    resp = await callback.enviar_agent_trace(payload)

    srv.shutdown()
    assert resp["ok"] is True
    assert _capturado["assinatura_ok"] is True
    assert _capturado["payload"]["tipo"] == "agent_trace"
    assert _capturado["payload"]["job_id"] == "job-1"
```

- [ ] **Step 2: Rodar — deve falhar (`enviar_agent_trace` inexistente)**

Run: `.venv/bin/python -m pytest tests/test_costura_c_agent_trace.py -v`
Expected: FAIL com `AttributeError: module 'callback' has no attribute 'enviar_agent_trace'`.

- [ ] **Step 3: Implementar `enviar_agent_trace` em `callback.py`**

Adicionar ao fim de `callback.py`:
```python
async def enviar_agent_trace(payload: dict) -> dict:
    """Telemetria do loop de agente (tipo=agent_trace) p/ receive-autorizacao.
    MESMO endpoint e MESMO HMAC do submit_result. Best-effort: o chamador
    engole exceção (telemetria nunca derruba o circuito principal)."""
    return await _enviar_para(config.callback_url(), payload)
```

- [ ] **Step 4: Rodar — deve passar**

Run: `.venv/bin/python -m pytest tests/test_costura_c_agent_trace.py -v`
Expected: PASS.

- [ ] **Step 5: Emitir o `agent_trace` em `_processar` (após o callback submit_result)**

Localizar em `worker.py` (dentro de `_processar`, após o bloco `try: await callback.enviar(payload) ... except ...`):
```python
        try:
            await callback.enviar(payload)
        except Exception:
            import traceback
            print("[callback-falhou]", traceback.format_exc(), flush=True)
```
Inserir logo depois (ainda dentro do `try` externo de `_processar`, antes do `finally`):
```python
        # Costura C: telemetria do agente (best-effort; nunca derruba o circuito).
        if res_agente is not None:
            try:
                trace = res_agente.para_agent_trace(
                    org_id=job.org_id, convenio=job.convenio)
                await callback.enviar_agent_trace(trace)
            except Exception:
                import traceback
                print("[agent-trace-falhou]", traceback.format_exc(), flush=True)
```

- [ ] **Step 6: Sanidade — worker importa**

Run: `.venv/bin/python -c "import worker; print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: todos PASS.

- [ ] **Step 8: Commit**

```bash
git add callback.py worker.py tests/test_costura_c_agent_trace.py
git commit -m "feat(worker): Costura C — callback agent_trace best-effort (HMAC reuso)"
```

---

### Task 7: Envs, docs e checklist de deploy F0

**Files:**
- Modify: `.env.example`
- Create: `docs/DEPLOY_F0_AGENTE.md`

- [ ] **Step 1: Acrescentar envs ao `.env.example`**

```
# ── Agente híbrido de fallback (F0) ──────────────────────────────────────
ANTHROPIC_API_KEY=                       # key DEDICADA (custo isolado)
AGENTE_HABILITADO=true
AGENTE_SUBMETER_HABILITADO=false         # F0: agente diagnostica/escala, nunca submete
AGENTE_MODELO_EXECUTOR=claude-haiku-4-5
AGENTE_MODELO_VERIFIER=claude-sonnet-4-6
AGENTE_MAX_PASSOS=15
AGENTE_MAX_CUSTO_USD=0.60
```

- [ ] **Step 2: Criar `docs/DEPLOY_F0_AGENTE.md`**

```markdown
# Deploy F0 — Agente Híbrido de Fallback

## Pré-requisitos
- VPS alcança `api.anthropic.com` (HTTPS). Testar: `curl -sS -o /dev/null -w "%{http_code}\n" https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01"` → 200.
- `.env` da VPS com as envs da Task 7 Step 1. `ANTHROPIC_API_KEY` DEDICADA.
- `AGENTE_SUBMETER_HABILITADO=false` (F0). NÃO ligar sem validação do Pedro.

## Passos
1. `git pull` na VPS (`/opt/imag-autorizador`).
2. `venv/bin/pip install -r requirements.txt` (traz `anthropic`).
3. `venv/bin/python -c "from agente import AgenteFallback; print('ok')"` → `ok`.
4. `venv/bin/python -m pytest tests/ -v` → tudo verde.
5. Deixar o cron atual rodar. Na PRIMEIRA falha real agent-elegível do Unimed,
   confirmar no HOP linha em `vw_rpa_agente_diario` com `custo_usd_medio` entre
   $0.05 e $0.35.

## Rollback
- `AGENTE_HABILITADO=false` no `.env` → volta 100% ao determinístico
  (FalhaDeterministica não-elegível vira `erro_submit`, como antes).

## Nota de risco (§6.1a + fluxo Unimed longo)
- A page fresh faz o agente re-navegar todo o fluxo de solicitação. Em Unimed
  (fluxo longo e stateful) isso pode estourar `AGENTE_MAX_PASSOS` antes de
  chegar à falha. Em F0 o desfecho esperado é `REQUER_HUMANO` de qualquer forma,
  então é aceitável — mas é o principal candidato a revisão em F1 (injeção de
  page vs. re-login). Observar `passos` e `custo_usd` na vw diária.
```

- [ ] **Step 3: Commit**

```bash
git add .env.example docs/DEPLOY_F0_AGENTE.md
git commit -m "docs(agente): envs F0 + checklist de deploy e rollback"
```

---

## Notas de escopo (fora desta fase)

- **F1** (`AGENTE_SUBMETER_HABILITADO=true`): decisão do Pedro pós-F0. Aí entram Q1 (`buscar_guia_existente` p/ o gate de guia dupla) e Q2 (`extrair_protocolo` do submit Unimed exposto como função async isolada). Hoje passam `None`.
- **Costura A nos demais adapters** (Sassepe/SulAmérica/Amil): repetir o padrão da Task 3 quando priorizado. Amil permanece `requer_humano` (WAF, não é caso de agente).
- **Camada 3 / verificar** (handoff Camada3, caso 188879979): frente separada; não tocada aqui.

## Self-Review

- **Cobertura do handoff VPS:** Costura A (Task 3), B (Task 5), C (Task 6); tabela de decisão §3 (motivos na Task 3 + gate `MOTIVOS_AGENTE` na Task 5); regras §4 (submeter off via `agente_submeter_habilitado`, RESULTADO_INCERTO→humano no mapeamento, PII no pruner intacto); §5 Q1–Q4 respondidas (Q3 async ok; Q1/Q2 None em F0; Q4 runner real = `worker._processar`); §6.2 envs (Task 7); §6.3 rede (checklist); §7 delivery checks 1–4 (Tasks 1, 3, 6 + deploy). ✅
- **Placeholders:** nenhum "TODO/TBD"; todo passo com código real. ✅
- **Consistência de tipos:** `_mapear_resultado_agente(res)`, `_rodar_agente(...)`, `enviar_agent_trace(payload)`, `ContextoSeguranca(dominio_portal=, anexos_permitidos=, submeter_habilitado=)`, `AgenteFallback(buscar_guia_existente=, extrair_protocolo=)`, `res.para_agent_trace(org_id=, convenio=)` — batem com os arquivos reais lidos (`agente/loop.py`, `agente/acoes.py`, `agente/tipos.py`). ✅
```
