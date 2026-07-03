# Handoff RESPOSTA — Varredura de status de autorização (tabela `autorizacao_status_portal`)

**De:** chat das varreduras/adapters (VPS `imag-autorizador`)
**Para:** chat do orquestrador (bot WhatsApp HOP)
**Responde:** "Handoff — Varredura sistemática de status de autorização (tabela unificada)" (2026-07-03)
**Decisão tomada com o Pedro:** começar pela **Fase 1** (nível-guia).

---

## TL;DR

- Dá pra materializar uma tabela espelho — **mas** as varreduras hoje são **nível-guia**, não nível-procedimento. Casar por `codigo_tuss` + **validade** + **saldo** exige **drill-down por guia**, que é a **Fase 2** (mesmo trabalho da ação `verificar`/Camada 3 — sincronizar as duas).
- **Fase 1 (escolhida):** espelho **nível-guia** — responde *"esse beneficiário tem guia **aprovada** nesse convênio (nesta data)?"*. Reduz HITL nos casos óbvios (nenhuma guia aprovada → claramente não autorizado). **Não** filtra por exame específico nem por vigência ainda.
- **Cobertura (Q1):** as varreduras enxergam a **visão do prestador IMAG**. Se a autorização do convênio é **atrelada ao prestador executante**, cobre o caso de agendar-na-IMAG; se é **genérica** (beneficiário escolhe onde usar), o caso "autorizei direto pra outro lugar" fica fora. **Pergunta de negócio em aberto** (ver §Q1).

---

## Respostas às perguntas (§6 do handoff original)

Baseado no que cada `coletar()` realmente raspa hoje (as três varreduras foram construídas e rodam):

| | Unimed (`unimed_recife`) | Sassepe | SulAmérica |
|---|---|---|---|
| Tela | Acompanhar Solicitações | Histórico de Solicitações | Consulta de Solicitações |
| Casa por | **nome + data** (sem cpf/carteira na lista) | **CPF** | **carteira** (+ nome) |
| Nº guia | protocolo | numero_protocolo | Nº Guia |
| status normalizado | ✅ (AUTORIZADO/NEGADO/…) | ✅ | ✅ |
| **codigo_tuss por linha** | ❌ (nível guia) | ❌ | ❌ |
| **validade início/fim** | ❌ | ❌ | ❌ |
| **saldo (qtd aut/util)** | ❌ | ❌ | ❌ |
| senha | ❌ (drill-down) | ❌ | ❌ |

### Q1 — Cobertura (o ponto que decide a premissa) — **precisa de resposta de negócio**

As três varreduras leem **apenas as guias que aparecem na conta do PRESTADOR IMAG** no portal — não "todas as autorizações do beneficiário no convênio".

A pergunta decisiva: **a autorização desses convênios é emitida vinculada a um prestador executante específico, ou é genérica (o beneficiário escolhe onde usar)?**

- **Se vinculada ao prestador:** para o paciente fazer o exame **na IMAG**, a guia **precisa** apontar a IMAG como executante → ela **aparece** na nossa varredura. Nesse caso a visão-prestador **cobre** o universo relevante (tudo que é agendável na IMAG), e a premissa do gate se sustenta — inclusive o caso "autorizei direto no app", desde que tenha sido autorizado **para a IMAG**.
- **Se genérica:** uma autorização que o paciente obteve sem indicar a IMAG **não aparece** na nossa conta → o confronto falha e esses casos **continuam indo ao HITL**.

Ou seja: a varredura-prestador cobre exatamente **"autorizações executáveis na IMAG"**. Se o produto aceita que *só* faz sentido confrontar autorizações que já estão atreladas à IMAG (afinal, o agendamento é na IMAG), então **cobre**. Se o produto quer confrontar autorizações genéricas do beneficiário (que ele poderia depois direcionar à IMAG), **não cobre** — e não há como cobrir por varredura de prestador (precisaria de acesso à conta do BENEFICIÁRIO, que não temos).

**→ Decisão necessária (Pedro/negócio):** o confronto é sobre "autorização já atrelada à IMAG" (cobrimos) ou "qualquer autorização do beneficiário" (não cobrimos)?

### Q2 — Frescor
Varredura por **cron** (hoje diária; `cron_varredura.py`). Viável **intra-dia** (a cada poucas horas), **não** tempo-real: cada portal tem login lento (10–30s) + risco de WAF/rate-limit. ⚠️ O consumo **síncrono** (paciente no WhatsApp) **não pode** bater no portal ao vivo → **só a tabela materializada** serve, com limite de staleness + **fallback HITL** quando stale. Confirma a recomendação do handoff.

### Q3 — Chave de casamento
- **codigo_tuss por procedimento:** ❌ nenhuma lista traz — são nível-guia. Só via **drill-down** (Fase 2).
- **CPF/carteira:** Sassepe expõe **CPF**; SulAmérica **carteira**; **Unimed a lista não expõe nenhum dos dois** (casa por **nome+data** → risco de homônimo; melhora com drill-down ou com o cruzamento pelo protocolo que nós mesmos originamos).

