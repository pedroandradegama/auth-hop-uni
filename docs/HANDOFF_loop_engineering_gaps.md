# Handoff — Loop-Engineering / Failure-Handling (HOP ⇄ VPS)

**Data:** 2026-08-07
**Origem:** sessão que (a) ativou exames laboratoriais para autorização Sassepe e (b) destravou, ponta a ponta, um job de imagem preso (RM Pé → guia real 1308722). No caminho, o *incidente* expôs os buracos de tratamento de falha que esta frente deve fechar.
**Complementa:** `docs/HANDOFF_verificar_camada3_hibrido_loop.md` (Camada 3 / verificar). Este foca no **submit/autorização** e no **ciclo de reserva → execução → callback**.

---

## 0. TL;DR — o que fechar

Três gaps sistêmicos, todos no HOP (Lovable/Supabase), descobertos depurando um job real:

1. **`fn_autorizacao_registrar_submit` não mapeia os status do agente** (`requer_humano`, `requer_captura`, `em_execucao`) → job com veredito do agente **trava em `em_execucao`** (rótulo mentiroso, some da fila mas não vira revisão humana).
2. **Reserva sem lease + watchdog desligado** → qualquer falha **depois** da reserva prende o job **permanentemente** em `em_execucao`. Hoje só sai com reset manual.
3. **HOP não resolve o CRM do médico solicitante** → o adapter Sassepe não acha o profissional por nome (o portal chaveia por CRM). Foi a causa-raiz do job travado.

O ativo mais forte já existe: a **telemetria do agente** (`rpa_agente_execucoes`) é excelente e deve ser o motor do loop — inclui diagnóstico e **patch sugerido** por execução.

---

## 1. O ciclo atual (como um job flui e onde quebra)

```
HITL Go → fn_autorizacao_enfileirar → autorizacoes(status=pendente)
  → VPS cron (5min) → proximo-job-autorizacao (reserva: status=em_execucao, tentativas++)
  → worker → adapter.submit → resultado
  → callback HMAC → receive-autorizacao → fn_autorizacao_registrar_submit (mapeia status)
  → [agente híbrido] se o determinístico levanta FalhaDeterministica: loop.py tenta N passos
      → agent_trace → fn_rpa_agente_registrar → rpa_agente_execucoes
      → veredito: protocolado | requer_humano | ...
```

**Pontos de quebra observados (job RM Pé, sessao 986a0c6f):**
- Reserva feita (`reservado_em` setado, `status=em_execucao`, `tentativas=1`) **sem `lease_id`/`lease_expires_at`**. Toda falha subsequente = travado.
- Agente devolveu `requer_humano` **5 vezes** ao longo do debug; o HOP nunca transicionou a linha (ver §2.1).
- Só destravou com reset manual repetido: `update autorizacoes set status='pendente', reservado_em=null, tentativas=0`.

---

## 2. Os gaps, com localização e direção de fix

### 2.1 `fn_autorizacao_registrar_submit` não conhece os status do agente

**Sintoma:** o worker posta o callback com `status` do adapter/agente; `receive-autorizacao` (submit_result) delega a `fn_autorizacao_registrar_submit(p_payload)`. Verificado ao vivo:
```sql
select (pg_get_functiondef(oid) ~ 'requer_humano')::text,
       (pg_get_functiondef(oid) ~ 'requer_captura')::text,
       (pg_get_functiondef(oid) ~ 'em_execucao')::text
from pg_proc where proname='fn_autorizacao_registrar_submit';
-- → false, false, false
```
A RPC só trata `protocolado`/`erro_submit`. Um veredito `requer_humano` cai no vazio → a linha fica `em_execucao`.

**Fix:** a RPC precisa mapear o vocabulário completo do agente para estados terminais/roteáveis:
- `requer_humano` / `requer_captura_manual` → um status de **revisão humana** que o operador vê na fila (reusar a infra de HITL / a tela de Autorizações `recentes`).
- gravar `motivo_negativa`/evidência do agente (`diagnostico`, `patch_sugerido`) para o humano agir com contexto.
- garantir idempotência (o callback pode repetir).

