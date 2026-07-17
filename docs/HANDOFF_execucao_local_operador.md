# HANDOFF — Execução Local com Operador Conectado (biometria prova-de-vida)

**Para:** nova sessão que vai desenhar/implementar o canal de **execução local** (na máquina do operador, NÃO na VPS) para convênios que exigem um **operador humano conectado rodando biometria (prova de vida) em tempo real**.
**De:** sessão que construiu os adapters de convênio + a esteira RPA na VPS + o agente híbrido de fallback (Costuras A/B/C).
**Data:** 2026-07-13.
**Org:** IMAG (`5aa48c18-ea25-4b9f-a54c-2120d509c7b4`).
**Escopo desta frente:** convênio **Hapvida** (biometria facial/digital ao vivo).

Este handoff é **auto-contido**: dá o terreno (o que já existe pra reusar), o design aprovado, os componentes novos com sketches, e as decisões em aberto. É um **design orientador**, não um plano de implementação fechado — a nova sessão faz brainstorming→spec→plano sobre ele.

---

## 0. TL;DR

Hoje a esteira roda **headless na VPS** (poll + callback HMAC): worker puxa job de `proximo-job-autorizacao`, dirige o portal, posta resultado em `receive-autorizacao`. Isso NÃO serve para convênios que exigem **prova de vida** (biometria facial/digital do beneficiário no ato) — precisa de **hardware físico + humano presente**, que a VPS não tem.

Esta frente cria um **segundo canal de execução**: um **runner LOCAL** na máquina de um operador conectado. O runner dirige o portal (Hapvida) até a **tela de biometria**, **PAUSA** para o operador fazer a prova de vida ao vivo, e então **retoma** → captura protocolo → callback. Roteamento por **worklist/claim** (operador online puxa), espelhando o sistema `laudo-*` do HOP.

**Invariante-mãe nova — I7:** *o ato biométrico é SEMPRE humano.* A automação nunca tenta, simula ou contorna a prova de vida. A tela de biometria é uma pausa obrigatória (HITL).

---

## 1. Terreno — o que JÁ EXISTE pra reusar (não reinventar)

### 1.1 Contrato poll + callback HMAC (VPS, maduro)
- Worker puxa job: `POST proximo-job-autorizacao` (Bearer `WORKER_INBOUND_SECRET`), claim atômico no HOP.
- Worker posta resultado: `POST receive-autorizacao`, corpo assinado **HMAC-SHA256** (header `X-HOP-Signature: sha256=<hex>` sobre o corpo cru). A edge valida antes de chamar RPC. **Sem service_role fora do HOP.**
- Contrato `submit_result`: `{status: protocolado|erro_submit|requer_humano, numero_protocolo, requer_captura_manual?, evidencias, mensagem}`.
- Watchdog: `watchdog-autorizacao` marca `requer_humano` em jobs `em_execucao` parados (>30 min).

### 1.2 Padrão claim/worklist em tempo real (`laudo-*`) — O MOLDE DO ROTEAMENTO
O HOP já tem um sistema de **operadores reivindicando trabalho ao vivo**: edges `laudo-claim`, `laudo-unclaim`, `laudo-distribuir`, `laudo-worklist`, `laudo-release`, `laudo-current`. **Espelhe esse padrão** para a fila de execução local — é o análogo mais próximo (radiologista ↔ operador de biometria).

### 1.3 HITL (human-in-the-loop) já existente
- `hitl-resolver` (edge) + fila de pré-atendimento (`sessoes_conversa`, `HitlResolutionPanel`, modo `devolver_autorizacao`). A pausa-para-humano da biometria pode reusar/estender essa infra de "caso aguardando humano".

### 1.4 Agente híbrido de fallback (construído nesta sessão)
- Pacote `agente/` (planner Haiku + verifier Sonnet) entra quando o determinístico lança `FalhaDeterministica` com motivo elegível. Contrato `agent_trace` → `receive-autorizacao` → `fn_rpa_agente_registrar` → `rpa_agente_execucoes`.
- **Reuso local:** o agente PODE tratar os hard stops **não-biométricos** do Hapvida local. Mas **obrigado a I7**: ao encontrar a tela de biometria, escala para o operador (HITL), **nunca tenta passar**.

