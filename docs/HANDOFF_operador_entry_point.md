# Handoff — Entry point do OPERADOR (iniciar extração/autorização de dentro do HOP)

> **Objetivo:** hoje os inputs/docs de uma autorização chegam do **paciente via WhatsApp**. Esta frente adiciona uma **porta de entrada de operador**: um funcionário da IMAG, de dentro do HOP, **anexa os documentos** (pedido médico + carteirinha) e **dispara a mesma esteira** de extração → dossiê → HITL → enfileiramento na fila de autorização (VPS). Casos: **exames que precisam ser autorizados na hora**, **fluxos presenciais/balcão**, retrabalho, contingência quando o WhatsApp não é o canal.

> **Princípio-guia:** **NÃO** criar uma esteira paralela. A extração, o dossiê, o HITL e o enfileiramento **já existem e funcionam**. Esta frente é só uma **nova porta de entrada** que alimenta o **mesmo pipeline**. Reusar > reimplementar.

Base da análise: codebase HOP (React + Vite + Supabase/Deno edge functions). Referências `arquivo:linha` são do snapshot analisado; confira contra o código atual antes de codar.

---

## 1. Como funciona HOJE (fluxo WhatsApp) — e onde ele acopla ao telefone

Cadeia atual (paciente → autorização):

```
whatsapp-webhook  →  extrair-documento  →  orquestrador-processar  →  sessoes_conversa (HITL)
                                                                         │
                                              operador resolve no HITL ──┘
                                              (HitlResolutionPanel, modo "devolver_autorizacao")
                                                                         │
                                              hitl-resolver → fn_autorizacao_enfileirar → autorizacoes
                                                                         │
                                              VPS worker: proximo-job-autorizacao → adapter → receive-autorizacao
```

Peças e acoplamento:

- **`whatsapp-webhook`** (`supabase/functions/whatsapp-webhook/index.ts`) — hoje é **só recebimento/log**; não cria `sessoes_conversa` direto. **Não é reusável** para operador (é específico do canal WhatsApp). ← ponto que a nova porta substitui.
- **`extrair-documento`** (`supabase/functions/extrair-documento/index.ts`) — OCR/extração por visão (LLM) + resolução determinística de exames no `cat_exames`. **JÁ É DESACOPLADO do canal:** aceita `documentos` (storage_path/url) e `telefone`/`sessao_id` **opcionais** (`origem` default "whatsapp"); grava em `doc_extracoes`. **Reusável direto.**
- **`orquestrador-processar`** (`supabase/functions/orquestrador-processar/index.ts`) — monta o dossiê (`contexto`/`contexto_doc`: paciente, convênio, numero_carteira, medico_solicitante, exames), decide os gates de HITL (ex. `motivo_hitl="autorizacao_convenio_pronta"`), e atualiza `sessoes_conversa`. **Input `ProcessarInput` EXIGE `telefone`** e `origem` (já aceita `"presencial"` como valor). É aqui que mora o acoplamento (ver §4).
- **`sessoes_conversa`** — a "unidade de trabalho" do HITL. Colunas-chave: `id, org_id, telefone, status, estado_atual, motivo_hitl, contexto, prioridade, atribuido_a, ...`. O HITL cockpit lê daqui.
- **HITL frontend** — `src/components/hitl/HitlCockpit.tsx` (fila 3 colunas), fila via `src/hooks/useHitlFila.ts` (`sessoes_conversa` com `status='aguardando_humano'`), resolução via `src/components/hitl/HitlResolutionPanel.tsx` (modo `"devolver_autorizacao"` → `hitl-resolver`). Rota `/operacoes/hitl` (`src/pages/operacoes/HitlPage.tsx`).
- **`hitl-resolver`** (`supabase/functions/hitl-resolver/index.ts`) — modo `devolver_autorizacao` recebe `autorizacao_input` (convenio, numero_carteira, cpf, medico "CRM NOME", exames) e chama `fn_autorizacao_enfileirar` → `autorizacoes`. **Já é o ponto de saída para a VPS.**

