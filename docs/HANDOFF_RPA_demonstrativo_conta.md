# Handoff — RPA de portais de convênio (padrões da autorização) → nova frente: Demonstrativo de Análise de Conta

> **Para quem vai implementar** a coleta do *demonstrativo de análise de conta* do convênio (arquivo, na maioria XML, atrás de login no portal). Este documento fixa **como fazemos RPA de portal de convênio hoje** (na automação de autorização), pra a nova frente manter uniformidade. Não é sobre autorização — é sobre reusar a mesma espinha, os mesmos padrões de sessão/navegação/Playwright, o mesmo deploy e as mesmas invariantes.

---

## 1. Contexto & o que muda

Já rodamos em produção a **RPA de autorização** (SP/SADT) para 3 convênios — `unimed_recife`, `sassepe`, `sulamerica` — numa arquitetura **espinha + adapters** (monorepo `auth-hop-uni`). O fluxo é bidirecional: **HOP (Lovable+Supabase) ⇄ VPS (worker Playwright) ⇄ Portal do convênio**.

A nova frente (**demonstrativo de análise de conta**) é **coleta**, não submissão:
- Dispara por clique no HOP **ou** agendado (cron).
- Loga no portal do convênio (às vezes **site/perfil de usuário distinto** do usado na autorização).
- **Baixa um arquivo** (XML na maioria; pode ter PDF/outros).
- Devolve o arquivo (+ metadados) ao HOP.

Ou seja: reaproveita **login/sessão/navegação/deploy**, mas o "verbo" é **download de arquivo**, não preencher formulário. Do lado do contrato, isso se parece mais com o `coletar()` (varredura) do que com o `submit()`. Ver §4 e §8.

---

## 2. Onde vive o código (monorepo `auth-hop-uni`)

```
auth-hop-uni/
├── worker.py            # poller/drenador: puxa job, roteia p/ adapter, callback HMAC
├── callback.py          # POST assinado (HMAC) do resultado p/ o HOP
├── schemas.py           # contrato Pydantic do job (valida 422 síncrono antes de abrir browser)
├── config.py            # config da ESPINHA (URLs HOP, secrets, intervalos)
├── cron_varredura.py    # coleta diária multi-convênio (status)
├── adapters/
│   ├── unimed_recife/   # 1 pasta por convênio, self-contained
│   ├── sassepe/
│   └── sulamerica/
│       ├── __init__.py       # expõe submit + coletar (nomes canônicos do contrato)
│       ├── config.py         # "valores mágicos" do portal + credenciais (env prefixado)
│       ├── sessao.py         # login() + navegador() (context manager do browser)
│       ├── _ui.py            # mecânica de UI/helpers do portal
│       ├── submit.py         # verbo submit(job) -> dict
│       ├── varredura.py      # verbo coletar(janela) -> list[dict]
│       ├── codigos.py        # tradução TUSS -> código do portal (identidade se n/a)
│       ├── smoke_test.py     # offline, sem portal/credenciais
│       ├── teste_login.py    # login real, read-only
│       ├── teste_submit.py   # ⚠️ submit real
│       └── DEPLOY.md         # env, deps, como roda, identificador
```

**Convenção-mãe:** cada adapter é **self-contained** e **espelha** um adapter existente. Para a nova frente, o molde mais próximo é **`adapters/sulamerica/`** (portal server-rendered clássico + iframes, engine Firefox) e o **`sessao.py`/`varredura.py`** de qualquer adapter para o padrão de login e de coleta.

---

## 3. Sessão & login — o padrão (`sessao.py`)

Dois elementos, sempre:

### 3.1 `navegador()` — context manager do browser
```python
import contextlib
from playwright.async_api import async_playwright
from . import config

@contextlib.asynccontextmanager
async def navegador():
    async with async_playwright() as p:
        engine = getattr(p, config.BROWSER_ENGINE)          # firefox|chromium por convênio
        browser = await engine.launch(headless=config.BROWSER_HEADLESS)
        try:
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
            page = await context.new_page()
            page.set_default_timeout(60000)
            yield page
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
```
- **Engine por convênio** (não global): SulAmérica/Unimed = **Firefox**; Sassepe (SPA React) = **Chromium**. Fica em `config.BROWSER_ENGINE` (env sobrescreve).
- **Headless por env** (`BROWSER_HEADLESS`, default true). Deixe fácil de rodar com cabeça para debug.
- **Viewport desktop largo** (1920×1080 / 1536×864): a mecânica de clique/coordenada pressupõe layout desktop.

