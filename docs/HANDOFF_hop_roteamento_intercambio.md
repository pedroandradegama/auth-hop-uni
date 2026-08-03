# HANDOFF (HOP-side) — Roteamento de Unimed Intercâmbio (CONNECTA)

**Para:** sessão que aplica mudanças no HOP (Lovable + Supabase, repo separado; alterações via SQL Editor / workflow do HOP).
**De:** sessão da esteira VPS, que já entregou o adapter `adapters/unimed_intercambio/` (portal CONNECTA), vivo em `auth-hop-uni@main`.
**Data:** 2026-07-13.

## 0. O que já existe (VPS) e o que falta (HOP)
- **VPS (pronto):** adapter `unimed_intercambio` registrado no worker; consome `convenio="unimed_intercambio"` no job e roda o CONNECTA (chromium+Xvfb). Sem anexo; `crm` obrigatório; trânsito=Sim; protocolo=Guia Operadora.
- **HOP (falta, este handoff):** fazer o HOP **rotear** guias de intercâmbio para esse slug e **enviar `crm`** no job.

## 1. Ponto exato do roteamento
`supabase/functions/hitl-resolver/index.ts`, no "Go" do operador (modo `devolver_autorizacao`), deriva o slug (~linhas 793-801):

```ts
const slugBase = (autorizacao.convenio ?? "").toString().toLowerCase()
  .normalize("NFD").replace(/[̀-ͯ]/g, "");
const ctxAut = {
  ...autorizacao,
  convenio_slug:
    slugBase.includes("unimed") ? "unimed_recife" :   // <-- TODO Unimed cai aqui hoje
    slugBase.includes("sassepe") ? "sassepe" :
    (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica" :
    slugBase.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_"),
};
```
Hoje **todo Unimed vira `unimed_recife`**. A carteirinha está disponível em `autorizacao.numero_carteira` neste escopo.

## 2. Regra de roteamento (por prefixo, parametrizável)
Cartão Unimed = 17 dígitos; os **4 primeiros** identificam a Unimed de origem. Recife (local) tem prefixo(s) próprio(s); **qualquer outra origem = intercâmbio**.

**Regra recomendada (inversa, robusta a novas origens):** se o convênio é Unimed e o prefixo da carteira **NÃO** está na lista de prefixos LOCAIS (Recife) → `unimed_intercambio`; senão `unimed_recife`.

## 3. SQL — tabela de parametrização + seed + cfg_convenios

```sql
-- 3.1 Tabela parametrizavel de prefixos Unimed locais (Recife).
create table if not exists public.cfg_unimed_prefixo_local (
  org_id     uuid not null,
  prefixo    text not null,               -- ex.: '4 primeiros digitos' da carteira Recife
  descricao  text,
  ativo      boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (org_id, prefixo)
);
alter table public.cfg_unimed_prefixo_local enable row level security;
-- (adicionar policy de leitura conforme padrao do HOP)

-- 3.2 Seed: PREENCHER com os prefixos REAIS das carteiras Unimed Recife (locais).
--     (o Pedro tem os valores; exemplos ilustrativos abaixo)
insert into public.cfg_unimed_prefixo_local (org_id, prefixo, descricao) values
  ('5aa48c18-ea25-4b9f-a54c-2120d509c7b4', '0865', 'Unimed Recife - AJUSTAR')
on conflict do nothing;

-- 3.3 cfg_convenios: linha para o slug unimed_intercambio (catalogo/gate).
--     Espelhar a linha de Unimed Recife, mudando slug + biometria=false.
--     verificacao_portal_ativa: deixar false ate' validar o verbo verificar no CONNECTA.
insert into public.cfg_convenios (org_id, nome, convenio_slug, tipo, tipo_pagador,
  biometria_necessaria, pre_autorizacao, verificacao_portal_ativa, ativo, campos_obrigatorios)
values ('5aa48c18-ea25-4b9f-a54c-2120d509c7b4', 'Unimed Intercambio', 'unimed_intercambio',
  'convenio', 'operadora', false, true, false, true, '{}'::jsonb)
on conflict do nothing;
```

## 4. Patch do `hitl-resolver` (roteamento + `crm`)
Substituir o cálculo do `convenio_slug` por uma resolução que consulta os prefixos locais quando for Unimed:

```ts
// Helper: decide unimed_recife vs unimed_intercambio por prefixo da carteira.
async function slugUnimed(sb, orgId, numeroCarteira: string | null): Promise<string> {
  const dig = (numeroCarteira ?? "").replace(/\D/g, "");
  const prefixo = dig.slice(0, 4);
  if (!prefixo) return "unimed_recife";              // sem carteira: default conservador
  const { data } = await sb.from("cfg_unimed_prefixo_local")
    .select("prefixo").eq("org_id", orgId).eq("ativo", true).eq("prefixo", prefixo);
  return (data && data.length) ? "unimed_recife" : "unimed_intercambio";
}

const convenioSlug =
  slugBase.includes("unimed")
    ? await slugUnimed(sb, sess.org_id, autorizacao.numero_carteira)
    : slugBase.includes("sassepe") ? "sassepe"
    : (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica"
    : slugBase.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_");

const ctxAut = {
  ...autorizacao,
  convenio_slug: convenioSlug,
  crm: autorizacao.crm ?? autorizacao.crm_solicitante ?? null,  // <-- garantir crm no contexto
};
```

**`crm` no job:** o worker (VPS) já lê `job.crm` (schema atualizado). A edge `proximo-job-autorizacao` precisa **incluir `crm`** no payload que devolve — hoje monta `{convenio, medico, codigos, ...}` (linha ~71). Adicionar `crm: row.crm ?? null`. E `fn_autorizacao_enfileirar` deve persistir `crm` na `autorizacoes` (coluna `crm` — criar se não existir):

```sql
alter table public.autorizacoes add column if not exists crm text;
```
E o front do HITL deve capturar/enviar o CRM do solicitante (campo já coletado no dossiê? confirmar) para `autorizacao.crm`.

## 5. Checklist de validação (HOP)
1. Aplicar 3.1–3.3 + `alter table autorizacoes add crm`.
2. Patch do `hitl-resolver` (§4) + `proximo-job-autorizacao` (incluir `crm`).
3. Seed dos prefixos LOCAIS reais (Recife).
4. Teste: um "Go" no HITL com carteira de OUTRA Unimed → conferir `autorizacoes.convenio = 'unimed_intercambio'` + `crm` preenchido.
5. Coordenar com a VPS: setar `UNIMED_CONECTA_*` no `.env` da VPS ANTES do 1º job real (senão o adapter falha no login).

## 6. Contrato que a VPS espera (job de intercâmbio)
```json
{ "convenio": "unimed_intercambio", "carteirinha": "<17 dig outra Unimed>",
  "medico": "PEDRO ANDRADE GAMA", "crm": "21798",
  "codigos": [{"codigo_tuss": "40901122", "quantidade": 1}] }
```
Sem `anexos` (intercâmbio dispensa). `sub_tipo` não é usado.
```
