# HANDOFF (HOP / Codex) — Loop-engineering: gaps de failure-handling

**Para:** sessão Codex (HOP — Lovable + Supabase).
**De:** sessão VPS (`auth-hop-uni`).
**Data:** 2026-08-07. **Auto-contido.** Contexto completo do incidente: `HANDOFF_loop_engineering_gaps.md`.
**Org IMAG:** `5aa48c18-ea25-4b9f-a54c-2120d509c7b4`. Sassepe convênio = `d0c34916-4f44-47d4-9b06-dba44eb0e18e`.

> ⚠️ Snippets = **referência**. Codex valida contra os corpos REAIS das RPCs/Edges
> (criadas no Lovable, não versionadas — inspecionar via `pg_get_functiondef`).

## 0. O que já foi feito na VPS (não refazer)
- **§3-emitir:** o `agent_trace` agora carrega **`detalhe_fallback`** (mensagem crua do passo que abortou — `FalhaDeterministica.detalhe`). Falta o HOP **persistir** (coluna, item §3 abaixo).
- **§2.2-watchdog (caller):** VPS tem `watchdog.py` + `run_watchdog.sh` + `config.watchdog_url()` prontos p/ chamar a edge `watchdog-autorizacao` por cron (a cada 10 min, auth `Bearer WORKER_INBOUND_SECRET`). Falta o HOP: **gravar lease na reserva** + a **lógica do watchdog** (abaixo).
- Adapter Sassepe já endurecido (navegação/hidratação/pós-envio); pós-Enviar nunca vira `erro_submit` (I1). Ver `HANDOFF_loop_engineering_gaps.md` §4.

## 1. GAP §2.1 — `fn_autorizacao_registrar_submit` não mapeia o veredito do agente
**Sintoma:** a RPC só trata `protocolado`/`erro_submit`. Veredito `requer_humano`/`requer_captura_manual` cai no vazio → linha fica `em_execucao` (fantasma). Verificado ao vivo: a fn não contém `requer_humano`/`requer_captura`/`em_execucao`.

**Fix (migration nova; `CREATE OR REPLACE`):**
- Mapear o vocabulário completo do callback: `protocolado` → terminal ok; `erro_submit` → como hoje; **`requer_humano`/`requer_captura_manual` → status de REVISÃO HUMANA** que aparece na fila do operador (reusar infra HITL / tela Autorizações `recentes`).
- Persistir contexto p/ o humano agir: `diagnostico`, `patch_sugerido`, **`detalhe_fallback`** (novos no payload), `motivo_negativa`/evidência.
- **Idempotência**: o callback pode repetir (HMAC reenviado) — a mesma `idempotency_key`/`job_id` não pode duplicar transição.
- **I1**: se o resultado indicar ato PÓS-submit (ex.: `requer_captura_manual` com protocolo ausente após envio), **nunca** voltar p/ `pendente` (risco de guia dupla) — vai p/ revisão humana.

## 2. GAP §2.2 — reserva sem lease + watchdog
**a) Reserva grava lease** — em `proximo-job-autorizacao` (RPC de reserva): ao setar `status='em_execucao'`, gravar `lease_id` (uuid) + `lease_expires_at = now() + interval '10 min'`. (Add colunas se faltarem.)

**b) Watchdog** (edge `watchdog-autorizacao`, acionada pelo cron da VPS):
```
UPDATE autorizacoes
   SET status='pendente', reservado_em=null, lease_id=null, lease_expires_at=null
 WHERE status='em_execucao' AND lease_expires_at < now()
   AND tentativas < :teto           -- respeitar teto
   AND <NÃO passou do ato irreversível>;   -- I1
-- tentativas >= teto  → status='requer_captura_manual' (revisão humana, sem re-fila)
```
- **Auth**: aceitar `Bearer WORKER_INBOUND_SECRET` (a VPS chama assim).
- **I1 crítico**: só reverter p/ `pendente` reservas que falharam **ANTES** do submit. Se houver sinal de que o Enviar aconteceu (ex.: guia_prestador gerada / flag), **não re-enfileirar** → revisão humana. Sem isso, retry automático = guia duplicada.

## 3. GAP §2.3 — HOP não resolve o CRM do solicitante (causa-raiz do incidente)
**Sintoma:** portal Sassepe chaveia o solicitante por **CRM**; busca por nome é inviável (substring + lazy-load). Job veio só com nome (`"SANDRA PAIVA BARBOSA"`) → `requer_humano`. Com CRM (`"10032 SANDRA..."`) protocolou de primeira.

**Onde:** `hitl-resolver/index.ts` monta `medicoFmt="CRM NOME"` só se houver `medico_solicitante_detalhe.crm` (de `doc_extracoes.resolucao.solicitante.crm`), que não resolveu.

**Fix (maior alavancagem):** a **extração/CNES do Pré-Atendimento** deve **resolver o CRM** do solicitante (por nome + UF, base CNES) de forma que `medicoFmt` saia sempre `"CRM NOME"` p/ Sassepe/SulAmérica → seleção determinística. (Cruza com o handoff de intercâmbio `docs/hop-patches/` — CRM estruturado no payload; aqui o foco é a RESOLUÇÃO na extração.) Sem CRM resolvido p/ convênio que exige → bloquear/rotular p/ revisão, nunca mandar só-nome.

## 4. §3 — persistir `detalhe_fallback` + painel
- **Coluna**: `alter table public.rpa_agente_execucoes add column if not exists detalhe_fallback text;` e `fn_rpa_agente_registrar` gravar `p_payload->>'detalhe_fallback'`. (A VPS já envia o campo.)
- **Painel** (materializar): taxa de `requer_humano` por `etapa_fallback`/convênio + top `patch_sugerido` recorrentes → fila de hardening priorizada. `rpa_agente_execucoes` já tem `diagnostico`/`patch_sugerido`/`custo_usd`/tokens.

## 5. Invariante de ouro (I1) — vale p/ §2.1 e §2.2
Depois de qualquer ato **irreversível** (Enviar/submeter), o sistema NUNCA pode reportar falha que dispare re-execução. Retry/watchdog precisa distinguir "falhou ANTES de submeter" (re-enfileirável) de "falhou DEPOIS" (só revisão humana). O adapter já garante que pós-Enviar retorna `protocolado`; o HOP não pode desfazer isso mandando de volta p/ `pendente`.

## 6. Prioridade (do handoff)
1. **§2.3 CRM** — elimina a maior fonte de `requer_humano` no submit.
2. **§2.1 mapear veredito** — sem isso, todo `requer_humano` é job fantasma em `em_execucao`.
3. **§2.2 lease + watchdog** — resiliência (a VPS já chama o watchdog; falta lease + lógica).
4. **§3 coluna `detalhe_fallback` + painel** — acelera o diagnóstico de tudo.

## 7. Referências
- RPCs/edges: `receive-autorizacao`, `proximo-job-autorizacao`, `watchdog-autorizacao`; `fn_autorizacao_registrar_submit`, `fn_autorizacao_enfileirar`, `fn_autorizacao_reconciliar`, `fn_rpa_agente_registrar` (inspecionar via `pg_get_functiondef`).
- Contrato do callback (VPS→HOP): `status ∈ {protocolado, erro_submit, requer_humano}`, + `requer_captura_manual`, `mensagem`, `numero_protocolo`/`numero_guia_*`, e (no `agent_trace`) `diagnostico`/`patch_sugerido`/`detalhe_fallback`/`motivo_fallback`/`etapa_fallback`.
- Reset manual de job preso (paliativo): `update autorizacoes set status='pendente', reservado_em=null, tentativas=0 where id=...`.