### 1.5 Adapters self-contained
- `adapters/{unimed_recife,sassepe,sulamerica,amil}/` — molde: `sessao.py` (navegador+login), `submit.py` (executar), `varredura.py`, `__init__.py` (expõe `submit`, `coletar`, `sessao`, `DOMINIO`). **O adapter Hapvida seguirá esse molde**, mas rodando no runner local.
- Credenciais Hapvida já no `.env` da VPS (`HAPVIDA_USER`/`HAPVIDA_PASS`) — no canal local, ficam na máquina do operador (ver §6 segurança).

---

## 2. O problema específico

Convênios com **prova de vida** exigem, no momento da autorização:
1. Hardware físico (leitor de digital / webcam para facial) na máquina onde o portal roda.
2. Presença humana (operador) para conduzir a captura ao vivo.
3. Muitas vezes o **beneficiário presente** (no balcão do operador) para a biometria.

Nada disso existe na VPS headless. Logo: **canal de execução novo, local, com operador conectado**.

**Alvo inicial:** Hapvida. (Amil — bloqueado por WAF no VPS — é beneficiário FUTURO do mesmo canal: Chrome real + IP residencial do operador tende a passar o WAF. Fora de escopo agora, mas o design deve não impedir.)

---

## 3. Arquitetura aprovada

```
HOP (Lovable + Supabase)                 Máquina do OPERADOR (local)
  fila exec-local + presença      ⇄       runner local (poll/claim + browser)
  claim atômico (só online)               dirige portal Hapvida
  callback HMAC (receive-autorizacao)      → PAUSA na biometria (I7)
  UI painel do operador                    → operador faz prova de vida ao vivo
                                           → "concluído" → runner retoma
                                           → captura protocolo → callback
```

**Fluxo do job (Hapvida):**
1. HOP enfileira job de autorização que exige operador (convênio marcado `exige_operador=true`).
2. Operador **online** reivindica o job (claim atômico) via seu runner local.
3. Runner: login → navega → preenche → chega na **tela de prova de vida**.
4. Runner **PAUSA** e sinaliza o operador (UI local + status no HOP = `aguardando_biometria`).
5. Operador conduz a biometria ao vivo (hardware/portal) e clica **"prova de vida concluída"**.
6. Runner **retoma** → finaliza a solicitação (ato irreversível) → captura protocolo (conservador, I3).
7. Callback `submit_result` (HMAC) → HOP.

---

## 4. Componentes NOVOS (sketches — proposta, a nova sessão refina)

### 4.1 HOP / Supabase

**Tabela `exec_local_fila`** (job que exige operador):
```
id, org_id, convenio_id, autorizacao_id/guia_id, payload(jsonb),
status: pendente | reservado | aguardando_biometria | concluido | erro | requer_humano,
operador_id (nullable), reservado_em, atualizado_em, tentativas, resultado(jsonb)
```

**Tabela `exec_local_operador_presenca`** (heartbeat):
```
operador_id (pk), org_id, ultimo_heartbeat, convenios_habilitados(text[]),
versao_runner, online (derivado: ultimo_heartbeat > now()-90s)
```

**RPC `fn_exec_local_reservar_proximo(p_operador_id)`** — claim atômico, **só** reivindica job `pendente` de convênio em `convenios_habilitados` do operador E com o operador `online`. Reseta `reservado` parado (>N min) para `pendente` (watchdog).

**RPC `fn_exec_local_marcar_biometria(p_job_id)`** — transição `reservado → aguardando_biometria` (o runner chegou na tela; o operador precisa agir).

**Edges:**
- `proximo-job-local` (v1.0, Bearer secret do runner) — claim.
- Callback: **reusar `receive-autorizacao`** com um `tipo` novo (ex.: `exec_local_result`) OU novo `receive-local`. Mesmo HMAC. Reaproveita o contrato `submit_result`.
- (opcional) `exec-local-heartbeat` — recebe heartbeat/presença do runner.