### 3.2 `login(page)` — autentica, falha ALTO
- Cada portal tem seu fluxo; **mapeie o real** (não presuma). Ex.:
  - SulAmérica: form clássico `#code`/`#user`/`#senha` + `#entrarLogin`.
  - Sassepe: **SSO MVOnePass** (redirect p/ `onepass.mv.com.br`, aceite LGPD, escolha de workspace).
- **Nunca silencie falha de login.** Ao final, cheque a URL/elemento de "logado"; se ainda na tela de login → `raise RuntimeError(...)`. Melhor falhar cedo e alto do que seguir cego.
- `login()` é reusado por **todos os verbos** (submit, coletar, e o novo "baixar demonstrativo").

> **Atenção à nova frente:** o demonstrativo pode estar em **site/perfil distinto** do da autorização. Isso é natural: crie um **adapter próprio** (ou um `sessao.py` próprio) para esse portal, com **credenciais próprias** (env prefixado diferente). Não force reutilizar a sessão da autorização se o login é outro.

---

## 4. Contrato do job & verbos (`schemas.py`, `__init__.py`)

O `__init__.py` do adapter **expõe funções com nomes canônicos** que a espinha chama:
```python
from .submit import executar as submit          # async submit(job: dict) -> dict
from .varredura import coletar                   # async coletar(janela_dias) -> list[dict]
NOME = "sulamerica"
```

- **`submit(job) -> dict`**: `{status: "protocolado"|"erro_submit", numero_protocolo, evidencias, mensagem}`.
- **`coletar(janela_dias) -> list[dict]`**: lista de registros normalizados (status de guias).

**Para o demonstrativo**, proponha um **terceiro verbo** — ex. `baixar_demonstrativo(job) -> dict` — seguindo o mesmo formato de retorno estruturado. Sugestão de contrato:
```python
{
  "status": "coletado" | "erro_coleta" | "sem_novidade",
  "arquivos": [{"nome": "...", "path_local": "...", "mime": "application/xml", "sha256": "..."}],
  "competencia": "2026-06",     # ou período/lote do demonstrativo
  "evidencias": [ ... ],        # screenshots (I4)
  "mensagem": "..."
}
```
Registre o verbo no `__init__.py` e no roteador do `worker.py` (`_ADAPTERS`), igual aos existentes.

> **Decisão de arquitetura a tomar pela sessão implementadora:** o demonstrativo pode (a) virar mais um verbo dentro dos adapters de convênio existentes, ou (b) ser um **módulo/tabela próprios** (ex. `demonstrativos`), com seu próprio worker/cron. Recomendo **(b) leve** se o login/portal for distinto — mantém as duas frentes desacopladas. Em ambos os casos, **reuse os padrões deste doc**.

---

## 5. Navegação/interação — padrões por tecnologia de portal

**Regra de ouro:** *mapeie o portal real primeiro* (sondagem ao vivo, ver §9), depois escreva seletores estáveis. Não invente seletor.

### 5.1 Portal server-rendered clássico (jQuery / TISS) — ex. SulAmérica, Unimed
- **Playwright locators** por `id`/`name`/texto. Preferir `#id` e `input[name='...']` (estáveis) a XPath frágil.
- **Iframes:** o conteúdo (form TISS) costuma estar **dentro de iframe**. Ache o frame que contém o seletor-âncora (não confie na URL do frame):
  ```python
  async def achar_frame(page, seletor, tentativas=5, espera_ms=2000):
      for _ in range(tentativas):
          for frame in [page] + page.frames:
              try:
                  if await frame.query_selector(seletor):
                      return frame
              except Exception:
                  continue
          await page.wait_for_timeout(espera_ms)
      return None
  ```
- **`<select>` por `value`:** `await frame.locator("#campo").select_option(value="16")`.
- **Campos com máscara (data, carteirinha, guia):** digitar char-a-char **quebra**. Setar `value` direto + disparar eventos (jQuery aceita):
  ```python
  await page.evaluate("""([id,v])=>{const e=document.getElementById(id);
      e.value=v; e.dispatchEvent(new Event('input',{bubbles:true}));
      e.dispatchEvent(new Event('change',{bubbles:true}));}""", [campo_id, valor])
  ```