**Onde o pipeline HARD-depende do telefone/WhatsApp (só 3 pontos, todos em RPC):**
| Ponto | Uso do telefone | Alternativa p/ operador |
|-------|-----------------|-------------------------|
| `fn_orq_resolver_sessao(org_id, telefone, origem)` | cria/resolve a `sessoes_conversa` (chave = telefone) | chave de sessão sintética/própria (ver §4) |
| `fn_orq_resolver_tag_telefone(org_id, telefone)` | pré-resolve unidade/convênio por telefone | ignorável p/ operador (ele informa unidade/convênio) |
| `fn_crm_registrar_evento(telefone, ...)` | log na timeline do CRM | opcional / usar ref do operador |

Tudo o mais (extração, montagem do dossiê, gates de HITL, enfileiramento) é **genérico** — não olha o telefone.

---

## 2. A proposta em uma frase

**Adicionar uma página de operador que: (1) sobe os docs pro bucket `dossies`, (2) chama `extrair-documento`, (3) chama `orquestrador-processar` com `origem="presencial"` e uma chave de sessão de operador, e deixa o caso cair no MESMO HITL cockpit** — onde o operador (o mesmo ou outro) revisa e clica "Encaminhar para autorização", exatamente como no fluxo WhatsApp. Zero mudança na VPS; zero esteira nova.

Dois modos possíveis (a sessão implementadora escolhe — ver §6):
- **Modo A (reuso máximo):** cria uma `sessoes_conversa` de origem operador → cai no HITL cockpit atual → resolve/enfileira como hoje.
- **Modo B (atalho direto):** operador preenche tudo na hora (carteirinha/médico/exames já conferidos) e a página chama **`hitl-resolver devolver_autorizacao` diretamente**, pulando a fila (bom para "autorizar na hora"). Reusa o mesmo backend de enfileiramento.

Recomendação: **implementar o Modo A primeiro** (reuso máximo, aproveita a UI de resolução existente) e oferecer o **Modo B** como "enviar direto" para o caso presencial urgente.

---

## 3. Blocos reutilizáveis (já existem no HOP)

| Bloco | Onde | Reuso |
|-------|------|-------|
| Upload p/ storage `dossies` | `src/hooks/useAtendimentoAnexos.ts` (`uploadAnexo`/`persistirAnexosErp`) | ✅ direto (bucket `dossies`, path `atendimento/<id>/<uuid>_<nome>`) |
| Componente de anexos | `src/components/pedidos-exame/AnexosStaged.tsx` (staged) e `src/components/files/FileUploadDialog.tsx` | ✅ base pronta (categorias: solicitacao_medica, carteira_convenio, ...) |
| Extração de documento | `supabase/functions/extrair-documento` | ✅ direto (telefone opcional) |
| Montagem dossiê + gates | `supabase/functions/orquestrador-processar` | ✅ com ajuste da chave de sessão (§4) |
| Fila HITL | `src/hooks/useHitlFila.ts` + `src/components/hitl/HitlCockpit.tsx` | ✅ o caso do operador aparece aqui |
| Resolução + enfileiramento | `src/components/hitl/HitlResolutionPanel.tsx` (modo `devolver_autorizacao`) + `hitl-resolver` | ✅ direto |
| Enfileirar p/ VPS | RPC `fn_autorizacao_enfileirar` → `autorizacoes` | ✅ direto |
| Contrato worker | `proximo-job-autorizacao` + `receive-autorizacao` (VPS) | ✅ nenhuma mudança |
| Combobox médico / resolvers | `MedicoSolicitanteCombobox`, `ResolverExames`, `ResolverConvenio` (em `src/components/hitl/`) | ✅ reuso no form do operador |

**Não existe** hoje um caminho "manual/presencial/balcão" de autorização (busca por `manual|presencial|operador|avulso` só achou `canal:'presencial'` em agendamento e `StartTriggerType:'MANUAL'` em workflows — nada de autorização). Ou seja: **é greenfield na porta de entrada, mas reuso total no miolo.**

> Nota: `PedidosExame.tsx` / `NovoPedidoDrawer.tsx` criam **pedidos de exame** (`pedidos_exame` + `tiss_guias`) — é um fluxo de **agendamento/faturamento**, **não** de autorização, e o upload lá acontece **depois** de salvar (não dispara extração). Não confundir com esta frente. Pode, no futuro, ganhar um botão "iniciar autorização" que reusa esta porta.

