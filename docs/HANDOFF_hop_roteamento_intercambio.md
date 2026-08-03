# HANDOFF (HOP-side) — Roteamento de Unimed Intercâmbio (CONNECTA)

**Para:** sessão que aplica mudanças no HOP (Lovable + Supabase; alterações via SQL Editor / workflow do HOP).
**De:** sessão da esteira VPS (adapter `adapters/unimed_intercambio/` já vivo em `auth-hop-uni@main`).
**Data:** 2026-07-13. **Revisado** contra o codebase HOP atual (HOP Imag v2) — ver §7.

## 0. O que já existe (VPS) e o que falta (HOP)
- **VPS (pronto):** adapter `unimed_intercambio` no worker; consome `convenio="unimed_intercambio"` + `crm` no job; roda CONNECTA (chromium+Xvfb). Sem anexo; trânsito=Sim; protocolo=Guia Operadora. Costura A (agente) ligada.
- **HOP (falta, este handoff):** (a) mapear o convênio **UNIMED INTERCAMBIO** para o slug `unimed_intercambio`; (b) **enviar `crm`** no job.

## 1. Descoberta que simplifica tudo
O HOP **já modela "UNIMED INTERCAMBIO" como convênio distinto por NOME** (visível em `orquestrador-processar/slots_convenio.ts`, que desambigua "UNIMED RECIFE | IGARASSU" vs "UNIMED INTERCAMBIO"). Logo, **não é preciso roteamento por prefixo de carteirinha** — o nome do convênio já carrega a distinção. (A abordagem de prefixo do rascunho anterior foi descartada.)

## 2. Ponto do roteamento (inalterado no HOP atual)
`supabase/functions/hitl-resolver/index.ts`, ~linhas 793-801:
```ts
const slugBase = (autorizacao.convenio ?? "").toString().toLowerCase()
  .normalize("NFD").replace(/[̀-ͯ]/g, "");
const ctxAut = {
  ...autorizacao,
  convenio_slug:
    slugBase.includes("unimed") ? "unimed_recife" :          // <-- Unimed cai aqui hoje
    slugBase.includes("sassepe") ? "sassepe" :
    (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica" :
    slugBase.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_"),
};
```
Problema: "UNIMED INTERCAMBIO" contém "unimed" → hoje viraria `unimed_recife` (errado).

## 3. Patch do `hitl-resolver` (roteamento por nome + crm)
Checar `intercambio` ANTES do genérico `unimed`, e incluir `crm` no contexto:
```ts
const ctxAut = {
  ...autorizacao,
  convenio_slug:
    slugBase.includes("intercambio") ? "unimed_intercambio" :   // <-- NOVO, antes de unimed
    slugBase.includes("unimed") ? "unimed_recife" :
    slugBase.includes("sassepe") ? "sassepe" :
    (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica" :
    slugBase.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_"),
  // CRM: usar o que ja existe no dossie/autorizacao (nao criar campo novo).
  crm: autorizacao.medico_solicitante_crm
       ?? (autorizacao.medico_solicitante as any)?.crm ?? null,
};
```

## 4. Patch do `proximo-job-autorizacao` (enviar `crm`)
`supabase/functions/proximo-job-autorizacao/index.ts` (~linha 71-79) monta hoje:
```ts
medico: extrairNomeMedico(row.medico_solicitante),
```
Adicionar no objeto `job`:
```ts
crm: extrairCrmMedico(row.medico_solicitante) ?? row.medico_solicitante_crm ?? null,
```
com um helper espelhando `extrairNomeMedico` (aceita objeto `{crm}`, string, ou JSON):
```ts
function extrairCrmMedico(v: unknown): string | null {
  if (!v) return null;
  if (typeof v === "object") return (v as any).crm ?? null;
  if (typeof v === "string") { try { return (JSON.parse(v)?.crm) ?? null; } catch { return null; } }
  return null;
}
```
**NÃO** criar coluna `autorizacoes.crm` — o dado já existe como `medico_solicitante_crm` / campo `.crm` do objeto `medico_solicitante`.

## 5. SQL — cfg_convenios (apenas garantir o slug)
A linha de convênio "UNIMED INTERCAMBIO" provavelmente **já existe** no catálogo (o agendamento a usa). Só garantir o `convenio_slug`:
```sql
-- Conferir primeiro:
select id, nome, convenio_slug, biometria_necessaria, pre_autorizacao
from public.cfg_convenios
where org_id = '5aa48c18-ea25-4b9f-a54c-2120d509c7b4'
  and nome ilike '%intercambio%';

-- Se existir e o slug estiver nulo/errado, setar:
update public.cfg_convenios
set convenio_slug = 'unimed_intercambio', biometria_necessaria = false
where org_id = '5aa48c18-ea25-4b9f-a54c-2120d509c7b4'
  and nome ilike '%intercambio%';

-- Se NAO existir, criar espelhando a de Unimed Recife (ajustar colunas conforme o schema real):
-- insert into public.cfg_convenios (org_id, nome, convenio_slug, tipo, tipo_pagador,
--   biometria_necessaria, pre_autorizacao, verificacao_portal_ativa, ativo, campos_obrigatorios)
-- values ('5aa48c18-...', 'UNIMED INTERCAMBIO', 'unimed_intercambio', 'convenio', 'operadora',
--   false, true, false, true, '{}'::jsonb);
```

## 6. Checklist de validação (HOP)
1. `select` do §5 → confirmar a linha e o slug.
2. Patch `hitl-resolver` (§3) + `proximo-job-autorizacao` (§4).
3. Teste: "Go" no HITL com convênio **UNIMED INTERCAMBIO** → conferir `autorizacoes.convenio`/contexto = slug `unimed_intercambio` E `crm` presente no job que `proximo-job` devolve.
4. Coordenar com a VPS: `UNIMED_CONECTA_*` no `.env` da VPS **já configurado** (feito 2026-07-13).

## 7. Notas de versão (revisão contra HOP v2)
- `hitl-resolver` slug derivation: **inalterado** (793-801) — patch §3 aplica limpo.
- `proximo-job-autorizacao`: usa `row.convenio` + `extrairNomeMedico(row.medico_solicitante)` — patch §4 aplica.
- **Correções vs rascunho anterior deste handoff:** (1) roteamento é por NOME (convênio UNIMED INTERCAMBIO já existe), não por tabela de prefixo — a tabela `cfg_unimed_prefixo_local` foi **descartada**; (2) CRM usa `medico_solicitante_crm`/objeto — **não** criar `autorizacoes.crm`.

## 8. Contrato que a VPS espera (job de intercâmbio)
```json
{ "convenio": "unimed_intercambio", "carteirinha": "<17 dig>",
  "medico": "PEDRO ANDRADE GAMA", "crm": "21798",
  "codigos": [{"codigo_tuss": "40901122", "quantidade": 1}] }
```
Sem `anexos` (intercâmbio dispensa). `sub_tipo` não é usado.