- **⚠️ MODAIS jQuery UI travam TUDO:** um alerta/modal aberto cria `<div class="ui-widget-overlay ui-front">` que **intercepta todo pointer event** — o próximo clique dá timeout (`element intercepts pointer events`). **Sempre feche o modal e espere o overlay sumir** antes de seguir:
  ```python
  async def fechar_modal(frame, page):
      try:
          btn = frame.locator("a:has-text('Fechar'), button:has-text('Fechar'), .ui-dialog-titlebar-close").first
          if await btn.count() > 0:
              await btn.click(timeout=4000)
      except Exception:
          pass
      for _ in range(10):
          if await page.locator(".ui-widget-overlay").count() == 0:
              break
          await page.wait_for_timeout(500)
  ```
  (Esse gotcha custou 2 rodadas no SulAmérica — o overlay de um alerta bloqueou o clique seguinte.)

### 5.2 SPA React — ex. Sassepe (só se o portal do demonstrativo for React)
- **Clique por coordenada** (compositor), não "localizar-depois-clicar". Screenshot → lê pixel → `mouse.click(x,y)` → re-screenshot p/ verificar.
- **Inputs React:** `click + type` pelo teclado; **NUNCA** `input.value=` via JS (não dispara o estado).
- **Dropdowns `[role=listbox]` com lazy-load:** só renderizam os primeiros itens até um **`WheelEvent` disparado NO elemento `[role=listbox]`**. `scroll()`/`scrollTop` **não** disparam.

### 5.3 Comum a ambos
- Após navegação: `wait_for_load` / `wait_for_timeout` generoso; portais TISS são lentos.
- **Verifique estado** após cada ação relevante (screenshot / `page_info` / checagem de elemento). Não presuma que clicou.

---

## 6. Download de arquivo (XML) — o que a nova frente precisa

Padrão Playwright para **capturar o download** disparado por um clique/link:
```python
async with page.expect_download(timeout=60000) as di:
    await page.locator("a:has-text('Baixar XML'), #btn-download").first.click()
download = await di.value
destino = os.path.join(config.DOWNLOADS_DIR, download.suggested_filename)
await download.save_as(destino)
```
- **Se o XML vem por link direto** (URL do arquivo já autenticada na sessão): pode ser mais robusto pegar os **cookies da sessão Playwright** e baixar via HTTP com esses cookies (evita depender do clique). Padrão: `context.cookies()` → `httpx` com os cookies → salva bytes.
- **Se abre numa nova aba/popup:** trate `context.expect_page()` / `page.expect_popup()`.
- **Valide o arquivo** antes de devolver: não-vazio, XML bem-formado (parse), e (se aplicável) confira a competência/lote esperado. **I3**: sem certeza do que baixou → marque `requer_conferencia_manual`, não afirme sucesso.
- **Hash** (sha256) do conteúdo p/ idempotência/dedup no HOP (não reprocessar o mesmo demonstrativo).
- **Devolva ao HOP** via URL assinada de storage (padrão inverso do anexo da autorização) ou conforme o HOP definir — **não trafegue bytes gigantes no callback** se der pra usar storage.

---

## 7. Credenciais & segredos (I5/I6)

- **Env prefixado por portal, sem default para segredo:** `SULAMERICA_CODIGO`, `SULAMERICA_SENHA`, etc. Faltou env → **falha cedo e alto** (`_req()` no `config.py`).
- Para o demonstrativo, se o login é **outro perfil/site**, use um **prefixo próprio** (ex. `SULAMERICA_DEMO_USUARIO`/`_SENHA`) — não confunda com as credenciais da autorização.
- **Segredo nunca no código, nunca no git.** Fica no `.env` da VPS (gitignored). O `.env.example` lista as chaves **vazias** + comentário.
- **A IA não digita senha em campo manualmente** durante sondagem: no debug ao vivo, **o humano faz o login**; o adapter (código) é quem autentica em produção com o env.

---

## 8. Invariantes (valem para a nova frente também)

| ID | Invariante | Como aplica ao demonstrativo |
|----|-----------|------------------------------|
| **I1** | Hard stop antes do irreversível | Coleta é read-only → risco baixo. Mesmo assim, não confirme "coletado" sem o arquivo em mão e validado. |
| **I2** | Falha explícita, nunca "chuta" | Login falhou / arquivo não encontrado → erro claro com a causa; nada de retornar vazio silencioso. |
| **I3** | Protocolo/dado conservador | Não sabe se o XML é o certo/atual → `requer_conferencia_manual`, não afirma. |
| **I4** | Evidência (screenshots) | Screenshot em cada etapa-chave e no erro (`evidencias: [{etapa, screenshot_path, ts}]`). |
| **I5/I6** | Credenciais via env prefixado, sem segredo no código | Idem §7. |

