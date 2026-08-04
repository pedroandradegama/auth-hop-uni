# HANDOFF (HOP / Codex) — Pendências do lado HOP — **v3 (2ª revisão do Codex incorporada)**

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
2. **Quantidade:** em AMBOS os ramos, incluir no `jsonb_build_object` do exame — com **cast defensivo** (valor não-numérico derrubaria a RPC), mínimo 1:
   ```sql
   'quantidade',
   case when coalesce(e->>'quantidade','') ~ '^[1-9][0-9]*$'
        then (e->>'quantidade')::int else 1 end
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
- `worker._montar_job_agente` agora inclui `crm` no `job_agente` do agente de fallback. Commitado.
- **VPS não muda com esta 2ª revisão** — o contrato do job segue `medico` (string do nome) + `crm` (string). A seleção estruturada de médico (§2.8.3) é interna do HOP; o HOP achata p/ `medico`+`crm` no job. O adapter já exige `crm` e é robusto a `quantidade` ausente (default 1).

### 2.8 Lacunas de FRONTEND + integridade (2ª revisão do Codex — ENTRAM no escopo)
1. **TERCEIRO enfileirador (a página direta):** `src/pages/operacoes/pre-atendimento/AutorizacaoNovaPage.tsx` (~289) chama `fn_autorizacao_enfileirar` direto. Hoje: só `sassepe`, fallback de slug p/ sassepe, **sem CRM**, **exige anexo**, exige carteira **E** CPF juntos, e **expande quantidade em itens repetidos** (em vez de `quantidade`). Precisa: rotear intercâmbio, enviar CRM, tornar anexo opcional p/ intercâmbio, aceitar carteira OU CPF, e mandar `quantidade` (não repetir itens). Os enfileiradores efetivos são o HITL e ESTA página (o orquestrador só monta o dossiê).
2. **Quantidade perdida no HITL:** o front manda `quantidade` em `autorizacao_input`, mas o tipo/mapeamento do `hitl-resolver` (~668) descarta. Corrigir o tipo `exames?: Array<{slug; nome?; quantidade?}>` e, ao montar exames: `quantidade: Math.max(1, Number(e.quantidade ?? 1))`.
3. **CRM pode ser do médico ERRADO (risco clínico):** `MedicoSolicitanteCombobox` (~16) mostra o CRM mas o `onChange` devolve só o nome. Se o operador trocar o médico, o Edge pode casar nome-novo + CRM-antigo do dossiê. Payload deve levar seleção **estruturada** `medico: {nome, crm, id?}`. Prioridade: (a) CRM selecionado pelo operador; (b) CRM do dossiê **só se** o nome normalizado for o mesmo; (c) senão, **bloquear intercâmbio por CRM ausente**. Nunca inferir CRM antigo após o nome mudar.
4. **Higiene de migration + jobs antigos:** NÃO editar a migration aplicada `20260630203905`; criar migration NOVA (coluna + `CREATE OR REPLACE` + comentários + regenerar `types.ts`). A RPC retorna a autorização existente para a mesma `idempotency_key` → **repetir o "Go" NÃO conserta linhas antigas** com slug/CRM errado. **Antes de religar o polling**, auditar autorizações não-terminais: corrigir as identificáveis com segurança, mover as ambíguas p/ `requer_humano`, e **nunca** deixar job antigo defeituoso ser reivindicado.

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

## 5. Ordem recomendada (revisada pelo Codex — 10 passos)
1. **Pausar temporariamente o polling da VPS** durante a mudança do contrato.
2. Criar **migration nova**: coluna `medico_solicitante_crm` + RPC corrigida (`CREATE OR REPLACE`: modalidade p/ intercâmbio + `quantidade` defensiva + CRM).
3. Corrigir `hitl-resolver`: slug (intercambio antes de unimed) + CRM seguro (§2.8.3) + quantidade (§2.8.2).
4. Corrigir o dossiê do `orquestrador-processar` (slug + CRM estruturado antes do `formatarMedicoPortal`).
5. Corrigir `proximo-job-autorizacao` (enviar `crm` + `quantidade`).
6. Corrigir `AutorizacaoNovaPage` + o seletor estruturado de médico (§2.8.1, §2.8.3).
7. `useConvenios` expõe `convenio_slug` e usa como fonte (evita 3 normalizadores).
8. **Auditar jobs antigos** não-terminais (corrigir/mover p/ requer_humano; §2.8.4).
9. Testes de contrato → **religar o polling**.
10. Fazer uma guia real pelo fluxo HOP → VPS.

(Execução local = frente separada; agente = criar migration reprodutível do drift, §4.)

## 6. Validação ponta-a-ponta (quando §2 pronto)
"Go" no HITL com UNIMED INTERCAMBIO → `autorizacoes.convenio='unimed_intercambio'` + `medico_solicitante_crm` + exames c/ quantidade → `proximo-job` devolve job com `crm`/`quantidade` → VPS roda CONNECTA. Creds `UNIMED_CONECTA_*` já no `.env` da VPS.
