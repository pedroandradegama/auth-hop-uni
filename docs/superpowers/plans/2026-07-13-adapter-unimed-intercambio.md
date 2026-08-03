# Adapter Unimed Intercâmbio (CONNECTA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portar o `bot_connecta.py` (validado ao vivo 14/07/2026) para um adapter `adapters/unimed_intercambio/` no molde da esteira, plugado ao contrato poll+callback HMAC, para autorizar guias de **intercâmbio** no portal Unimed **CONNECTA** (ASP.NET WebForms, `remote.unimedrecife.com.br:444/connecta`).

**Architecture:** Adapter self-contained (`config`/`sessao`/`submit`/`codigos`/`__init__`), engine **chromium + headless=False + Xvfb** (via `pyvirtualdisplay` no Linux — CONNECTA esconde o form em headless puro). `submit(dados) -> submit_result` como os demais. Fluxo do bot preservado **verbatim** nos helpers de portal; adaptam-se só as bordas (config, split sessao/submit, contrato de saída, mapeamento do recibo). Costura A (FalhaDeterministica → agente) fica como **fase 2**, após validação ao vivo do caminho determinístico.

**Tech Stack:** Python 3.12, Playwright async (chromium), pyvirtualdisplay+Xvfb (Linux), pytest.

## Global Constraints

- **Portal exige chromium + headless=False + Xvfb.** Não usar firefox/headless puro (CONNECTA esconde o formulário). Xvfb e xvfb-run confirmados na VPS; chromium do Playwright confirmado (`/root/.cache/ms-playwright/chromium-1223/...`).
- **Intercâmbio NÃO envia anexo.** `anexos` deixa de ser obrigatório para `convenio="unimed_intercambio"`.
- **CRM é obrigatório no job** (campo dedicado `crm`). O adapter aborta se ausente.
- **Beneficiário de Trânsito → responder "Sim"** automaticamente (a autorização É o teste de validação do paciente de intercâmbio).
- **Exames já realizados (exige justificativa) → `requer_humano` (HITL)**, nunca justificar sozinho.
- **Protocolo canônico** = `numero_protocolo` ← "Número Guia Operadora"; devolver também `numero_autorizacao` + `validade` no resultado (confirmar nos testes ao vivo).
- **Código** = modelo idêntico ao `unimed_recife`: job carrega `codigo_tuss`, `resolver_codigo_portal` = identidade, CSV de catálogo próprio.
- **I1/I2/I3** herdadas: hard stop antes do envio; falha explícita; protocolo conservador (sem status "autorizado" seguro → `pendente`/`requer_humano`, nunca inventa).
- **Roteamento (HOP-side, fora deste plano):** HOP decide por prefixo de carteirinha → seta `convenio="unimed_intercambio"`. Este plano só consome o slug.
- Manter padrão do repo: getters de env com `_req`; adapters self-contained; worker nunca toca Postgres.

---

## File Structure

- **Create** `adapters/unimed_intercambio/__init__.py` — expõe `submit`, `sessao`, `DOMINIO`, `NOME`.
- **Create** `adapters/unimed_intercambio/config.py` — URLs, creds `UNIMED_CONECTA_*`, regras fixas, engine.
- **Create** `adapters/unimed_intercambio/sessao.py` — Xvfb + chromium + login + seleção de contexto.
- **Create** `adapters/unimed_intercambio/submit.py` — helpers de portal (port verbatim) + `executar(job)` (contrato).
- **Create** `adapters/unimed_intercambio/codigos.py` — resolver identidade (molde `codigos.py` raiz).
- **Create** `adapters/unimed_intercambio/codigos_unimed_intercambio.csv` — catálogo inicial.
- **Modify** `schemas.py` — campo `crm`; `quantidade` no `ExameItem`; `anexos` condicional; `CONVENIOS_SEM_ANEXO`.
- **Modify** `worker.py` — registrar `unimed_intercambio` em `_ADAPTERS`; passar `crm`/`quantidade` no `dados`.
- **Modify** `requirements.txt` — `pyvirtualdisplay`.
- **Modify** `.env.example` — `UNIMED_CONECTA_USER/PASS`, `CONTEXTO_PRESTADOR`.
- **Create** `tests/test_schema_intercambio.py`, `tests/test_intercambio_codigos.py`, `tests/test_intercambio_mapeamento.py`, `tests/test_intercambio_exports.py`.
- **Create** `docs/DEPLOY_UNIMED_INTERCAMBIO.md`.