---

## 9. Como sondar um portal novo (ao vivo, sem escrever no portal)

Fizemos isso pra mapear o Sassepe e o SulAmérica. Ferramenta: **`browser-harness`** (controla o Chrome do usuário via CDP) — ver `~/Developer/browser-harness/SKILL.md`.
- Abre o portal em **nova aba** (`new_tab`), **o humano faz o login** (auth-wall: a IA não digita credencial).
- Navega até a tela-alvo, **extrai a estrutura real** (seletores, tabela, links de download) com `js(...)` e **screenshots**.
- Descobre os seletores estáveis e o gesto exato (ex.: qual link dispara o download, se abre popup, se o XML é link direto).
- **Só então** escreve o adapter em Playwright espelhando o que funcionou.
- Registre no adapter/DEPLOY os achados não-óbvios (máscara, iframe, overlay, formato do arquivo).

---

## 10. Deploy (VPS) & execução

- **VPS:** `ssh root@76.13.224.144` (acesso por senha). Repo em **`/opt/imag-autorizador`**.
- **venv do cron é `venv/`** (sem ponto) — instale deps aí. `python -m playwright install <engine>` (firefox/chromium conforme o portal) + `install-deps <engine>` (libs do SO, root).
- **Não usa PM2 para o autorizador** — roda por **cron**:
  - submit: `run_autorizador.sh` (modo `drenar`, a cada 5 min).
  - varredura: `run_varredura.sh` (diário).
  - **Para o demonstrativo**, crie um cron análogo (ex. `run_demonstrativo.sh`) se for agendado; ou um endpoint que o HOP aciona via job na fila (padrão poll).
- **`.env` da VPS** carrega os segredos. Teste login isolado (`teste_login.py`, read-only) antes de qualquer coleta real.

---

## 11. Integração com o HOP (disparo por clique / agendado)

Padrão atual da autorização (reusar a forma):
- HOP (Edge Function Deno) **enfileira** um job numa tabela (`autorizacoes`); o worker da VPS **pola** `proximo-job-*` (claim atômico via RPC `... reservar_proximo`, `FOR UPDATE SKIP LOCKED`), processa **um por vez**, e devolve o resultado por **callback HMAC**.
- **Slug do convênio** tem que bater **exatamente** com o registrado no `worker._ADAPTERS` (gotcha real: "Sul América" → precisa virar `sulamerica`, não `sul_america`). Cuide do slug na Edge Function.
- Para o demonstrativo: espelhe isso com uma fila/tabela própria (ex. `demonstrativos_coleta`) e um `proximo-demonstrativo` + callback. **Clique no HOP** ou **cron** só enfileira; o worker coleta e devolve o arquivo (via storage assinado) + metadados.
- **Idempotência:** chave por (org, convênio, competência/lote) + hash do arquivo — não reprocessar/duplicar.

---

## 12. Checklist para começar a nova frente

1. **Sondar o portal do demonstrativo ao vivo** (§9): login, tela do demonstrativo, como o XML é baixado (link direto? botão? popup? nova aba?), formato/competência.
2. **Criar o adapter/módulo** espelhando `adapters/sulamerica/` (ou `varredura.py`): `config.py` (URL + env prefixado próprio), `sessao.py` (login + `navegador()`, engine certa), verbo `baixar_demonstrativo()`, `_ui.py` (helpers), `smoke_test.py`, `teste_login.py`, `DEPLOY.md`.
3. **Aplicar os padrões:** iframe finder, máscara via `value`+eventos, **fechar modal jQuery UI**, download via `expect_download` (ou cookies+httpx), validação do XML, evidências, env prefixado.
4. **Contrato de retorno estruturado** + registro no worker/roteador.
5. **Deploy** no `venv/` da VPS (playwright install da engine) + cron/poll conforme disparo.
6. **HOP:** fila/tabela + Edge Function de enfileiramento (clique/agendado) + callback + slug exato + idempotência por hash.
7. **Testes:** `teste_login.py` (read-only) → coleta real → conferir o XML baixado.

