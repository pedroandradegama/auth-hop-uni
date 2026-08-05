# Patches de Edge (rascunho de referência — Codex valida no código real)

## 1. `supabase/functions/hitl-resolver/index.ts` (~793-801)

**Slug: `intercambio` ANTES de `unimed`. + propagar CRM (seguro) + quantidade.**

```ts
const ctxAut = {
  ...autorizacao,
  convenio_slug:
    slugBase.includes("intercambio") ? "unimed_intercambio" :
    slugBase.includes("unimed") ? "unimed_recife" :
    slugBase.includes("sassepe") ? "sassepe" :
    (slugBase.includes("sul") && slugBase.includes("amer")) ? "sulamerica" :
    slugBase.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "_"),
  // CRM seguro (ver §2.8.3 do handoff): so' usa CRM do dossie se o nome bate.
  crm: crmSeguro(autorizacao),
};
```

**Quantidade — o tipo/mapeamento (~668) descarta `quantidade`. Corrigir:**

```ts
// tipo do input:
exames?: Array<{ slug: string; nome?: string | null; quantidade?: number }>;

// ao montar exames p/ o contexto:
exames: (body.exames ?? []).map(e => ({
  ...e,
  quantidade: Math.max(1, Number(e.quantidade ?? 1)),
})),
```

**CRM seguro (helper) — evita casar nome-novo com CRM-antigo:**

```ts
function crmSeguro(a: any): string | null {
  // 1) CRM explicitamente selecionado pelo operador (seleção estruturada)
  if (a?.medico?.crm) return String(a.medico.crm);
  // 2) CRM do dossiê SÓ se o nome normalizado for o mesmo
  const norm = (s: string) => (s ?? "").toString().toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
  const nomeSel = a?.medico?.nome ?? a?.medico_solicitante ?? null;
  if (a?.medico_solicitante_crm && nomeSel
      && norm(nomeSel) === norm(a?.dossie_medico_nome ?? nomeSel)) {
    return String(a.medico_solicitante_crm);
  }
  // 3) senão, ausente → o enfileirador bloqueia intercâmbio por CRM ausente
  return null;
}
```
> Regra: intercâmbio **sem CRM ⇒ bloquear** (não enfileirar). Nunca inferir CRM antigo após troca de nome.

---

## 2. `supabase/functions/orquestrador-processar/index.ts` (~2061)

Mesmo slug (intercambio antes de unimed). E garantir que o CRM do
`contextoAcumulado.medico_solicitante` (objeto) entre em `p_contexto->>'crm'`
(ou `{medico_solicitante,crm}`) **antes** do `formatarMedicoPortal` achatar em texto.

```ts
const convenio_slug =
  nomeConvLower.includes("intercambio") ? "unimed_intercambio" :
  nomeConvLower.includes("unimed") ? "unimed_recife" :
  nomeConvLower.includes("sassepe") ? "sassepe" :
  (nomeConvLower.includes("sul") && nomeConvLower.includes("amer")) ? "sulamerica" :
  nomeConvLower.replace(/[^a-z0-9]+/g, "_");

const med = contextoAcumulado.medico_solicitante ?? null;   // objeto {nome, crm?}
const crm = (med && typeof med === "object") ? (med.crm ?? null) : null;
// incluir crm no p_contexto passado à fn_autorizacao_enfileirar:
//   { ...dossie, convenio_slug, crm, medico_solicitante: formatarMedicoPortal(med) }
```

---

## 3. `supabase/functions/proximo-job-autorizacao/index.ts` (~67-79)

Enviar `crm` + `quantidade` no job (hoje só manda `medico` + codigos sem quantidade):

```ts
crm: row.medico_solicitante_crm ?? null,
codigos: (row.exames ?? []).map((e: any) => ({
  codigo_tuss: e.codigo_tuss,
  sub_tipo: e.sub_tipo,
  nome: e.nome ?? undefined,
  quantidade: (Number.isInteger(e.quantidade) && e.quantidade > 0) ? e.quantidade : 1,
})),
```
> `medico` continua string do NOME (`extrairNomeMedico`). A VPS quer `medico`(nome) + `crm`(string).
