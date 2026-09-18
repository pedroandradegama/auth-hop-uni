# Handoff — Camada 3 (`verificar`) + modelo híbrido / loop engineering para casos de falha

**Para:** nova sessão que vai implantar um **modelo híbrido (RPA + human-in-the-loop) com loop engineering** para tratar os casos de falha do fluxo de autorização/verificação.
**De:** sessão que construiu os adapters de convênio e a ação `verificar` (Camada 3 do gate).
**Data:** 2026-07-10.
**Org:** IMAG (`5aa48c18-ea25-4b9f-a54c-2120d509c7b4`).

> Este handoff é **auto-contido**: dá todo o contexto do que existe + onde os casos de falha aparecem + onde o modelo híbrido/loop deve engatar. Junte-o ao handoff da outra sessão.

---

## 0. TL;DR

- Existe uma esteira RPA madura (**auth-hop-uni**, monorepo Python/Playwright na VPS) que **autoriza** e **verifica** guias em portais de convênio (Unimed, Sassepe, SulAmérica), integrada ao HOP (Lovable + Supabase) por fila + callback HMAC.
- A ação **`verificar`** (Camada 3 do gate de faturamento) está **ponta-a-ponta funcionando** para o caminho feliz (senha autorizada → status + validade + guia PDF + campos), incluindo retry de 3 strikes.
- **O que falta e é o coração desta nova sessão:** os **casos de falha** ainda são frágeis. Há um caso real aberto (senha `188879979` → `status_portal desconhecido: ''`) que expõe a necessidade de um **tratamento híbrido**: quando a RPA não consegue classificar com segurança, o caso deve cair num **loop** (re-tentar com estratégia diferente) e/ou num **operador humano** (HITL) — nunca "chutar".
- Invariante-mãe: **I3 — conservador**. Na dúvida, `requer_captura_manual`/HITL, nunca inventa resultado.

---

## 1. Arquitetura (o mapa)

```
HOP (Lovable + Supabase)  ⇄  VPS worker (Playwright)  ⇄  Portal do convênio
   fila + RPC (claim atômico)      poll + callback HMAC        login + navegação
```

- **Monorepo:** `github.com/pedroandradegama/auth-hop-uni` (clonado na VPS em `/opt/imag-autorizador`).
- **Espinha:** `worker.py` (poll/drenar, roteia por convênio), `callback.py` (POST HMAC-SHA256 sobre corpo cru), `schemas.py` (contrato Pydantic), `config.py` (URLs/segredos), `cron_varredura.py` (coleta de status).
- **Adapters** (1 pasta por convênio, self-contained): `adapters/{unimed_recife,sassepe,sulamerica}/` com `config/sessao/_ui/submit/varredura/(verificar|guia)/__init__`.
- **Deploy VPS:** `ssh root@76.13.224.144` (senha). venv **`venv/`** (sem ponto). Roda por **cron** (não PM2): `run_autorizador.sh` (drenar, 5 min) + `run_varredura.sh` (diário). Credenciais no `.env` da VPS.
- **Engines:** Unimed/SulAmérica = **Firefox** headless; Sassepe = **Chromium** (SPA React).

### Memórias (leia primeiro — contêm o mapa fino de cada portal)
No diretório de memória do projeto:
- `auth-hop-uni-sassepe.md`, `auth-hop-uni-sulamerica.md`, `auth-hop-uni-unimed-verificar.md`.

---

## 2. O que já está VIVO (mergeado + deployado)

| Frente | Estado |
|---|---|
| **Adapter Unimed** (submit + varredura `coletar`) | vivo, produção |
| **Adapter Sassepe** (submit + varredura) | vivo (guia real 1189780). CPF é o identificador. |
| **Adapter SulAmérica** (submit + varredura + captura protocolo) | vivo (protocolo 235122942). Carteirinha 20 díg. |
| **`verificar` Unimed v1.1** (Camada 3) | **e2e OK** p/ autorizada + nao_encontrada (ver §3) |
| **Varredura de status → espelho `fat_autorizacao_status_portal`** (Fase 1) | desenhada; VPS já posta `sweep_result`; falta HOP materializar |
| **Coleta de demonstrativos SulAmérica** | outra sessão fiava (PR aberto) |
| **Handoffs docs** | `docs/HANDOFF_*` (demonstrativo, operador entry point, varredura status) |

