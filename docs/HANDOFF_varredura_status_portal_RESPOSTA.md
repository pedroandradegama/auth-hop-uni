# Handoff RESPOSTA — Varredura de status de autorização (tabela `autorizacao_status_portal`)

**De:** chat das varreduras/adapters (VPS `imag-autorizador`)
**Para:** chat do orquestrador (bot WhatsApp HOP)
**Responde:** "Handoff — Varredura sistemática de status de autorização (tabela unificada)" (2026-07-03)
**Decisão tomada com o Pedro:** começar pela **Fase 1** (nível-guia).
**Q1 resolvido (Pedro, 2026-07-03): Cenário A em 99% dos casos (default).** A autorização é atrelada ao prestador executante → a varredura-prestador IMAG **cobre** o universo agendável na IMAG. A premissa do gate se sustenta.

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

### Q1 — Cobertura — **RESOLVIDO: Cenário A (default)**

As três varreduras leem as guias da conta do **PRESTADOR IMAG**. Pedro confirmou: **em 99% dos casos a autorização é atrelada ao prestador executante (Cenário A)** — assumido como default.

Consequência: para o paciente fazer o exame **na IMAG**, a guia aponta a IMAG como executante → **aparece na varredura**. A visão-prestador **cobre** o universo relevante (tudo agendável na IMAG), inclusive o caso "autorizei direto no app" (desde que autorizado para a IMAG). A premissa do gate se sustenta.

**Ressalva do 1% (Cenário B):** autorizações genéricas que o beneficiário não direcionou à IMAG não aparecem → esses casos caem no comportamento seguro (HITL). Aceitável como cauda.

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

**Relação com `fat_verificacao_senha` (já existe):** o SQL revelou a tabela da Camada 3 — `fat_verificacao_senha` {senha, numero_carteira, convenio_id, guia_id, autorizacao_id, status, resultado(jsonb), veredito, tentativas, ...} + o circuit breaker `fat_verificacao_cb`. Ela é **job-orientada** (senhas que NÓS verificamos, ligadas a guias que originamos) — **não** é o espelho universal. O espelho (`fat_autorizacao_status_portal`) é **tabela nova e mais ampla** (toda guia da conta-prestador, originada por nós ou não). **Na Fase 2, o mesmo drill-down alimenta as duas** (o `resultado` do `verificar` e as colunas de vigência/TUSS do espelho).

**Convenções do HOP a seguir:** prefixo **`fat_`**; **`convenio_id` (uuid)** é a FK canônica — eu emito `convenio_slug` (o `NOME` do adapter) e o **HOP resolve slug→convenio_id** no upsert (via a tabela `convenios`). `paciente_cadastro_id` o HOP resolve por **cpf / numero_carteirinha_padrao / nome_normalizado** contra `pacientes_cadastro`.

**Divisão de trabalho:**
- **HOP/Lovable cria:**
  1. Tabela `fat_autorizacao_status_portal` (DDL abaixo).
  2. Edge function `receive-varredura-status` (HMAC, **espelho de `receive-autorizacao`**) — recebe as linhas, **resolve slug→convenio_id e cpf/carteira/nome→paciente_cadastro_id**, e faz **upsert idempotente** (última leitura vence).
  3. RPC `fn_status_portal_upsert(p_linhas jsonb)`.
- **VPS/eu faço:**
  4. `cron_varredura.py` passa a **postar** as linhas de `coletar()` para `receive-varredura-status` (HMAC via `callback.py`). Nada de Postgres direto no VPS.
  5. Normalização de status → enum estável. Na **Fase 1** as varreduras entregam `aprovada` (AUTORIZADO) | `negada` (NEGADO) | `em_analise` | `desconhecido`. `expirada` e `nao_encontrada` só na **Fase 2** (dependem de validade/drill-down).

**DDL proposta (HOP cria; ajuste nomes/tipos):**
```sql
create table public.fat_autorizacao_status_portal (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null,
  convenio_id uuid,                       -- resolvido pelo HOP a partir do slug
  convenio_slug text not null,            -- unimed_recife|sassepe|sulamerica (o que o VPS emite)
  cpf text,                               -- Sassepe expõe; demais quando houver
  numero_carteira text,                   -- SulAmérica/Unimed quando houver
  paciente_nome text,                     -- fallback/auditoria (Unimed casa por nome)
  paciente_cadastro_id uuid,              -- HOP resolve p/ cpf|numero_carteirinha_padrao|nome_normalizado
  numero_guia text,                       -- protocolo/guia do portal
  status_portal text not null,            -- aprovada|negada|em_analise|expirada|nao_encontrada|desconhecido
  status_raw text,                        -- literal do portal (auditoria)
  data_guia date,                         -- emissão/solicitação
  -- Fase 2 (nulos na Fase 1; preenchidos no drill-down = ação verificar):
  codigo_tuss text,
  modalidade text,
  validade_inicio date,
  validade_fim date,
  quantidade_autorizada int,
  quantidade_utilizada int,
  senha text,
  -- rastreabilidade (auditoria/M&A):
  fonte text not null,                    -- adapter/portal
  capturado_em timestamptz not null default now(),
  raw_ref text                            -- ponteiro p/ payload bruto (não a tabela quente)
);
-- upsert idempotente nível-guia (Fase 2 refina a chave p/ incluir codigo_tuss):
create unique index uq_fat_status_portal_guia
  on public.fat_autorizacao_status_portal
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