### 2.2 Reserva sem lease + watchdog não roda

**Sintoma:** `proximo-job-autorizacao` reserva (`status=em_execucao`) **sem** gravar `lease_id`/`lease_expires_at`. Existe `watchdog-autorizacao` (edge function) mas **não há cron** chamando (o crontab da VPS só tem autorizador/varredura/demonstrativo). Resultado: reserva órfã (worker morre, 401, context-destroyed, etc.) = job preso pra sempre.

**Fix:**
- **Reserva grava lease** com expiry (ex.: `lease_expires_at = now() + interval '10 min'`) na RPC de reserva.
- **Watchdog periódico** (cron na VPS OU pg_cron) que reverte reservas expiradas: `em_execucao` com `lease_expires_at < now()` → `pendente` (respeitando um teto de `tentativas` antes de mandar pra revisão humana).
- Backstop de `tentativas`: após N reservas falhas → `requer_captura_manual` em vez de re-enfileirar infinito.

### 2.3 HOP não resolve o CRM do médico solicitante (causa-raiz do incidente)

**Sintoma:** o job trazia `medico_solicitante = "SANDRA PAIVA BARBOSA"` (só nome, sem CRM). O portal Sassepe **chaveia o solicitante por CRM** — a busca por nome é substring + lazy-load alfabético de ~10 itens, então nome completo longo dá "Nenhum resultado" e por 1 token a pessoa fica fora do chunk. **Achar por nome é inviável.** Com o CRM injetado (`"10032 SANDRA PAIVA BARBOSA"`) o adapter protocolou de primeira.

**Onde nasce:** `hitl-resolver/index.ts` monta `medicoFmt` = `"CRM NOME"` **se** houver CRM (de `medico_solicitante_detalhe.crm`), senão cai no nome só. O CRM vem da extração/CNES do pedido (`doc_extracoes.resolucao.solicitante.crm`) — que **não resolveu** para essa médica.

**Fix (o de maior alavancagem):** garantir que a extração/CNES do Pré-Atendimento **resolva o CRM do solicitante** (por nome + UF, base CNES), de modo que `medicoFmt` sempre saia `"CRM NOME"` para Sassepe/SulAmérica. Isso torna a seleção do solicitante **determinística** e elimina a maior fonte de `requer_humano` no submit. O adapter já tem fallback de busca progressiva por nome, mas é paliativo.

---

## 3. A telemetria do agente é o motor do loop (`rpa_agente_execucoes`)

Cada fallback do agente grava uma linha rica — use como fonte primária do loop de melhoria:

| coluna | uso |
|---|---|
| `etapa_fallback` | onde o determinístico parou (ex.: `submit_sassepe`) |
| `motivo_fallback` | classe (`estado_inesperado`, ...) |
| `diagnostico` | **causa-raiz em linguagem natural** (o agente descreve o que viu) |
| `patch_sugerido` | **conserto proposto pelo próprio agente** (frequentemente certeiro) |
| `trace` (Json) | passos do agente; **não** guarda o `detalhe` cru do `FalhaDeterministica` (limitação: ver abaixo) |
| `passos`, `custo_usd`, tokens | orçamento/observabilidade |

**Padrão de trabalho validado nesta sessão:** ler `diagnostico`/`patch_sugerido` → corrigir o determinístico → reprocessar. Foi assim que os 5 obstáculos do job caíram um a um.

**Melhorias sugeridas para a telemetria:**
- Persistir o `FalhaDeterministica.detalhe` (a mensagem exata do passo que abortou) numa coluna consultável — hoje ele **não** aparece no `trace` (tivemos que instrumentar screenshots no adapter para ver). `tipos.py:to_dict()` já expõe `detalhe`; basta o `loop.py`/registro gravá-lo.
- Materializar um painel: taxa de `requer_humano` por `etapa_fallback`/convênio, top `patch_sugerido` recorrentes → fila de hardening priorizada.

---

## 4. O que JÁ foi corrigido no adapter (não refazer)

Commits na `main` (`713c0a3` → `39b291a`), VPS atualizada por `git pull`:

