# Patches HOP — Unimed Intercâmbio (rascunhos de referência p/ o Codex)

> ⚠️ **RASCUNHO DE REFERÊNCIA.** Estes arquivos NÃO estão prontos p/ aplicar às cegas.
> Foram escritos da sessão da **VPS** (`auth-hop-uni`), que **não tem** o corpo completo
> das RPCs/Edges do HOP. O **Codex valida cada trecho contra o código real** do HOP
> (Lovable + Supabase) antes de aplicar. Onde falta o corpo real, há marcadores
> `>>> COLE/AJUSTE <<<`.

Contexto completo e por quê: `../HANDOFF_hop_pendencias_codex.md` (v3).
Contrato VPS confirmado + validado ao vivo: `../HANDOFF_hop_pendencias_codex.md` §1.

## Ordem (revisada pelo Codex — 10 passos)
1. **VPS pausa o polling** (feito pela sessão VPS — avisar antes de começar).
2. Migration nova: `2026-08-04_migration_intercambio.sql` (coluna CRM + RPC corrigida).
3. `patches_edges.md` → `hitl-resolver` (slug + CRM seguro + quantidade).
4. `patches_edges.md` → `orquestrador-processar` (slug + CRM estruturado).
5. `patches_edges.md` → `proximo-job-autorizacao` (crm + quantidade defensiva).
6. `patches_frontend.md` → `AutorizacaoNovaPage` + `MedicoSolicitanteCombobox`.
7. `useConvenios` expõe `convenio_slug` (fonte única; evita 3 normalizadores).
8. Auditar jobs antigos não-terminais (nunca deixar job velho defeituoso ser reivindicado).
9. Testes de contrato → **VPS religa o polling**.
10. "Go" real HOP → VPS.

## Contrato do job (o que a VPS consome — NÃO mudar sem alinhar)
```json
{ "convenio": "unimed_intercambio", "carteirinha": "<17 dig>", "cpf": null,
  "medico": "PEDRO ANDRADE GAMA", "crm": "21798",
  "codigos": [{"codigo_tuss": "40901122", "quantidade": 1}] }
```
Sem `anexos`. `medico` = nome (string); `crm` = string separada (achatar a seleção
estruturada do front). VPS aborta se `crm` ausente.

## O que a VPS devolve (submit_result) — já implementado e validado
- Autorizado → `{status:"protocolado", numero_protocolo:<guia operadora>, senha:<nº autorizacao>, numero_autorizacao, numero_guia_operadora, numero_guia_prestador, validade:null}`
- Negado/Cancelada/não-achado → `{status:"requer_humano", requer_captura_manual:true, mensagem:<motivo>, numero_guia_*}`
- Mapear no HOP: `autorizacoes.senha <- numero_autorizacao`; `autorizacoes.numero_protocolo <- numero_guia_operadora` (fallback `numero_protocolo`).
