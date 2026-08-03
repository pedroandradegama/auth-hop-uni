# HANDOFF (HOP / Codex) — Pendências do lado HOP para a esteira de autorização

**Para:** sessão Codex que edita o HOP (Lovable + Supabase — repo separado do `auth-hop-uni`).
**De:** sessão da esteira VPS (`auth-hop-uni`), que construiu os adapters, o agente de fallback e o adapter Unimed Intercâmbio.
**Data:** 2026-07-13. **Auto-contido** — assume que o Codex NÃO tem o contexto das sessões da VPS.
**Org IMAG:** `5aa48c18-ea25-4b9f-a54c-2120d509c7b4`.

---

## 0. Mapa em 6 linhas (como a esteira funciona)
O HOP enfileira autorizações; um worker na VPS (Playwright) **puxa** o job via edge
`proximo-job-autorizacao` (claim atômico), executa o portal do convênio e **posta** o
resultado via `receive-autorizacao` (HMAC-SHA256 sobre o corpo cru, header
`X-HOP-Signature: sha256=<hex>`). O slug do convênio no job decide qual adapter roda.
Quando o determinístico bate numa parede, um **agente LLM de fallback** entra (só
diagnostica em F0) e manda telemetria `agent_trace` → `fn_rpa_agente_registrar`.

## 1. Contrato que a VPS ESPERA no job (referência)
`proximo-job-autorizacao` devolve um JSON que a VPS valida (Pydantic). Campos:
```
job_id, idempotency_key, org_id,
convenio            # SLUG: unimed_recife | unimed_intercambio | sassepe | sulamerica | amil
carteirinha | cpf   # pelo menos um
medico              # nome (string)
crm                 # NOVO — numero do conselho (exigido por unimed_intercambio)
codigos: [{codigo_tuss, sub_tipo?, quantidade?}]
anexos: [{url, nome}]   # OBRIGATORIO, salvo convenios isentos (unimed_intercambio dispensa)
```
Mudanças recentes na VPS (já em produção): campo `crm`, `quantidade` por código, e
`anexos` opcional para `unimed_intercambio`.

---

## 2. PENDÊNCIA 1 (pronta p/ aplicar) — Roteamento Unimed Intercâmbio
**Objetivo:** guias de intercâmbio (beneficiário de outra Unimed) devem sair com
`convenio="unimed_intercambio"` e carregar `crm`. Hoje **todo Unimed vira
`unimed_recife`** e o `crm` **não é enviado**.

### 2.1 Fato-chave (evita over-engineering)
O HOP **já modela "UNIMED INTERCAMBIO" como convênio distinto por NOME** (visto em
`supabase/functions/orquestrador-processar/slots_convenio.ts`, que desambigua
"UNIMED RECIFE | IGARASSU" vs "UNIMED INTERCAMBIO"). Logo o roteamento é **por nome**,
NÃO por prefixo de carteirinha.

### 2.2 Patch A — `supabase/functions/hitl-resolver/index.ts` (~linhas 793-801)
Hoje:
```ts
const slugBase = (autorizacao.convenio ?? "").toString().toLowerCase()
  .normalize("NFD").replace(/[̀-ͯ]/g, "");
const ctxAut = {
  ...autorizacao,
  convenio_slug:
    slugBase.includes("unimed") ? "unimed_recife" :
    slugBase.includes("sassepe") ? "sassepe" :
    (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica" :
    slugBase.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_"),
};
```
Trocar por (checar `intercambio` ANTES do genérico `unimed`, e propagar `crm`):
```ts
const ctxAut = {
  ...autorizacao,
  convenio_slug:
    slugBase.includes("intercambio") ? "unimed_intercambio" :
    slugBase.includes("unimed") ? "unimed_recife" :
    slugBase.includes("sassepe") ? "sassepe" :
    (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica" :
    slugBase.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_"),
  crm: autorizacao.medico_solicitante_crm
       ?? (autorizacao.medico_solicitante as any)?.crm ?? null,
};
```