---

### Referências no repo
- `adapters/sulamerica/` — molde mais próximo (server-rendered, iframe, Firefox, máscara, modal jQuery, captura por Consulta).
- `adapters/sassepe/` — molde SPA React (coordenada, `[role=listbox]` WheelEvent, SSO).
- `adapters/*/varredura.py` — padrão de **coleta** (o mais parecido com baixar demonstrativo).
- `worker.py`, `callback.py`, `schemas.py` — espinha (poll, HMAC, contrato).
- `~/Developer/browser-harness/SKILL.md` — sondagem ao vivo.

---

## Apêndice A — SulAmérica: Demonstrativo de Análise de Conta (MAPEADO AO VIVO)

> Sondagem ao vivo no portal real (2026-07-01), login do prestador IMAG. **Fluxo inteiro validado, incluindo download do XML.** Esta é a receita concreta para o primeiro convênio da nova frente.

### A.1 Login & sessão — REUSA o adapter de autorização
O demonstrativo fica **no MESMO portal e MESMO login** da autorização SulAmérica (não é site/perfil distinto). Portanto **reuse `adapters/sulamerica/sessao.login()` e `navegador()`** direto (Firefox, `SULAMERICA_CODIGO`/`USUARIO`/`SENHA`). Não precisa de credencial nova.

Recomendação: implementar como **novo verbo no adapter existente** — `adapters/sulamerica/demonstrativos.py` com `async coletar_demonstrativos(janela) -> dict`, exposto no `__init__.py`. (Se outros convênios tiverem login distinto para o demonstrativo, aí sim adapter/módulo próprio — decisão por convênio.)

### A.2 Navegação
- URL direta: `https://saude.sulamericaseguros.com.br/prestador/servicos-medicos/demonstrativos-tiss-3/demonstrativo-de-pagamento/`
- Menu equivalente: **Serviços Médicos → Demonstrativos TISS 3 → Demonstrativo de Pagamento**.
- ⚠️ **Popup de pesquisa NPS** ("SUA OPINIÃO É ESSENCIAL PARA NÓS") abre por cima ao carregar. **`Escape` fecha** (ou clicar fora). Trate sempre — senão o overlay atrapalha.

### A.3 Filtro de período
- Campos: `#data-inicial` e `#data-final` (formato `dd/mm/yyyy`). Setar **value direto + eventos** (jQuery, mesma técnica da máscara do submit); digitar char-a-char quebra.
- Botão: `#btnPesquisar`.
- ⚠️ **SulAmérica guarda no máximo ~3 meses** de histórico. Coletar por **mês fechado** (01→30/31). Janela padrão sugerida: mês anterior fechado.

```python
await page.evaluate("""(function(){
  function setv(id,v){var e=document.getElementById(id); e.value=v;
    e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));}
  setv('data-inicial','01/06/2026'); setv('data-final','30/06/2026');
  document.getElementById('btnPesquisar').click();
})()""")
```

### A.4 Tabela de resultado
Colunas: `Data Pagamento | Data Lim. Recurso | Valor Apresentado | Valor Processado | Valor Liberado | Demo. Pagto. | Demo. An. Ct. Médica`. Uma linha por **data de pagamento**.

Cada linha tem **5 links** (texto): `[pdf, xml, pdf, xml, csv]`:
- `links[0]`/`links[1]` = **Demo. Pagto.** (pdf / xml)
- `links[2]`/`links[3]` = **Demo. An. Ct. Médica** (pdf / xml) ← **o que queremos**
- `links[4]` = csv

**O alvo (XML de análise de conta) é `links[3]` de cada linha.** Os links têm `href="#"` e **handler jQuery** (sem `onclick` inline) — não dá pra ler a URL do DOM; ela é gerada no clique.

Filtro de linha (JS): `tr` com 6–8 `td` e uma data `dd/mm/yyyy`; pegar os `<a>` cujo texto é exatamente `pdf|xml|csv`.