---

## 4. O único ponto a resolver: chave de sessão SEM telefone

`orquestrador-processar` e `fn_orq_resolver_sessao` usam **telefone como chave** da `sessoes_conversa`. Para o operador não há telefone (ou há, mas não é o eixo). Duas opções:

- **Opção 1 (menos código, pragmática):** gerar uma **chave sintética** por caso, ex. `op:<uuid>` ou `presencial:<cpf>:<timestamp>`, e passar como `telefone` para `orquestrador-processar(origem="presencial")`. O sistema de tag cria uma tag vazia; o operador informa unidade/convênio manualmente. Funciona sem tocar em RPC.
- **Opção 2 (mais limpa, um pouco de backend):** estender `fn_orq_resolver_sessao` para aceitar `p_external_ref`/`p_paciente_id` como chave alternativa ao telefone, e `fn_crm_registrar_evento` para aceitar `external_ref`. Desacopla de verdade a `sessoes_conversa` do canal.

**Recomendação:** começar com **Opção 1** (destrava a frente sem mexer em RPC), e migrar para **Opção 2** quando o volume justificar. Documentar a chave sintética escolhida (prefixo `op:`/`presencial:`) para não colidir com telefones reais e para filtrar no cockpit.

---

## 5. Fluxo proposto (Modo A)

```
[Operador] página "Iniciar Autorização"
   │  anexa pedido médico + carteirinha (+ CPF/observações)
   ▼
1. upload → bucket dossies (useAtendimentoAnexos)          → storage_paths
2. POST extrair-documento {org_id, origem:"presencial",     → doc_extracoes (lote_id)
      documentos:[{storage_path}]}                             + resolucao (exames/convenio/carteira/medico)
3. POST orquestrador-processar {org_id, origem:"presencial",→ sessoes_conversa (estado_atual,
      telefone:<chave-op>, conteudo:{documentos_extraidos}}    motivo_hitl, contexto=dossiê)
   ▼
4. Caso cai no HITL cockpit (mesma fila) ─ badge "presencial/operador"
   ▼
5. Operador revisa (carteirinha 20díg p/ SulAmérica, médico "CRM NOME", exames)
   e clica "Encaminhar para autorização"  → hitl-resolver devolver_autorizacao
   ▼
6. fn_autorizacao_enfileirar → autorizacoes (pendente)
   ▼
7. VPS worker drena → adapter do convênio submete no portal → receive-autorizacao (protocolo)
```

Modo B (presencial urgente): a própria página, com os campos já conferidos, chama `hitl-resolver devolver_autorizacao` no passo 3, pulando 4–5.

---

## 6. Plano de implementação (concreto)

### Frontend (React)
1. **Página** `src/pages/operacoes/IniciarAutorizacaoPage.tsx` (rota `/operacoes/autorizacao`).
2. **Rota** em `src/App.tsx` (bloco `<ProtectedRoute>`), lazy import — seguir o padrão das outras páginas de `operacoes/`.
3. **Nav** em `src/components/layout/AppSidebar.tsx` — item sob **Operações → Orquestrador** (ou junto de "Atendimento"), com `usePermissions()` para gating.
4. **Componentes**: reusar `AnexosStaged`/`FileUploadDialog` (upload) + `MedicoSolicitanteCombobox`/`ResolverExames`/`ResolverConvenio` (form) — os mesmos do HITL.
5. **Hook** `useIniciarAutorizacao()`: orquestra upload → `extrair-documento` → `orquestrador-processar` (Modo A) **ou** → `hitl-resolver devolver_autorizacao` (Modo B); mostra a confiança da extração pro operador conferir antes de enviar.

### Backend (Supabase)
6. **Chave de sessão** (§4): Opção 1 (sintética) sem mudança de RPC; ou Opção 2 (estender `fn_orq_resolver_sessao`).
7. **Origem** `"presencial"`/`"operador"` já é aceita pelo orquestrador — usar para marcar o caso (badge no cockpit + filtro).
8. **(Opcional) Edge function fina** `iniciar-autorizacao-operador` que encapsula upload-assinado + extrair + processar numa transação lógica (evita orquestrar 3 chamadas no cliente). Recomendado para robustez.