Fonte de verdade dos helpers de portal: `~/Downloads/bot_connecta.py` (validado). Copiar **sem alterar a mecânica**; só ajustar imports/config.

---

### Task 1: Schema — `crm`, `quantidade`, `anexos` condicional

**Files:**
- Modify: `schemas.py`
- Test: `tests/test_schema_intercambio.py`

**Interfaces:**
- Produces: `JobPreAutorizacao` aceita `crm: str | None`; `ExameItem.quantidade: int = 1`; `anexos` opcional p/ `convenio ∈ CONVENIOS_SEM_ANEXO = {"unimed_intercambio"}`.

- [ ] **Step 1: Escrever os testes**

```python
# tests/test_schema_intercambio.py
import pytest
from schemas import JobPreAutorizacao


def _base(**kw):
    d = dict(job_id="j1", idempotency_key="k1", org_id="o1",
             convenio="unimed_intercambio", carteirinha="08650002578827002",
             medico="PEDRO ANDRADE GAMA", crm="21798",
             codigos=[{"codigo_tuss": "40901122", "quantidade": 2}])
    d.update(kw)
    return d


def test_intercambio_sem_anexo_e_valido():
    job = JobPreAutorizacao(**_base())
    assert job.crm == "21798"
    assert job.codigos[0].quantidade == 2
    assert job.anexos == []


def test_intercambio_dispensa_subtipo():
    # CONNECTA nao usa RM/TC (campo Tipo fixo). Nao deve exigir sub_tipo.
    job = JobPreAutorizacao(**_base())
    assert job.codigos[0].sub_tipo is None


def test_unimed_recife_ainda_exige_anexo():
    with pytest.raises(Exception):
        JobPreAutorizacao(job_id="j", idempotency_key="k", org_id="o",
                          convenio="unimed_recife", carteirinha="08650002578827002",
                          medico="X", codigos=[{"codigo_tuss": "41101219", "sub_tipo": "RM"}])
        # sem anexos -> deve falhar p/ unimed_recife
```

- [ ] **Step 2: Rodar — falha (schema atual exige anexos e não tem crm/quantidade)**

Run: `.venv/bin/python -m pytest tests/test_schema_intercambio.py -q`
Expected: FAIL (`crm`/`quantidade` inexistentes; `anexos` obrigatório).

- [ ] **Step 3: Adicionar `quantidade` ao `ExameItem`**

Em `schemas.py`, na classe `ExameItem`, após `nome: str | None = None`:
```python
    quantidade: int = 1
```

- [ ] **Step 4: Adicionar `CONVENIOS_SEM_ANEXO` + campo `crm`**

Após a linha `CONVENIOS_SEM_SUBTIPO = {"sassepe", "sulamerica"}` acrescentar:
```python
# Convenios cujo fluxo NAO envia anexo (pedido medico). Ex.: Unimed Intercambio
# (CONNECTA) — o portal autoriza sem upload. Para esses, anexos e' opcional.
CONVENIOS_SEM_ANEXO = {"unimed_intercambio"}
```
Na classe `JobPreAutorizacao`, após `medico: str`:
```python
    crm: str | None = None  # numero do conselho; exigido pelos adapters que usam
```

- [ ] **Step 5: Tornar `anexos` condicional**