- **Seleção de perfil** pós-login (`/workspace/selecionar-perfil`): poll até o card hidratar + fail-loud (`sessao.py::_escolher_workspace`).
- **Hidratação do SPA** antes de clicar 'Solicitações' + confirmação do card 'SP/SADT' + retry (`submit.py::_abrir_sp_sadt`).
- **Resiliência a "Execution context was destroyed"** em todos os `evaluate` de navegação (capturam e re-tentam).
- **Busca progressiva do solicitante** (CRM → nome completo → 2 tokens → 1 token) — paliativo; o fix real é o CRM no HOP (§2.3).
- **Pós-Enviar nunca vira erro_submit** (`submit.py::_enviar_solicitacao`): depois do ato irreversível o retorno é sempre `protocolado` (varredura reconcilia o número) — evita re-submit → guia duplicada (I1).
- **Instrumentação `_diag`**: screenshot em disco + URL/título por passo do submit (`evidencias/diag_*.png`).

Estes fecham uma **classe** de falhas (navegação/hidratação/pós-envio) para TODOS os jobs, não só o incidente.

---

## 5. Onde o loop-engineering engata (arquitetura-alvo)

O ciclo ideal, reusando o que já existe:

1. **Reserva com lease** (§2.2) → sem órfãos.
2. **Determinístico** roda; em falha classificada (`FalhaDeterministica`) → **agente** tenta (já existe, `agente/loop.py`).
3. **Veredito mapeado** (§2.1): `protocolado` fecha; `requer_humano`/`requer_captura` → **fila de revisão humana com contexto** (`diagnostico` + `patch_sugerido` + evidências).
4. **Watchdog** (§2.2) devolve reservas expiradas a `pendente` com teto de tentativas.
5. **Realimentação:** `patch_sugerido` recorrente vira item de hardening do determinístico (fechando o loop de aprendizado). O `detalhe` cru persistido (§3) acelera o diagnóstico.

**Invariante de ouro (I1) que o incidente reforçou:** depois de qualquer ato **irreversível** (Enviar/submeter), o sistema NUNCA pode reportar falha que dispare re-execução — sob risco de guia/duplicata. O retry automático (§2.2) precisa saber distinguir "falhou antes de submeter" (re-enfileirável) de "falhou depois de submeter" (só revisão humana).

---

## 6. Referências rápidas

- Adapter Sassepe: `adapters/sassepe/{sessao,submit,_ui,varredura}.py`; testes `teste_login.py`/`smoke_test.py`.
- HOP edges: `receive-autorizacao`, `proximo-job-autorizacao`; RPCs `fn_autorizacao_registrar_submit`, `fn_autorizacao_reconciliar`, `fn_rpa_agente_registrar` (corpos criados no Lovable, não versionados — inspecionar via `pg_get_functiondef`).
- Agente: `agente/{loop,tipos,acoes,pruner}.py`; telemetria `rpa_agente_execucoes`.
- VPS: `ssh root@76.13.224.144`, `/opt/imag-autorizador`, cron 5min, venv `venv/`. Reset manual de job preso: `update autorizacoes set status='pendente', reservado_em=null, tentativas=0 where id=...`.
- Convênios: `cfg_convenios` (Sassepe = `d0c34916-4f44-47d4-9b06-dba44eb0e18e`); regra `cfg_convenio_modalidade_regra` (Sassepe×LAB = `previa`, adicionada nesta sessão).
- Memórias do projeto: `auth-hop-uni-sassepe`, `auth-hop-uni-unimed-verificar`, `auth-hop-uni-sulamerica`.

---

## 7. Prioridade sugerida

1. **§2.3 CRM do médico** — maior alavancagem, elimina a maior fonte de `requer_humano` no submit.
2. **§2.1 mapear veredito do agente** — sem isso, todo `requer_humano` é invisível (job fantasma em `em_execucao`).
3. **§2.2 lease + watchdog** — resiliência do ciclo; sem isso, qualquer soluço prende job.
4. **§3 persistir `detalhe` + painel** — acelera todo o resto.