**HOP (Supabase) — relevante à Camada 3:**
- `fat_verificacao_senha` (fila de verificação): `{id, org_id, lote_id→tiss_lotes, guia_id→tiss_guias, autorizacao_id→autorizacoes, convenio_id→cfg_convenios, senha, numero_carteira, status, tentativas, resultado(jsonb), veredito, reservado_em, resolvido_em}`.
- `fat_verificacao_cb` (circuit breaker): `{convenio_id, falhas_consecutivas, suspenso_em}`.
- RPC `fn_rpa_verificacao_reservar_proximo(p_org_id)`: claim atômico. **Só reivindica** jobs `status='pendente'` **de convênios com `cfg_convenios.verificacao_portal_ativa = true`**. Reseta jobs `em_execucao` parados >60min (tentativas≥2 → `erro`, senão `pendente`).
- Edge `proximo-job-verificacao` (v1.0, Bearer `WORKER_INBOUND_SECRET`) + `receive-verificacao` (v1.1, HMAC `HOP_CALLBACK_SECRET`; aceita `evidencia_b64`/`guia_pdf_b64` → sobe pro Storage `dossies`).
- `cfg_convenios` (catálogo; **não é `convenios`**). Ex.: `UNIMED RECIFE | VITORIA` = `8af61152-cbfa-4d07-aa78-aa46cf6c5ea7`.

---

## 3. `verificar` (Camada 3) — estado detalhado

**O que é:** dado uma **senha** de autorização emitida, consulta o portal e devolve o estado. O HOP usa como gate antes de transmitir lotes TISS (senha cancelada/vencida = bloqueio, glosa evitada).

**Contrato do retorno (`resultado` do callback):**
```json
{ "status_portal": "autorizada|cancelada|vencida|nao_encontrada|erro",
  "validade": "YYYY-MM-DD"|null, "qtd_autorizada": int|null,
  "classe_erro": "estrutural|transitorio|null",
  "evidencia_b64": "<PNG ≤300KB>"|null, "detalhe": "...",
  "guia_pdf_b64": "...", "guia_campos": {...}, "itens": [...] }
```

**Mecânica (mapeada ao vivo, portal Unimed `autorizador.unimedrecife.com.br`):**
1. Login (código/senha) → menu **Autorizações → VALIDAR SENHA** = tela **CONSULTAR AUTORIZAÇÃO**.
2. `input[name=numero]` = senha → **`dispatch_event('click')`** no botão `input[name=buscar]` (⚠️ `page.click()` TRAVA — o onclick dispara AJAX; use dispatch_event) → painel **Resultado da Busca**.
3. Parse: cabeçalho (linhas `td|td`: Carteira, Guia Prestador, Beneficiário, Autorização, **Status**, Cod. Unimed) + tabela **Itens** (`"N. Item - <codigoTUSS> - <MOD> - descr" | Status | QtSol | QtAut`).
4. **Validade NÃO está no CONSULTAR** — vem da **guia PDF** (drill-down): Acompanhar-por-senha (com período amplo 180d) → `listaguia.php` → anexo "Impressão de Guia" (`<n>.pdf`) → **viewer autenticado** `mudareditorimagem.php?codanexos=..&nome=..&protocolo=..` (o arquivo direto dá 401) → baixa via **`page.request.get`** (cookies da sessão) → parse TISS (`guia.py`, pypdf, por vizinhança de rótulo).
5. `guia_campos` extraídos: senha (campo 5 ≠ nº Autorização), **validade_senha**, numero_carteira, beneficiario, solicitante nome/CRM/UF, procedimentos[codigo_tuss/modalidade/qtd].

