# Deploy — Watchdog de reservas (loop-engineering §2.2, lado VPS)

Aciona periodicamente a edge `watchdog-autorizacao` p/ reverter reservas expiradas
(evita job preso em `em_execucao` para sempre). **A lógica vive no HOP**; a VPS só
dispara o gatilho por cron.

## Pré-requisitos
- `.env` da VPS com `HOP_WATCHDOG_URL` (URL da edge `watchdog-autorizacao`).
  Auth = `WORKER_INBOUND_SECRET` (já existe).

## Passos
1. `git pull` na VPS (`/opt/imag-autorizador`).
2. `chmod +x run_watchdog.sh` (já vem executável do git).
3. Teste manual: `set -a; source .env; set +a; venv/bin/python watchdog.py`
   → imprime `>> watchdog <status>: <corpo>`.
4. Adicionar ao crontab (a cada 10 min):
   ```
   */10 * * * * /opt/imag-autorizador/run_watchdog.sh >> /opt/imag-autorizador/logs/watchdog.log 2>&1
   ```

## Ordem com o HOP
- Seguro habilitar já (o watchdog atual reverte órfãos em `em_execucao`).
- **Ganho pleno** após o Codex entregar a **reserva com lease** (§2.2) + a lógica de
  `lease_expires_at < now()` → `pendente` com teto de `tentativas` e respeito ao I1
  (falha PÓS-submit nunca re-enfileira). Coordenar.

## Rollback
- Remover a linha do crontab. Sem efeito no submit/varredura.