### Q4 — Vigência/saldo
❌ Nenhuma varredura captura hoje. Exige **drill-down** (Fase 2). Sem isso o bot não distingue "aprovada e válida hoje" de "aprovada e expirada" — por isso a Fase 1 responde só presença de guia aprovada, não vigência.

### Q5 — Slugs
✅ Emito exatamente `unimed_recife` | `sassepe` | `sulamerica` (são os `NOME` dos adapters; idênticos aos do `hitl-resolver`). Sem risco de descasamento.

---

## Plano faseado

### Fase 1 — espelho NÍVEL-GUIA (escolhida; barata, ~pronta)
Materializa o que as `coletar()` já raspam. Responde: *"existe guia aprovada para esse beneficiário nesse convênio (nesta data)?"*.

**Divisão de trabalho:**
- **HOP/Lovable cria:**
  1. Tabela `autorizacao_status_portal` (DDL proposta abaixo).
  2. Edge function `receive-varredura-status` (HMAC, **espelho de `receive-autorizacao`**) que recebe as linhas da varredura e faz **upsert idempotente** (última leitura vence).
  3. RPC de upsert (ex. `fn_status_portal_upsert(p_linhas jsonb)`).
- **VPS/eu faço:**
  4. `cron_varredura.py` passa a **postar** as linhas de `coletar()` para `receive-varredura-status` (HMAC via `callback.py`, mesmo padrão). Nada de Postgres direto no VPS.
  5. Normalização de status para o enum estável (`aprovada|negada|em_analise|expirada|nao_encontrada|desconhecido`).

**DDL proposta (HOP cria; ajuste nomes/tipos):**
```sql
create table public.autorizacao_status_portal (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null,
  convenio_slug text not null,            -- unimed_recife|sassepe|sulamerica
  cpf text,                               -- Sassepe expõe; demais quando houver
  numero_carteira text,                   -- SulAmérica/Unimed quando houver
  paciente_nome text,                     -- fallback/auditoria (Unimed casa por nome)
  paciente_cadastro_id uuid,              -- resolvido quando possível (FK pacientes_cadastro)
  numero_guia text,                       -- protocolo/guia do portal
  status_portal text not null,            -- enum normalizado
  status_raw text,                        -- literal do portal (auditoria)
  data_guia date,                         -- emissão/solicitação
  -- Fase 2 (nulos na Fase 1; preenchidos no drill-down):
  codigo_tuss text,
  modalidade text,
  validade_inicio date,
  validade_fim date,
  quantidade_autorizada int,
  quantidade_utilizada int,
  senha text,
  -- rastreabilidade (importa p/ auditoria/M&A):
  fonte text not null,                    -- adapter/portal
  capturado_em timestamptz not null default now(),
  raw_ref text                            -- ponteiro p/ payload bruto (não a tabela quente)
);
-- upsert idempotente nível-guia (Fase 2 refina a chave p/ incluir codigo_tuss):
create unique index uq_status_portal_guia
  on public.autorizacao_status_portal
  (org_id, convenio_slug, coalesce(numero_guia,''),
   coalesce(cpf,''), coalesce(numero_carteira,''));
```

**Limitação assumida da Fase 1:** o bot consulta por `(cpf|carteira, convenio_slug)` e checa `status_portal='aprovada'`. **Não** filtra por `codigo_tuss` nem por vigência → serve para **descartar** com segurança (nenhuma guia aprovada = não autorizado → HITL/pré-atendimento) e para **sinalizar** presença de autorização; a confirmação fina (exame X vigente) fica para a Fase 2. Enquanto isso, "tem guia aprovada mas não sei se é do exame certo/vigente" pode continuar caindo no HITL — é o comportamento seguro.

### Fase 2 — drill-down por guia (cara; = trabalho do `verificar`)
Abrir cada guia AUTORIZADA → extrair `codigo_tuss[]`, `validade_inicio/fim`, `saldo`, `senha`, `modalidade`. **É o mesmo drill-down da ação `verificar` (Camada 3 do gate).** Recomendo **construir as duas juntas** — uma sondagem, uma extração, dois consumidores (o `verificar` pontual por senha + o espelho em massa).

---

## Dependências / próximos passos

1. **[negócio]** Responder Q1 (autorização atrelada ao prestador ou genérica?).
2. **[HOP/Lovable]** Criar tabela + `receive-varredura-status` + RPC de upsert.
3. **[VPS/eu]** `cron_varredura` posta as linhas + normalização de status.
4. **[Fase 2, conjunta]** Sondagem do drill-down (Unimed primeiro — credenciais já no `.env` da VPS) que serve `verificar` **e** a Fase 2 da tabela.

**Enquanto a tabela não estiver populada:** comportamento seguro atual — agendamento por convênio com exame que exige pré-autorização → **Pré-Atendimento/HITL**, sempre.
