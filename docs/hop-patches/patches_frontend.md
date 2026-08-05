# Patches de Frontend (rascunho de referência — Codex valida no código real)

## 1. `src/pages/operacoes/pre-atendimento/AutorizacaoNovaPage.tsx` (~289) — 3º enfileirador

Hoje chama `fn_autorizacao_enfileirar` direto e: só permite `sassepe`; fallback de
slug p/ sassepe; **não envia CRM**; **exige anexo**; exige carteira **E** CPF;
**expande quantidade em itens repetidos**. Correções:

- **Rotear intercâmbio** (e demais) por nome, igual aos Edges — idealmente usar
  `convenio_slug` de `cfg_convenios` (via `useConvenios`) como fonte, não recomputar.
- **Enviar CRM** (seleção estruturada do médico — ver item 2).
- **Anexo opcional** quando `convenio_slug === "unimed_intercambio"` (intercâmbio não anexa).
- **Aceitar carteira OU CPF** (não exigir os dois).
- **Enviar `quantidade`** por item (não repetir o item N vezes):

```ts
exames: itens.map(i => ({
  codigo_tuss: i.codigo_tuss,
  modalidade: i.modalidade ?? null,
  nome: i.nome ?? null,
  quantidade: Math.max(1, Number(i.quantidade ?? 1)),
})),
```

- No payload `p_contexto`: incluir `convenio_slug`, `crm` (do médico estruturado),
  `carteirinha`/`cpf` (o que houver), e **remover a exigência dupla + o hardcode sassepe**.

## 2. `src/components/hitl/MedicoSolicitanteCombobox.tsx` (~16) — seleção estruturada

Hoje o `onChange` devolve só o **nome** (o CRM exibido é perdido) → risco de casar
nome-novo com CRM-antigo. Devolver seleção **estruturada**:

```ts
type MedicoSelecionado = { nome: string; crm: string | null; id?: string | null };

// no onChange do item selecionado:
onChange({ nome: item.nome, crm: item.crm ?? null, id: item.id ?? null });
```

E o consumidor (form do HITL / AutorizacaoNovaPage) passa esse objeto adiante como
`medico: { nome, crm, id }` no `autorizacao_input`. O Edge (hitl-resolver) resolve o
CRM com a prioridade segura (operador → dossiê só se nome igual → senão bloquear).

## 3. `useConvenios` — expor `convenio_slug`

Expor `convenio_slug` no hook e usá-lo como **fonte única** do slug em todos os
enfileiradores (HITL, orquestrador, AutorizacaoNovaPage), eliminando os 3
normalizadores por nome (evita divergência/drift).