**UI HOP (painel do operador):** fila disponível, botão **reivindicar**, status ao vivo do job em execução, botão **"prova de vida concluída"**, indicador de presença/online. (Realtime: Supabase channels ou polling.)

### 4.2 Runner local
- Poll/claim contra `proximo-job-local` (como o `worker.py` da VPS faz contra `proximo-job-autorizacao`, mas com identidade de operador).
- Heartbeat periódico (presença).
- Adapter Hapvida (molde dos adapters): `sessao`, `submit` **com um ponto de PAUSA explícito** na tela de biometria (aguarda sinal do operador — via UI local ou via polling de um flag no HOP).
- Callback HMAC (reusar a função de assinatura do `callback.py`).

---

## 5. Runner local — 3 opções (DECISÃO EM ABERTO)

| Opção | Prós | Contras | Quando |
|---|---|---|---|
| **A. browser-harness / CDP no Chrome do operador** | Reusa ferramenta existente; hardware/webcam/IP/sessão do operador nativos; menor esforço; passa WAF (Amil futuro) | Precisa daemon + dispatcher local fino; menos "produto" | **Recomendado p/ MVP** |
| **B. App desktop (Electron/Tauri)** | Melhor UX (fila+status+botão biometria num app só); controle de update/distribuição; embute browser | Mais esforço de build/assinatura/auto-update; manutenção de app nativo | Quando escalar operadores/UX |
| **C. Extensão de navegador** | Footprint mínimo; roda na aba do operador | Sandbox restrito p/ automação profunda + acesso a arquivo/hardware; frágil | Provavelmente insuficiente p/ biometria |

**Recomendação:** começar em **A** (dispatcher Python fino + browser-harness/CDP no Chrome real do operador, com a UI de controle vivendo no próprio HOP web). Migrar para **B** se a UX/escala exigir. A arquitetura (fila+claim+callback) é **independente** da opção de runner — trocar o runner não muda o HOP.

---

## 6. Invariantes (herdadas + nova I7)

- **I1** — hard stop antes do irreversível (não finalizar solicitação sem todos os campos/anexos ok).
- **I2** — falha explícita, nunca silenciosa.
- **I3** — protocolo conservador: sem casamento seguro → `requer_captura_manual`, nunca inventa número.
- **I4** — evidência (screenshot **não-biométrico**).
- **I5/I6** — credenciais via env, sem segredo no código.
- **I7 (NOVA) — o ato biométrico é SEMPRE humano.** A automação nunca captura, simula, reusa ou contorna a prova de vida. A tela de biometria é pausa obrigatória; o agente de fallback, se usado, escala para o operador ao vê-la.
- **Privacidade (reforço de I7):** dado biométrico **nunca sai da máquina do operador / do portal**. O HOP recebe apenas status + protocolo + evidência não-biométrica. Nenhum frame de webcam / template de digital em callback, storage ou trace.

---

## 7. Modelo de falha / claim / watchdog

- Operador cai **antes** do ato biométrico/irreversível → claim expira → job volta a `pendente` (outro operador online pode pegar). Watchdog reseta `reservado`/`aguardando_biometria` parados.
- Operador cai **depois** do ato irreversível (guia já gerada) → **`requer_captura_manual`, NUNCA re-executa** (risco de guia dupla + de repetir biometria no beneficiário). Mesma regra I1/I3 do VPS.
- `aguardando_biometria` com timeout longo (operador demora): configurável; ao estourar → `requer_humano` + notifica.
- Presença: claim só para operador `online` (heartbeat fresco). Sem operador online p/ o convênio → job fica `pendente` (não falha; espera).

---

## 8. Reuso concreto desta sessão (VPS)

| Artefato VPS | Como reusar no canal local |
|---|---|
| `worker.py` (poll/claim/drenar/callback) | Molde do dispatcher local (trocar URLs + identidade operador) |
| `callback.py` (`_assinar`, `_enviar_para`) | Copiar a assinatura HMAC tal qual |
| `config.py` (getters de env) | Molde de config do runner local |
| Adapters `submit.py` (hard stops, `_snap`, captura conservadora) | Molde do adapter Hapvida + ponto de PAUSA biométrica |
| `agente/` (Costuras A/B/C) | Fallback nos hard stops **não-biométricos**; escala na biometria (I7) |
| Contrato `submit_result` / HMAC / `receive-autorizacao` | Reusar; só adicionar `tipo=exec_local_result` |
| Padrão `laudo-*` (HOP) | Molde do worklist/claim/presença do operador |