### A.5 Mecanismo de download — `window.open` → **URL assinada GCS**
O clique no `xml` chama **`window.open()`** para uma **URL pré-assinada do Google Cloud Storage**:
```
https://storage.googleapis.com/contasmedicastransf/DEMONSTRATIVO/DC/20260610/
  DC_000043_20260610_100000014967_001.zip?GoogleAccessId=...&Expires=...&Signature=...
```
- `DC` = Demonstrativo de Conta (análise de conta). Path: `.../DEMONSTRATIVO/DC/<AAAAMMDD>/`.
- Nome: `DC_<seq>_<dataPagamento AAAAMMDD>_<codPrestador>_001.zip`.
- **É `.zip`** — o XML fica **dentro** (`..._001.XML`, TISS `tipoTransacao=DEMONSTRATIVO_ANALISE_CONTA`, encoding ISO-8859-1).
- **A URL é auto-autorizada** (assinatura GCS) → **baixa com HTTP GET puro, SEM cookie/sessão**. `Expires` é efetivamente não-expirável. Validado: `curl` → HTTP 200, `application/zip`.

### A.6 Receita do coletor (Playwright)
Interceptar `window.open` para **capturar as URLs** (não deixa abrir aba/download nativo), clicar cada `links[3]`, depois baixar com **httpx** (sem cookies) e extrair o XML do zip:

```python
# 1. hook: captura as URLs e impede abrir aba
await page.evaluate("""window.__urls=[]; const _o=window.open;
    window.open=function(u){ window.__urls.push(''+u); return null; };""")

# 2. para cada linha, clicar o links[3] (xml An.Ct.Médica)
#    (localizar por: tr com data dd/mm/yyyy -> <a> texto pdf|xml|csv -> índice 3)
#    clicar via coordenada OU via a.click() no JS.

# 3. ler as URLs capturadas
urls = await page.evaluate("window.__urls")

# 4. baixar cada uma com httpx (assinada, sem cookies) e extrair o XML
import httpx, io, zipfile
async with httpx.AsyncClient(timeout=60, follow_redirects=True) as cli:
    for u in urls:
        r = await cli.get(u); r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        nome_xml = next(n for n in zf.namelist() if n.upper().endswith(".XML"))
        conteudo = zf.read(nome_xml)   # bytes ISO-8859-1
        # validar (parse XML, checar tipoTransacao), salvar, hash p/ idempotência
```
Alternativa: Playwright `context.on("page")`/`expect_popup()` — mas `.zip` vira **download event**, mais chato. A interceptação de `window.open` + httpx é mais limpa **porque as URLs são assinadas**.

### A.7 Contrato de retorno sugerido
```python
{
  "status": "coletado" | "erro_coleta" | "sem_novidade",
  "competencia": "2026-06",
  "arquivos": [{
    "nome": "DC_000043_20260610_100000014967_001.XML",
    "data_pagamento": "2026-06-10",
    "tipo_transacao": "DEMONSTRATIVO_ANALISE_CONTA",
    "path_local": "...", "sha256": "...", "mime": "application/xml"
  }],
  "evidencias": [ ... ],
  "mensagem": "..."
}
```
- **Idempotência (I3):** chave = nome do arquivo (`DC_<seq>_<data>_<cod>_001`) + `sha256`. Não re-baixar/duplicar no HOP.
- **Validação:** parse do XML + conferir `tipoTransacao=DEMONSTRATIVO_ANALISE_CONTA`; se não parsear ou vier vazio → `erro_coleta` (não afirmar sucesso).

### A.8 Também disponível na mesma tela (fora de escopo agora, mas mapeado)
- Coluna **Demo. Pagto.** (`links[1]` xml / `links[0]` pdf) — demonstrativo de pagamento (outro `tipoTransacao`).
- `csv` por linha; botões **ATS**, **RGE**, **Solicitar Demonstrativo Excel**.
- Botão **Gerenciar Emails** (`#btnGerenciarEmails`) — envio automático por email (possível fonte alternativa, não usada aqui).

### A.9 Checklist específico SulAmérica
1. `adapters/sulamerica/demonstrativos.py` → `coletar_demonstrativos(janela)`; reusa `sessao.login`/`navegador`.
2. Navegar à URL do demonstrativo → **fechar survey (Escape)** → setar período (mês fechado, ≤3 meses) → `#btnPesquisar`.
3. Interceptar `window.open`, clicar cada `links[3]`, coletar URLs, **httpx GET (sem cookies)**, unzip, extrair `.XML`.
4. Validar XML (tipoTransacao), hash, contrato de retorno.
5. Devolver ao HOP (storage assinado + metadados) — não trafegar bytes grandes no callback.
6. Disparo: verbo na fila (clique no HOP) e/ou cron mensal (mês fechado).