### Nada muda
- VPS worker, adapters, `proximo-job-autorizacao`, `receive-autorizacao`, `fn_autorizacao_enfileirar`, schema do job — **intactos**. A porta do operador entrega no mesmo `autorizacoes`.

---

## 7. Onde o operador vê o caso

- **Modo A:** no **HITL cockpit** (`/operacoes/hitl`) — o caso do operador entra na mesma fila (`sessoes_conversa`, `status='aguardando_humano'`), idealmente com **badge/filtro "presencial"** (via `origem`/prefixo da chave) para separar do WhatsApp. Reusa toda a UI de resolução.
- **Modo B:** feedback imediato na própria página "Iniciar Autorização" (enfileirou → acompanha status via `autorizacoes`/`watchdog-autorizacao`).

Sugestão de UX: a página "Iniciar Autorização" mostra, após o envio, o **status do job** (pendente → em_execução → protocolado/erro) lendo `autorizacoes` — o operador presencial acompanha em tempo real.

---

## 8. Decisões em aberto (para a sessão implementadora)

1. **Modo A vs B como default** — recomendação: A primeiro (reuso da UI de resolução), B como "enviar direto" para presencial urgente.
2. **Chave de sessão** — Opção 1 (sintética, sem RPC) para destravar; Opção 2 (RPC) depois.
3. **Identificação do paciente** — presencial costuma ter CPF/carteirinha na mão; o form deve permitir preencher direto (SulAmérica exige **carteirinha 20 díg**, não CPF; Sassepe usa **CPF**; ver os adapters). Reusar o gate "carteirinha OU CPF" já existente no `HitlResolutionPanel`.
4. **Permissão/perfil** — qual papel pode iniciar autorização (recepção? faturamento?). Gating no sidebar + RLS.
5. **Auditoria** — marcar `encaminhado_por` = operador (o `autorizacao` já tem esse campo no hitl-resolver).

---

## 9. Checklist

1. Definir Modo (A/B) e chave de sessão (§4).
2. Página + rota + nav + permissão (`IniciarAutorizacaoPage`).
3. Hook `useIniciarAutorizacao`: upload (`dossies`) → `extrair-documento` (origem presencial) → `orquestrador-processar` (chave op) [Modo A] ou `hitl-resolver devolver_autorizacao` [Modo B].
4. Reusar componentes de resolução (médico/exames/convênio) e o gate carteirinha-OU-CPF.
5. Badge/filtro "presencial" no HITL cockpit.
6. (Opcional) edge `iniciar-autorizacao-operador` encapsulando o passo-a-passo.
7. Mostrar status do job (`autorizacoes`) na página após envio.
8. Testar ponta-a-ponta: operador anexa → HITL/enqueue → VPS drena → protocolo (usar Sassepe ou SulAmérica, que já rodam).

---

### Referências (HOP) — confira contra o código atual
- Ingestão/extração: `supabase/functions/whatsapp-webhook`, `.../extrair-documento`, `.../orquestrador-processar`.
- HITL: `src/components/hitl/HitlCockpit.tsx`, `src/hooks/useHitlFila.ts`, `src/components/hitl/HitlResolutionPanel.tsx`, `src/pages/operacoes/HitlPage.tsx`.
- Enfileiramento/saída: `supabase/functions/hitl-resolver` (modo `devolver_autorizacao`), RPC `fn_autorizacao_enfileirar`, `supabase/functions/proximo-job-autorizacao`, `.../receive-autorizacao`.
- Upload: `src/hooks/useAtendimentoAnexos.ts`, `src/components/pedidos-exame/AnexosStaged.tsx`, `src/components/files/FileUploadDialog.tsx`.
- Roteamento/nav: `src/App.tsx`, `src/components/layout/AppSidebar.tsx`.
- **VPS (não mexer):** `auth-hop-uni/worker.py`, `adapters/*`, `schemas.py`.