**Gotchas resolvidos (todos em PRs #13–#16):**
- `page.click` no Buscar trava → **`dispatch_event('click')`**.
- `listaguia.php` é **ISO-8859-1** → `body().decode('latin-1')` (não `r.text()` UTF-8).
- Itens do CONSULTAR sujos (cabeçalho/"Aguarde...") → filtrar linhas com 2 últimas células numéricas + dedup por código.
- Guia PDF nativo-digital → parse confiável (sem OCR).

**E2E validado pela fila real (2026-07-10):** seed em `fat_verificacao_senha` (senha 191866912, convênio Unimed) → worker drenou → `verificar` → callback → HOP gravou `status=concluida, veredito=ok, status_portal=autorizada, validade=31/08/2026` + **guia PDF persistida** (`guia_ref=guias/<job>.pdf`). Retry de 3 strikes também observado funcionando.

**Regra da vigência (spec):** o adapter devolve `autorizada` + `validade` (mesmo se passada); **o HOP deriva `vencida`** comparando `validade < hoje`. `status_portal="vencida"` do adapter provavelmente **nunca** ocorre no Unimed (a tela mostra "Autorizado", não "Vencido").

---

## 4. ⚠️ O CASO DE FALHA ABERTO (ponto de partida do modelo híbrido)

**Senha `188879979` (antiga, validade passada) → `status_portal desconhecido: ''` → `classe_erro=transitorio` → retry 3x → `status=erro`.**

Diagnóstico: o painel do CONSULTAR **renderizou**, mas o parser **não achou o par "Status"** no cabeçalho (`pares.get("Status","")` = `''`). Não é "Senha Inválida" (o regex pegaria → `nao_encontrada`). É uma **estrutura de painel diferente** para essa senha (possivelmente: senha vencida mostra layout distinto, ou o `wait_for_function` casou "Item" de um resquício e o cabeçalho ainda não tinha carregado, ou há uma mensagem que não mapeamos).

**Investigação parada aqui:** ia-se capturar o screenshot que o job guardou (`resultado->>'evidencia_ref'` no Storage `dossies`) para ver o painel exato. **Próximo passo imediato:** baixar essa evidência (ou rodar um debug headless na VPS que dá `dispatch_event` no Buscar e faz dump de `PARES`/`ITENS`/`BODY`) para ver o que a senha vencida mostra, e então: (a) mapear o status/rótulo, ou (b) tratar como caso de HITL.

**Por que isso importa para o modelo híbrido:** este é o padrão de todos os casos de falha — a RPA encontra um estado que **não sabe classificar**. A resposta certa NÃO é falhar seco (3 strikes → erro) nem chutar. É:
1. **Loop de estratégia**: re-tentar com abordagem alternativa (ex.: se o CONSULTAR-por-senha não classifica, cair no drill-down da guia por protocolo; se a guia não vem por período, alargar a janela; etc.).
2. **Escalonar ao humano (HITL)** quando o loop esgota, **com a evidência** (screenshot + o que foi tentado), para o operador decidir no portal e devolver o fato ao motor.

---

## 5. Taxonomia de erro + retry/circuit-breaker (o que já existe)

- **`transitorio`**: timeout de rede, portal lento, sessão expirou, 5xx. O HOP **re-tenta (3 strikes)**. Depois vira `erro`.
- **`estrutural`**: seletor não encontrado (layout mudou), login recusado repetido, WAF/403, manutenção. **Cinco estruturais consecutivas suspendem o convênio inteiro** (circuit breaker `fat_verificacao_cb`) + tarefa crítica. Na dúvida entre os dois → **`transitorio`** (não derruba o convênio à toa).
- Timeout interno do `verificar`: **90s** (spec). ⚠️ Com o download da guia embutido, 90s ficou **apertado** (o caso feliz levou 82s). Considere subir p/ ~150s + backstop do worker (hoje 100s) p/ ~170s — OU separar a captura da guia num passo assíncrono/segundo verbo, para o status não depender do download.
- O worker intercala submit/verificação no drain (`VERIFICACAO_LOTE=5`), gated por `VERIFICACAO_HABILITADA=true` (flag do `.env`).

---

## 6. Onde o MODELO HÍBRIDO / LOOP ENGINEERING engata

Espaço de design para a nova sessão (a decisão é sua; aqui os ganchos que já existem):

**A. Loop de estratégia dentro do adapter (antes de desistir):**
- Hoje `verificar` faz 1 tentativa linear. Transformar em **cascata de estratégias** por caso não-classificado: CONSULTAR-por-senha → (se status vazio) drill-down guia por protocolo → (se guia ausente) alargar janela do Acompanhar → (se ainda nada) devolver `requer_captura_manual` COM evidência. Cada passo com timeout próprio.
- Padrão já usado no projeto: **hard stop conservador (I1/I3)** — nunca produzir resultado parcial/chutado.

**B. Retry inteligente na espinha (worker):**
- Hoje: worker classifica exceção → `transitorio`; HOP re-tenta 3x cegamente. Evoluir para **backoff + estratégia diferente por tentativa** (ex.: tentativa 2 força relogin; tentativa 3 tenta o drill-down). O `tentativas` já está em `fat_verificacao_senha`.

**C. Escalonamento a humano (HITL) — o "híbrido":**
- Já existe a infra de HITL no HOP (fila `sessoes_conversa`, `HitlResolutionPanel`, modo `devolver_autorizacao`; ver `docs/HANDOFF_operador_entry_point.md`). Quando o loop de verificação esgota, **abrir um caso HITL** com: a senha, o `veredito` inconclusivo, a **evidência** (screenshot já sobe pro Storage como `evidencia_ref`) e o histórico de tentativas. O operador confere no portal e injeta o fato (autorizada/vencida/cancelada) de volta ao gate.
- Esse é o **respaldo de loop engineering**: automação tenta N estratégias → se falha, humano fecha o loop → e o resultado do humano **realimenta** o sistema (aprendizado: mapear o novo estado para a próxima vez).

**D. Observabilidade do loop:**
- Cada tentativa deve logar `job_id` (já é regra) + a estratégia usada + o resultado. Guardar no `resultado.tentativas_log` para auditoria e para calibrar o loop.

---

## 7. Invariantes (valem para tudo, inclusive o híbrido)

- **I1** — hard stop antes do irreversível (submit); verificação é read-only, mas nunca "conclui" sem dado real.
- **I2** — falha explícita, nunca silenciosa/chutada.
- **I3** — **conservador**: sem certeza → `requer_captura_manual`/HITL (o coração do modelo híbrido).
- **I4** — evidência (screenshot base64 → `evidencia_ref` no Storage).
- **I5/I6** — credenciais via env prefixado, sem segredo no código.

---

## 8. Referências rápidas

**Repo/arquivos-chave:**
- `worker.py` (`_pollar_verificacao_uma_vez`, `_adapter_por_nome_convenio`, `_erro_verif`, drain intercalado).
- `callback.py` (`_enviar_para`, `enviar_verificacao`).
- `config.py` (`proximo_job_verificacao_url`, `callback_verificacao_url`, `verificacao_habilitada`, `VERIFICACAO_LOTE`).
- `adapters/unimed_recife/verificar.py` (fluxo CONSULTAR + status/itens + chama guia).
- `adapters/unimed_recife/guia.py` (`baixar_guia_por_senha`, `parse_guia` — download viewer + parse TISS).
- `adapters/unimed_recife/teste_verificar.py`, `teste_verificacao.py` (conectividade do poll).

**PRs desta frente:** #11 (espinha verificar), #13 (verbo), #14 (dispatch_event), #15 (itens+guia por senha), #16 (latin-1). Todos mergeados na `main`.

**Envs VPS (`.env`):** `VERIFICACAO_HABILITADA=true`, `HOP_PROXIMO_JOB_VERIFICACAO_URL`, `HOP_CALLBACK_VERIFICACAO_URL` (derivadas das URLs de autorização trocando o nome da função), `UNIMED_USER`/`UNIMED_PASS`, `WORKER_INBOUND_SECRET`, `HOP_CALLBACK_SECRET`.

**Como semear um teste de verificação (satisfaz os FKs):**
```sql
insert into fat_verificacao_senha
  (org_id, convenio_id, lote_id, guia_id, autorizacao_id, senha, status)
values ('5aa48c18-ea25-4b9f-a54c-2120d509c7b4','8af61152-cbfa-4d07-aa78-aa46cf6c5ea7',
  (select id from tiss_lotes limit 1),(select id from tiss_guias limit 1),
  (select id from autorizacoes limit 1),'<SENHA>','pendente') returning id;
```
E o convênio precisa de `cfg_convenios.verificacao_portal_ativa = true`. Drenar: `MODO=cron python worker.py` na VPS.
⚠️ Seed usa FKs aleatórios → bom p/ testar `verificar`, NÃO p/ validar o auto-fill do pedido (que precisa de guia_id real → pedido real).

---

## 9. Próximos passos concretos (para a nova sessão)

1. **Fechar o diagnóstico do caso `188879979`**: baixar `evidencia_ref` do Storage (ou debug headless com dump PARES/ITENS/BODY) → ver o painel da senha vencida → mapear o status **ou** decidir que é caso de HITL.
2. **Desenhar o loop de estratégias** do `verificar` (cascata §6.A) + retry inteligente (§6.B).
3. **Ligar o escalonamento HITL** (§6.C) reusando a infra de pré-atendimento, com evidência + histórico.
4. **Ajustar timeouts** (§5) — 90s→150s interno, ou separar a captura da guia.
5. **Realimentação/aprendizado**: quando o humano resolve, mapear o novo estado para a automação (fechar o loop).
6. **DoD pendente da Camada 3**: `cancelada`/`vencida` reais (vencida via validade passada; o `188879979` é justamente esse teste, travado no parser), + simulação de falha `estrutural` (seletor inválido proposital), + validar auto-fill num caso de lote real.

**Junte este handoff ao da outra sessão** (loop engineering) — este dá o terreno (RPA + gate + failure modes reais); o outro dá o método (loop). O ponto de encontro é o **§6**.