### 2.3 Patch B — `supabase/functions/proximo-job-autorizacao/index.ts` (~linha 71-79)
Hoje monta o job com `medico: extrairNomeMedico(row.medico_solicitante)` e **não manda `crm`**.
Adicionar ao objeto `job`:
```ts
crm: extrairCrmMedico(row.medico_solicitante) ?? row.medico_solicitante_crm ?? null,
```
E o helper (espelha `extrairNomeMedico`):
```ts
function extrairCrmMedico(v: unknown): string | null {
  if (!v) return null;
  if (typeof v === "object") return (v as any).crm ?? null;
  if (typeof v === "string") { try { return JSON.parse(v)?.crm ?? null; } catch { return null; } }
  return null;
}
```
⚠️ **NÃO criar coluna `autorizacoes.crm`.** O dado já existe (`medico_solicitante_crm`
e/ou o campo `.crm` do objeto `medico_solicitante`).

### 2.4 SQL — cfg_convenios (só garantir o slug)
```sql
select id, nome, convenio_slug, biometria_necessaria, pre_autorizacao
from public.cfg_convenios
where org_id = '5aa48c18-ea25-4b9f-a54c-2120d509c7b4' and nome ilike '%intercambio%';

-- se existir e slug nulo/errado:
update public.cfg_convenios
set convenio_slug = 'unimed_intercambio', biometria_necessaria = false
where org_id = '5aa48c18-ea25-4b9f-a54c-2120d509c7b4' and nome ilike '%intercambio%';
```
Se não existir, criar espelhando a linha de "UNIMED RECIFE" (mesmas colunas), mudando
`nome='UNIMED INTERCAMBIO'`, `convenio_slug='unimed_intercambio'`, `biometria_necessaria=false`.

### 2.5 Validação
- "Go" no HITL com convênio **UNIMED INTERCAMBIO** → conferir que o contexto enfileirado
  tem `convenio_slug='unimed_intercambio'` e `crm` presente.
- `proximo-job-autorizacao` (chamar manualmente com o secret) devolve o job com `crm`.
- A VPS já tem o adapter + creds `UNIMED_CONECTA_*` (configuradas 2026-07-13).

### 2.6 Invariantes / não-quebrar
- HMAC do `receive-autorizacao` inalterado.
- Não mexer no fluxo dos outros convênios (o `intercambio` é checado ANTES de `unimed`,
  então "UNIMED RECIFE" continua → `unimed_recife`).

---

## 3. PENDÊNCIA 2 (maior, projeto próprio) — Execução local com operador (biometria)
Convênios que exigem **operador humano + biometria (prova de vida) em tempo real**
(alvo: **Hapvida**) precisam de um canal de execução LOCAL (na máquina do operador),
não a VPS headless. Todo o lado HOP disso é NOVO (tabelas de fila + presença de
operador + claim RPC + edges + UI). **Design completo (auto-contido) em:**
`docs/HANDOFF_execucao_local_operador.md` (mesmo repo `auth-hop-uni`, pasta docs).
Resumo: worklist/claim espelhando o padrão `laudo-*` do HOP; invariante nova **I7 — o
ato biométrico é sempre humano** (nunca automatizar/simular a prova de vida). Tratar
como projeto separado após a Pendência 1.

---

## 4. Já FEITO no HOP (não repetir)
- Agente de fallback: tabela `rpa_agente_execucoes` + `fn_rpa_agente_registrar` +
  `receive-autorizacao` aceitando `tipo="agent_trace"` — **implantado e verificado**.
- Observação pendente (não é código): acompanhar `vw_rpa_agente_diario` na 1ª falha
  real agent-elegível (custo esperado $0.05–$0.35/execução).

## 5. Ordem sugerida p/ o Codex
1. Pendência 1 (§2) — pequena, desbloqueia o intercâmbio ponta-a-ponta.
2. Validar (§2.5) + coordenar 1 guia real com a VPS.
3. Pendência 2 (§3) — projeto próprio (brainstorming → spec → plano).
