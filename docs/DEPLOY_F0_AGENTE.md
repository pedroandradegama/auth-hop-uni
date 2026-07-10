# Deploy F0 — Agente Híbrido de Fallback

## Pré-requisitos
- VPS alcança `api.anthropic.com` (HTTPS). Testar:
  `curl -sS -o /dev/null -w "%{http_code}\n" https://api.anthropic.com/v1/models -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01"` → 200.
- `.env` da VPS com as envs do bloco "Agente hibrido de fallback (F0)" do `.env.example`.
  `ANTHROPIC_API_KEY` DEDICADA (custo isolado).
- `AGENTE_SUBMETER_HABILITADO=false` (F0). NÃO ligar sem validação do Pedro.

## Passos
1. `git pull` na VPS (`/opt/imag-autorizador`).
2. `venv/bin/pip install -r requirements.txt` (traz `anthropic`).
3. `venv/bin/python -c "from agente import AgenteFallback; print('ok')"` → `ok`.
4. `venv/bin/pip install -r requirements-dev.txt && venv/bin/python -m pytest tests/ -q` → tudo verde.
5. Deixar o cron atual rodar. Na PRIMEIRA falha real agent-elegível do Unimed,
   confirmar no HOP linha em `vw_rpa_agente_diario` com `custo_usd_medio` entre
   $0.05 e $0.35.

## Rollback
- `AGENTE_HABILITADO=false` no `.env` → volta 100% ao determinístico
  (FalhaDeterministica não-elegível vira `erro_submit`, como antes).

## Nota de risco (§6.1a + fluxo Unimed longo)
- A page fresh faz o agente re-navegar todo o fluxo de solicitação. Em Unimed
  (fluxo longo e stateful) isso pode estourar `AGENTE_MAX_PASSOS` antes de
  chegar à falha. Em F0 o desfecho esperado é `REQUER_HUMANO` de qualquer forma,
  então é aceitável — mas é o principal candidato a revisão em F1 (injeção de
  page vs. re-login). Observar `passos` e `custo_usd` na vw diária.

## Contrato HOP (validado 2026-07-10)
- `agent_trace` → edge `receive-autorizacao` (mesmo HMAC do `submit_result`)
  → `fn_rpa_agente_registrar({p_payload})` → tabela `rpa_agente_execucoes`.
- Todas as colunas da tabela (convenio, custo_usd, diagnostico, duracao_seg,
  etapa_fallback, job_id, motivo_fallback, org_id, passos, patch_sugerido,
  protocolo, status, tokens_*, trace) são preenchidas por
  `ResultadoAgente.para_agent_trace()`.
