# HANDOFF (HOP / Codex) — Pendências do lado HOP — **v2 (corrigido)**

**Para:** sessão Codex que edita o HOP (Lovable + Supabase).
**De:** sessão da esteira VPS (`auth-hop-uni`).
**Data:** 2026-07-13. **v2** incorpora a devolutiva do Codex + leitura da RPC real. **Auto-contido.**
**Org IMAG:** `5aa48c18-ea25-4b9f-a54c-2120d509c7b4`.

> **Correções vs v1 (erros meus, apontados pelo Codex — confirmados no ZIP):**
> 1. `autorizacoes` **NÃO tem** `medico_solicitante_crm` (é só `medico_solicitante text`). Persistir CRM **exige migration** (v1 dizia "não criar coluna" — errado; eu havia lido `medico_solicitante_crm` de `agendamentos_orq`, tabela errada).
> 2. O roteamento genérico de Unimed existe em **DOIS** caminhos: `hitl-resolver` **e** `orquestrador-processar` (v1 só citou um).
> 3. A RPC `fn_autorizacao_enfileirar` **descarta CRM, não preserva `quantidade`, e filtra exames para `modalidade in ('TC','RM')`** — o que **descartaria** exames de intercâmbio como US. Patch só nos Edges NÃO resolve.

---

## 0. Mapa em 6 linhas
HOP enfileira autorizações (`fn_autorizacao_enfileirar` → `public.autorizacoes`); worker VPS **puxa** via `proximo-job-autorizacao` (claim atômico) e **posta** via `receive-autorizacao` (HMAC-SHA256 sobre corpo cru, header `X-HOP-Signature: sha256=<hex>`). O `convenio` (slug) no job decide o adapter. Falha determinística → agente LLM (F0 só diagnostica) + `agent_trace`.

## 1. Contrato que a VPS espera (adapter VALIDADO ao vivo 2026-08-04)
```
convenio (slug), carteirinha|cpf, medico (string), crm (string),
codigos:[{codigo_tuss, sub_tipo?, quantidade?}], anexos (opcional p/ unimed_intercambio)
```
`unimed_intercambio`: sem anexo, sem RM/TC obrigatório, **crm obrigatório**, quantidade usada.

**Status VPS:** o adapter `unimed_intercambio` está **provado ponta-a-ponta** — cria guia real no CONNECTA e captura o resultado no Histórico (Autorizado→`protocolado` com senha; Negado/Cancelada→`requer_humano`; o portal deduplica sozinho). Só falta o HOP **produzir o job correto** (este handoff). Exemplo real que funcionou:
```json
{ "convenio": "unimed_intercambio", "carteirinha": "08650004956229017",
  "medico": "PEDRO ANDRADE GAMA", "crm": "21798",
  "codigos": [{"codigo_tuss": "40901122", "quantidade": 1}] }
```

---

## 2. PENDÊNCIA 1 — Unimed Intercâmbio (o job precisa sair correto do HOP)
Fato: "UNIMED INTERCAMBIO" já é convênio **por nome** no HOP → roteamento por nome (não por prefixo).

### 2.1 Migration — persistir CRM + (a RPC abaixo)
```sql
alter table public.autorizacoes add column if not exists medico_solicitante_crm text;
```

### 2.2 RPC `fn_autorizacao_enfileirar` (migration `20260630203905_...sql`) — 3 correções
Arquivo atual: default `v_convenio_slug := coalesce(p_contexto->>'convenio_slug','unimed_recife')`; ramo `if v_convenio_slug in ('sassepe','sulamerica')` aceita qualquer modalidade, ELSE filtra `where upper(e->>'modalidade') in ('TC','RM')`; o `insert` grava `medico_solicitante` sem CRM.

Correções (recriar a função com `CREATE OR REPLACE`):
1. **Modalidade:** incluir `unimed_intercambio` (e provavelmente `unimed_recife` continua RM/TC) no ramo "qualquer modalidade" — ou melhor, inverter: só `unimed_recife` filtra RM/TC; os demais aceitam tudo. Concretamente, trocar:
   ```sql
   if v_convenio_slug in ('sassepe','sulamerica') then
   ```
   por:
   ```sql
   if v_convenio_slug in ('sassepe','sulamerica','unimed_intercambio') then
   ```
2. **Quantidade:** em AMBOS os ramos, incluir no `jsonb_build_object` do exame:
   ```sql
   'quantidade', coalesce((e->>'quantidade')::int, 1)
   ```
3. **CRM:** adicionar a coluna no `insert into public.autorizacoes (... , medico_solicitante_crm)` e no `values (...)`:
   ```sql
   coalesce(p_contexto->>'crm', p_contexto#>>'{medico_solicitante,crm}')
   ```