Trocar o campo `anexos` (hoje `Field(min_length=1, ...)`) por:
```python
    anexos: list[AnexoItem] = Field(
        default_factory=list,
        description="Pedido medico. Obrigatorio salvo convenios em CONVENIOS_SEM_ANEXO.",
    )
```
E adicionar um `model_validator(mode="after")` após `_subtipo_por_convenio`:
```python
    @model_validator(mode="after")
    def _anexo_por_convenio(self):
        if self.convenio not in CONVENIOS_SEM_ANEXO and len(self.anexos) < 1:
            raise ValueError(
                f"convenio '{self.convenio}' exige ao menos 1 anexo (pedido medico)")
        return self
```

- [ ] **Step 6: Adicionar `unimed_intercambio` a `CONVENIOS_SEM_SUBTIPO`**

Trocar:
```python
CONVENIOS_SEM_SUBTIPO = {"sassepe", "sulamerica"}
```
Por:
```python
CONVENIOS_SEM_SUBTIPO = {"sassepe", "sulamerica", "unimed_intercambio"}
```

- [ ] **Step 7: Rodar — passa; suíte inteira verde**

Run: `.venv/bin/python -m pytest tests/test_schema_intercambio.py tests/ -q`
Expected: PASS (novos + todos os anteriores).

- [ ] **Step 8: Commit**

```bash
git add schemas.py tests/test_schema_intercambio.py
git commit -m "feat(schema): crm + quantidade + anexos condicional (unimed_intercambio)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Config + Códigos do adapter

**Files:**
- Create: `adapters/unimed_intercambio/config.py`, `codigos.py`, `codigos_unimed_intercambio.csv`
- Test: `tests/test_intercambio_codigos.py`

**Interfaces:**
- Produces: `config.PORTAL_URL`, `config.URL_SOLICITACAO`, `config.unimed_conecta_user/pass()`, `config.contexto_prestador()`, regras fixas, `config.BROWSER_ENGINE="chromium"`, `config.DOMINIO`; `codigos.resolver_codigo_portal(tuss) -> str` (identidade).

- [ ] **Step 1: Criar `adapters/unimed_intercambio/config.py`**

```python
"""config.py — Adapter Unimed Intercambio (portal CONNECTA)."""
import os
from urllib.parse import urlparse

import config as _raiz  # reusa SCREENSHOTS_DIR/BASE_DIR globais


def _req(nome: str) -> str:
    v = os.environ.get(nome)
    if not v:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {nome}.")
    return v


PORTAL_URL = os.environ.get(
    "UNIMED_CONECTA_URL",
    "https://remote.unimedrecife.com.br:444/connecta/Default.aspx",
)
URL_SOLICITACAO = os.environ.get(
    "UNIMED_CONECTA_URL_SOLICITACAO",
    "https://remote.unimedrecife.com.br:444/connecta/Content/TISS/Prestador/GuiaSolicitacaoSPSADT.aspx",
)


def unimed_conecta_user() -> str:
    return _req("UNIMED_CONECTA_USER")


def unimed_conecta_pass() -> str:
    return _req("UNIMED_CONECTA_PASS")


def contexto_prestador() -> str:
    return os.environ.get("CONTEXTO_PRESTADOR", "Imag Diagnostico Por Imagem Ltda")


# Regras de negocio fixas (validadas 14/07/2026 no bot_connecta.py)
CONSELHO_PROFISSIONAL_FIXO = "CRM"
UF_CONSELHO_FIXO = "PE"
CODIGO_CBO_FIXO = "225125 - Médico clínico"
CARATER_ATENDIMENTO_FIXO = "1-Eletiva"
TIPO_ITEM_FIXO = "Procedimento"
CODIGO_PRESTADOR_FIXO = "99999999999999"