---

## 9. Perguntas em aberto (DECIDIR ANTES DE CODAR)

1. **Hapvida — mapear o portal real:** qual é exatamente o passo de prova de vida? SDK embarcado? webcam no navegador? leitor de digital + software do convênio? É por **beneficiário** (presencial) ou do **operador** (assinatura)? → precisa de uma sessão de mapeamento no portal (como foi feito p/ Unimed/Sassepe/SulAmérica).
2. **Presença:** Supabase Realtime *presence* vs coluna `ultimo_heartbeat` + poll. (Heartbeat-column é mais simples e robusto; presence é mais "ao vivo".)
3. **Multi-convênio por operador:** um operador serve vários convênios? (`convenios_habilitados[]` já prevê; confirmar.)
4. **Beneficiário presencial vs remoto:** a prova de vida acontece no balcão do operador (beneficiário ao lado) ou remota? Muda a UX e o timeout.
5. **Runner tech:** confirmar A (browser-harness/CDP) como MVP.
6. **Onde vive o código:** o dispatcher/adapter local mora neste repo (`auth-hop-uni`, num subdir `local/` ou `runner_local/`) ou em repo novo? HOP (edges/migrations/UI) é o repo Lovable separado.
7. **Identidade/secret do runner:** cada operador tem um secret próprio (Bearer) ou um secret compartilhado + `operador_id`? (Preferir secret por operador p/ revogação.)

---

## 10. Plano faseado sugerido (espelha o F0 do agente)

- **Fase 0 — mapeamento:** sessão no portal Hapvida real → documentar login + fluxo até a biometria + o ato exato + captura de protocolo. Sem código de produção.
- **Fase 1 — canal (shadow):** tabelas + RPC claim + edges + heartbeat + UI mínima do operador. Runner faz poll/claim e dirige até ANTES da biometria, então **só escala** (não finaliza). Valida roteamento/presença/claim sem risco.
- **Fase 2 — biometria assistida:** habilita a PAUSA→operador→retoma→finaliza (ato irreversível) num convênio/operador piloto. I7 + I1/I3 duros.
- **Fase 3 — endurecer:** watchdog, timeouts, fallback do agente nos hard stops não-biométricos, observabilidade (vw diária espelhando `vw_rpa_agente_diario`).

---

## 11. Referências rápidas (artefatos HOP reais — confirmados no codebase)

- **Edges relevantes:** `proximo-job-autorizacao`, `receive-autorizacao`, `watchdog-autorizacao`, `hitl-resolver`, `laudo-claim`/`laudo-worklist`/`laudo-distribuir`/`laudo-release`/`laudo-unclaim`/`laudo-current`.
- **Contrato HMAC:** header `X-HOP-Signature: sha256=<hmac_sha256(corpo_cru, HOP_CALLBACK_SECRET)>`. Nunca re-serializar após assinar.
- **Org IMAG:** `5aa48c18-ea25-4b9f-a54c-2120d509c7b4`.
- **Repo VPS (molde de runner/adapter/callback):** `github.com/pedroandradegama/auth-hop-uni` (`worker.py`, `callback.py`, `config.py`, `adapters/*/`, `agente/`).
- **HOP:** repo Lovable + Supabase separado (edges em `supabase/functions/`, schema em `src/integrations/supabase/types.ts`).

---

## 12. O que está FORA de escopo desta frente

- Amil / WAF (beneficiário futuro do mesmo canal; não desenhar agora, só não impedir).
- Migrar Unimed/Sassepe/SulAmérica p/ local (seguem headless na VPS; só migrariam se passarem a exigir biometria).
- Camada 3 / verificar (frente separada; caso senha `188879979`).
- F1 do agente na VPS (armar submit) — decisão pós-observação da `vw_rpa_agente_diario`.