### 2.3 Roteamento — corrigir os DOIS caminhos (slug: intercambio ANTES de unimed)
Mesma substituição nos dois:
```ts
convenio_slug:
  slugBase.includes("intercambio") ? "unimed_intercambio" :
  slugBase.includes("unimed") ? "unimed_recife" :
  slugBase.includes("sassepe") ? "sassepe" :
  (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica" :
  slugBase.normalize("NFD").replace(/[̀-ͯ]/g,"").replace(/[^a-z0-9]+/g,"_")
```
- `supabase/functions/hitl-resolver/index.ts` (~793-801) — e propagar `crm` no `ctxAut` (de `medico_solicitante`/dossiê).
- `supabase/functions/orquestrador-processar/index.ts` (~2061) — mesmo slug; garantir que o `crm` do `contextoAcumulado.medico_solicitante` (objeto) entre em `p_contexto->>'crm'` antes do `formatarMedicoPortal` achatar em texto.
- **Recomendação do Codex (boa):** tornar `cfg_convenios.convenio_slug` a fonte única e os 3 normalizadores consultarem-na, em vez de recomputar por nome. (Refactor opcional, mas elimina drift.)

### 2.4 `proximo-job-autorizacao` — enviar `crm` e `quantidade`
`supabase/functions/proximo-job-autorizacao/index.ts` (~67-79): hoje manda `medico` e `codigos:[{codigo_tuss,sub_tipo,nome}]`, sem `crm`/`quantidade`. Adicionar:
```ts
crm: row.medico_solicitante_crm ?? null,
// e no map de exames:
codigos: (row.exames ?? []).map(e => ({
  codigo_tuss: e.codigo_tuss, sub_tipo: e.sub_tipo, nome: e.nome ?? undefined,
  quantidade: e.quantidade ?? 1,
})),
```

### 2.5 cfg_convenios — garantir o slug
```sql
select id,nome,convenio_slug,biometria_necessaria,pre_autorizacao from public.cfg_convenios
where org_id='5aa48c18-ea25-4b9f-a54c-2120d509c7b4' and nome ilike '%intercambio%';
update public.cfg_convenios set convenio_slug='unimed_intercambio', biometria_necessaria=false
where org_id='5aa48c18-ea25-4b9f-a54c-2120d509c7b4' and nome ilike '%intercambio%';
```

### 2.6 Testes de contrato (antes de liberar claim pela VPS)
Testar que, para um dossiê de intercâmbio, o job final tem: `convenio="unimed_intercambio"`, `crm` preenchido, `quantidade` por exame, exames de qualquer modalidade preservados, `anexos` pode ser vazio.

### 2.7 Já corrigido no lado VPS (por esta sessão)
- `worker._montar_job_agente` agora inclui `crm` no `job_agente` do agente de fallback (era a lacuna que o Codex apontou em `worker.py:100`). Commitado.

---

## 3. PENDÊNCIA 2 — Execução local/biometria (frente separada)
Codex confirmou: já existe **fundação parcial** no HOP (migration `20260720171901_...` — colunas/presença/lease/claim/2 marcos biométricos, callback Ed25519, edges de heartbeat/claim/biometria/escala/callback), MAS não opera ponta-a-ponta. Defeitos a tratar (do Codex):
- Nenhum enfileiramento marca `canal='local'`/`exige_operador=true`; sem UI React; sem runner/adapter Hapvida.
- `receive-autorizacao-local` grava dedup ANTES da RPC → retry vira "duplicado" sem processar (idempotência quebrada).
- Watchdog antigo não separa `canal='vps'` de `local` (pode escalar runner local saudável em 30min); `fn_exec_local_watchdog` não está agendada.
- Auth do runner por secret compartilhado aceitando `operador_id/org_id` do corpo → impersonação. `proximo-job-local` não envia médico (contrato divergente).
Tratar como projeto próprio (roteamento → segurança/idempotência → UI → provisionamento chaves → runner Hapvida → piloto). Design de referência: `docs/HANDOFF_execucao_local_operador.md`.

## 4. Agente de fallback — DRIFT a resolver
Codex não achou migration versionando `rpa_agente_execucoes` nem `fn_rpa_agente_registrar` (só aparecem no banco/tipos). **Criar migration reprodutível** desses objetos (e de quaisquer RPCs/tabelas hoje só-no-banco) p/ eliminar drift repo↔banco.

## 5. Ordem recomendada (Codex)
1. Pendência 1: migration (CRM + RPC modalidade/quantidade) + 2 Edges (slug/crm) + `proximo-job` (crm/quantidade).
2. Testes de contrato do job.
3. Conferir `cfg_convenios` **ao vivo** (o ZIP não prova o estado do banco).
4. Migrations reprodutíveis (incl. agente).
5. Execução local como frente separada.

## 6. Validação ponta-a-ponta (quando §2 pronto)
"Go" no HITL com UNIMED INTERCAMBIO → `autorizacoes.convenio='unimed_intercambio'` + `medico_solicitante_crm` + exames c/ quantidade → `proximo-job` devolve job com `crm`/`quantidade` → VPS roda CONNECTA. Creds `UNIMED_CONECTA_*` já no `.env` da VPS.