BROWSER_ENGINE = "chromium"          # CONNECTA esconde form em headless puro
BROWSER_HEADLESS = False             # roda sob Xvfb no Linux (ver sessao.py)
DOMINIO = urlparse(PORTAL_URL).netloc  # "remote.unimedrecife.com.br:444"
SCREENSHOTS_DIR = _raiz.SCREENSHOTS_DIR
```

- [ ] **Step 2: Criar `codigos_unimed_intercambio.csv` (catálogo inicial, molde do unimed_recife)**

```
codigo,nome
40901122,EXEMPLO - AJUSTAR NO PRIMEIRO USO
```
(O catálogo é validação leve; a resolução é identidade. Ampliar conforme os exames reais de intercâmbio.)

- [ ] **Step 3: Criar `adapters/unimed_intercambio/codigos.py` (molde do `codigos.py` raiz, identidade)**

```python
"""codigos.py — Resolucao de codigo p/ o CONNECTA. Identidade (o portal aceita
o proprio TUSS no autocomplete), igual ao unimed_recife. CSV = validacao leve."""
import csv
import os

_CACHE: dict | None = None
_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "codigos_unimed_intercambio.csv")


def _carregar() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        with open(_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cod = (row.get("codigo") or "").strip()
                if cod:
                    _CACHE[cod] = {"nome": (row.get("nome") or "").strip()}
    return _CACHE


def resolver_codigo_portal(codigo_tuss: str) -> str:
    """Identidade: o codigo que vai no autocomplete e' o proprio TUSS."""
    return (codigo_tuss or "").strip()


def conhecido(codigo_tuss: str) -> bool:
    return (codigo_tuss or "").strip() in _carregar()
```

- [ ] **Step 4: Escrever o teste de resolução**

```python
# tests/test_intercambio_codigos.py
import importlib


def test_resolver_identidade():
    codigos = importlib.import_module("adapters.unimed_intercambio.codigos")
    assert codigos.resolver_codigo_portal("40901122") == "40901122"
    assert codigos.resolver_codigo_portal("  123 ") == "123"
```

- [ ] **Step 5: Rodar — passa**

Run: `.venv/bin/python -m pytest tests/test_intercambio_codigos.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add adapters/unimed_intercambio/config.py adapters/unimed_intercambio/codigos.py adapters/unimed_intercambio/codigos_unimed_intercambio.csv tests/test_intercambio_codigos.py
git commit -m "feat(intercambio): config + resolver de codigo (identidade)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Sessão (Xvfb + chromium + login + contexto)

**Files:**
- Create: `adapters/unimed_intercambio/sessao.py`
- Modify: `requirements.txt`
- Test: (validação ao vivo no deploy; aqui só import/estrutura)

**Interfaces:**
- Produces: `sessao.navegador()` (async context manager → `page`), `sessao.login(page)`, `sessao.selecionar_contexto(page, nome)`.
- Consumes: `adapters.unimed_intercambio.config`.

- [ ] **Step 1: Adicionar `pyvirtualdisplay` ao requirements**

Em `requirements.txt`, acrescentar a linha `pyvirtualdisplay`.

- [ ] **Step 2: Criar `sessao.py`**

Portar de `bot_connecta.py` **sem alterar a mecânica**: `_garantir_display_virtual` (linhas 35-46), `selecionar_contexto` (201-272), e montar `navegador()`/`login()` a partir do bloco de setup do `_autorizar_uma_tentativa` (716-798). Estrutura:

```python
"""sessao.py — Sessao do portal Unimed CONNECTA (Xvfb + chromium + contexto).
Portado de bot_connecta.py (validado 14/07/2026). Mecanica preservada."""
import contextlib
import sys

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from . import config

_display = None


def _garantir_display_virtual():
    """Xvfb SOMENTE em Linux (VPS sem monitor). Windows/Mac: no-op."""
    global _display
    if not sys.platform.startswith("linux"):
        return None
    if _display is None:
        from pyvirtualdisplay import Display
        _display = Display(visible=0, size=(1280, 900))
        _display.start()
    return _display


async def selecionar_contexto(page, nome_contexto: str) -> tuple:
    # ... COPIAR VERBATIM de bot_connecta.py linhas 201-272 ...
    ...


async def login(page):
    """Login (user/senha via evaluate) + selecionar_contexto. Levanta
    RuntimeError se o contexto falhar (alto, nao silencioso)."""
    await page.goto(config.PORTAL_URL, wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    campo_user = page.get_by_label("Usuário").first
    campo_senha = page.get_by_label("Senha").first
    await campo_user.wait_for(state="attached", timeout=30000)
    await page.wait_for_timeout(2000)
    await campo_user.evaluate(
        "(el, v) => { el.value=v; el.dispatchEvent(new Event('input',{bubbles:true}));"
        " el.dispatchEvent(new Event('change',{bubbles:true})); }",
        config.unimed_conecta_user())
    await campo_senha.evaluate(
        "(el, v) => { el.value=v; el.dispatchEvent(new Event('input',{bubbles:true}));"
        " el.dispatchEvent(new Event('change',{bubbles:true})); }",
        config.unimed_conecta_pass())
    await page.get_by_role("button", name="entrar").first.evaluate("el => el.click()")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)
    ok, motivo = await selecionar_contexto(page, config.contexto_prestador())
    if not ok:
        raise RuntimeError(f"Falha ao selecionar contexto CONNECTA: {motivo}")


@contextlib.asynccontextmanager
async def navegador():
    _garantir_display_virtual()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=config.BROWSER_HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1600, "height": 1000},
                ignore_https_errors=True,
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
            )
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = await context.new_page()
            page.set_default_timeout(60000)
            yield page
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
```

- [ ] **Step 3: Import sanity**

Run: `.venv/bin/python -c "from adapters.unimed_intercambio import sessao; print('ok', callable(sessao.navegador), callable(sessao.login))"`
Expected: `ok True True`.

- [ ] **Step 4: Commit**

```bash
git add adapters/unimed_intercambio/sessao.py requirements.txt
git commit -m "feat(intercambio): sessao chromium+Xvfb + login + contexto (port do bot)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Submit — helpers de portal (port) + contrato

**Files:**
- Create: `adapters/unimed_intercambio/submit.py`
- Test: `tests/test_intercambio_mapeamento.py`

**Interfaces:**
- Consumes: `sessao.navegador/login`, `config.*`, `codigos.resolver_codigo_portal`.
- Produces: `submit.executar(dados: dict) -> dict` (submit_result); `submit._mapear_recibo(recibo: dict, status: str|None) -> dict` (função pura testável).

- [ ] **Step 1: Escrever teste da função pura de mapeamento**

```python
# tests/test_intercambio_mapeamento.py
import importlib


def test_recibo_autorizado_vira_protocolado():
    submit = importlib.import_module("adapters.unimed_intercambio.submit")
    recibo = {"Número Guia Operadora": "999888", "Nº da Autorização": "AUT123",
              "Data de Validade da Autorização": "31/08/2026", "Status": "Autorizado"}
    r = submit._mapear_recibo(recibo, "Autorizado")
    assert r["status"] == "protocolado"
    assert r["numero_protocolo"] == "999888"
    assert r["numero_autorizacao"] == "AUT123"
    assert r["validade"] == "31/08/2026"


def test_recibo_status_nao_autorizado_vira_pendente():
    submit = importlib.import_module("adapters.unimed_intercambio.submit")
    recibo = {"Número Guia Operadora": "", "Status": "Em análise"}
    r = submit._mapear_recibo(recibo, "Em análise")
    assert r["status"] == "requer_humano"
    assert r["requer_captura_manual"] is True
```

- [ ] **Step 2: Rodar — falha (submit inexistente)**

Run: `.venv/bin/python -m pytest tests/test_intercambio_mapeamento.py -q`
Expected: FAIL (`ModuleNotFoundError`/`AttributeError`).

- [ ] **Step 3: Criar `submit.py` — helpers verbatim + `executar` + `_mapear_recibo`**

Copiar de `bot_connecta.py` **verbatim** (só trocar imports p/ `from . import config, sessao, codigos`):
`_salvar_screenshot_erro, _set_value, _select_by_text, _ler_valor_campo, _click, _clicar_ok_alerta_sessao, _blur_e_aguardar, _preencher_com_espera, _selecionar_com_espera, _assentar_pagina, _preencher_resiliente, _selecionar_resiliente, expandir_todos_blocos, _id_input_por_label, _preencher_autocomplete_locator, preencher_autocomplete_por_id, adicionar_item_procedimento, tratar_alertas_pos_envio, clicar_enviar, ler_recibo` (linhas 80-677 do bot).

Substituir o miolo de `_autorizar_uma_tentativa` (686-1072) por uma versão que:
1. **usa `sessao.navegador()`/`sessao.login()`** em vez de montar browser/login inline;
2. lê `dados["crm"]` (obrigatório), `dados["codigo_prestador"]` (default `config.CODIGO_PRESTADOR_FIXO`), `codigos` com `codigo`+`quantidade`;
3. trânsito → **"sim"** (default), depois reenvia;
4. exames_realizados sem justificativa → retorna dict `{"status":"requer_humano", ...}`;
5. erro 500 → `{"status":"erro_submit", ...}` (transitório);
6. remove o `asyncio.sleep(60)` final (artefato de debug).

Adicionar as duas funções de contrato:
```python
def _mapear_recibo(recibo: dict, status: str | None) -> dict:
    """Recibo do CONNECTA -> submit_result. Autorizado -> protocolado
    (numero_protocolo = Guia Operadora); qualquer outro status -> requer_humano
    (conservador I3, nunca inventa)."""
    if status and status.strip().lower() == "autorizado":
        return {
            "status": "protocolado",
            "numero_protocolo": recibo.get("Número Guia Operadora") or None,
            "numero_autorizacao": recibo.get("Nº da Autorização"),
            "validade": recibo.get("Data de Validade da Autorização"),
            "evidencias": [],
            "mensagem": "Autorizacao CONNECTA (intercambio) efetivada.",
        }
    return {
        "status": "requer_humano", "numero_protocolo": None,
        "requer_captura_manual": True, "evidencias": [],
        "mensagem": f"Guia enviada, status retornado: {status!r}. Conferir manual.",
    }


async def executar(job: dict) -> dict:
    """Contrato da esteira. job (dict do worker): carteirinha, medico, crm,
    codigos:[{codigo,quantidade}], codigo_prestador?. Retorna submit_result."""
    for campo in ("carteirinha", "medico", "crm"):
        if not (job.get(campo) or "").strip():
            return {"status": "erro_submit", "numero_protocolo": None,
                    "evidencias": [], "mensagem": f"Campo obrigatorio ausente: '{campo}'."}
    if not job.get("codigos"):
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Nenhum codigo de procedimento informado."}
    return await _fluxo_connecta(job)
```
Onde `_fluxo_connecta(job)` é o corpo portado (dentro de `async with sessao.navegador() as page:`), que ao final chama `recibo = await ler_recibo(page)` e `return _mapear_recibo(recibo, recibo.get("Status"))`, e nos pontos de erro estruturais retorna dicts `{"status":"erro_submit",...}` (sem FalhaDeterministica nesta fase — ver Task 7).

- [ ] **Step 4: Rodar — mapeamento passa**

Run: `.venv/bin/python -m pytest tests/test_intercambio_mapeamento.py -q`
Expected: PASS.

- [ ] **Step 5: Import sanity do submit**

Run: `.venv/bin/python -c "import adapters.unimed_intercambio.submit as s; print('ok', callable(s.executar))"`
Expected: `ok True`.

- [ ] **Step 6: Commit**

```bash
git add adapters/unimed_intercambio/submit.py tests/test_intercambio_mapeamento.py
git commit -m "feat(intercambio): submit (port do bot) + mapeamento de recibo

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `__init__` + registro no worker + `dados`

**Files:**
- Create: `adapters/unimed_intercambio/__init__.py`
- Modify: `worker.py`
- Test: `tests/test_intercambio_exports.py`

**Interfaces:**
- Produces: `adapters.unimed_intercambio.submit/sessao/DOMINIO/NOME`; worker roteia `convenio="unimed_intercambio"` e injeta `crm`/`quantidade`.

- [ ] **Step 1: Criar `__init__.py`**

```python
from . import sessao
from . import config
from .submit import executar as submit

NOME = "unimed_intercambio"
DOMINIO = config.DOMINIO
```

- [ ] **Step 2: Escrever teste de exports**

```python
# tests/test_intercambio_exports.py
import importlib


def test_intercambio_exports():
    a = importlib.import_module("adapters.unimed_intercambio")
    assert a.NOME == "unimed_intercambio"
    assert callable(a.submit)
    assert callable(a.sessao.navegador)
    assert a.DOMINIO == "remote.unimedrecife.com.br:444"
```

- [ ] **Step 3: Rodar — falha (não registrado/estrutura)**

Run: `.venv/bin/python -m pytest tests/test_intercambio_exports.py -q`
Expected: PASS já é possível (import direto). Se falhar, corrigir `__init__`.

- [ ] **Step 4: Registrar no `worker.py` (`_ADAPTERS`)**

Trocar:
```python
    "sulamerica": "adapters.sulamerica",
}
```
Por:
```python
    "sulamerica": "adapters.sulamerica",
    "unimed_intercambio": "adapters.unimed_intercambio",
}
```

- [ ] **Step 5: Incluir `crm` e `quantidade` no `dados` do `_processar`**

No `worker.py`, no dict `dados` (dentro de `_processar`), acrescentar `crm` e `quantidade` por código. Trocar:
```python
                "medico": job.medico,
                "paciente_nome": job.paciente_nome,
                "codigos": [c.model_dump() for c in job.codigos],
```
Por:
```python
                "medico": job.medico,
                "crm": job.crm,
                "paciente_nome": job.paciente_nome,
                "codigos": [c.model_dump() for c in job.codigos],
```
(`model_dump()` já inclui `quantidade` após a Task 1; o adapter lê `item["codigo_tuss"]` via `codigos.resolver_codigo_portal` e `item.get("quantidade", 1)`.)

- [ ] **Step 6: Rodar exports + import worker + suíte**

Run: `.venv/bin/python -c "import worker; print('ok')" && .venv/bin/python -m pytest tests/ -q`
Expected: `ok` + todos PASS.

- [ ] **Step 7: Commit**

```bash
git add adapters/unimed_intercambio/__init__.py worker.py tests/test_intercambio_exports.py
git commit -m "feat(intercambio): __init__ + registro no worker + crm/quantidade no dados

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Envs + doc de deploy

**Files:**
- Modify: `.env.example`
- Create: `docs/DEPLOY_UNIMED_INTERCAMBIO.md`

- [ ] **Step 1: Acrescentar envs ao `.env.example`**

```
# ── Unimed Intercambio (portal CONNECTA) — adapter adapters/unimed_intercambio/ ──
# Engine chromium + headless=False + Xvfb (o portal esconde o form em headless puro).
UNIMED_CONECTA_USER=
UNIMED_CONECTA_PASS=
CONTEXTO_PRESTADOR=Imag Diagnostico Por Imagem Ltda
# UNIMED_CONECTA_URL=https://remote.unimedrecife.com.br:444/connecta/Default.aspx
```

- [ ] **Step 2: Criar `docs/DEPLOY_UNIMED_INTERCAMBIO.md`**

```markdown
# Deploy — Adapter Unimed Intercambio (CONNECTA)

## Pré-requisitos VPS
- Xvfb + xvfb-run (confirmados: /usr/bin/Xvfb, /usr/bin/xvfb-run).
- Chromium do Playwright (confirmado em /root/.cache/ms-playwright/).
- `venv/bin/pip install pyvirtualdisplay` (nova dep).
- `.env`: UNIMED_CONECTA_USER, UNIMED_CONECTA_PASS, CONTEXTO_PRESTADOR.

## Passos (cron pausado, como no deploy do agente)
1. Pausar cron autorizador; backup do crontab.
2. `git pull --ff-only origin main`.
3. `venv/bin/pip install -r requirements.txt` (traz pyvirtualdisplay).
4. Smoke: `venv/bin/python -c "import worker; from adapters.unimed_intercambio import submit; print('ok')"`.
5. `venv/bin/python -m pytest tests/ -q` (dev deps).
6. Religar cron.

## Validação ao vivo (Fase 0 do adapter)
- Seed de 1 job real de intercambio (carteirinha de outra Unimed + crm) e drenar
  na mão: `MODO=cron venv/bin/python worker.py`.
- Confirmar: contexto selecionado, beneficiario localizado, procedimento na tabela,
  alerta de TRANSITO respondido "Sim", recibo lido, `numero_protocolo` = Guia
  Operadora. Ajustar o CSV de codigos com os exames reais.

## Rollback
- `git reset --hard <hash_anterior>`; remover `unimed_intercambio` de `_ADAPTERS`
  não é necessário (sem job desse convenio, o adapter fica inerte).
```

- [ ] **Step 3: Commit**

```bash
git add .env.example docs/DEPLOY_UNIMED_INTERCAMBIO.md
git commit -m "docs(intercambio): envs CONNECTA + checklist de deploy

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7 (Fase 2, pós-validação ao vivo): Costura A — FalhaDeterministica

**Só após o caminho determinístico ser validado ao vivo.** Converter os pontos de erro **in-portal estruturais** de `submit._fluxo_connecta` (contexto não selecionado, beneficiário não encontrado, todos os códigos falharam, campo não preenchido) em `raise FalhaDeterministica` (molde da Costura A dos outros adapters: `VALIDACAO_PORTAL` p/ beneficiário; `ESTADO_INESPERADO`/`SELETOR_NAO_ACHADO` p/ o resto). Erro 500 e `requer_humano` **permanecem** dicts (não são caso de agente). Expor já está feito (`sessao`+`DOMINIO`). Adiar até a validação evita o agente re-navegar um fluxo ainda não provado.

---

## Self-Review

- **Cobertura:** engine chromium/Xvfb (Tasks 2,3 + doc); anexo dispensado (Task 1); crm (Tasks 1,5); quantidade (Tasks 1,5); códigos identidade (Task 2); protocolo=Guia Operadora (Task 4 `_mapear_recibo`); trânsito=Sim + exames→HITL (Task 4 `_fluxo_connecta`); roteamento consumido via slug (Task 5); creds (Task 6). ✅
- **Placeholders:** o único "COPIAR VERBATIM" (Task 3/4) referencia linhas exatas do `bot_connecta.py` — é port de código validado, não placeholder de lógica nova. ✅
- **Consistência de tipos:** `executar(job)->dict`, `_mapear_recibo(recibo,status)->dict`, `resolver_codigo_portal(tuss)->str`, `sessao.navegador()/login(page)`, `DOMINIO="remote.unimedrecife.com.br:444"` — coerentes entre tasks. ✅
- **Escopo:** único subsistema (adapter). Fase 2 (Costura A) separada e explícita. ✅

## Fora de escopo
- Roteamento por prefixo no HOP (cfg_convenios + regra) — lado Lovable/Supabase.
- verificar/varredura de intercâmbio (status sweep) — frente futura.
- Costura A (Task 7) só após validação ao vivo.
```
