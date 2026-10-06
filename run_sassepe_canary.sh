#!/usr/bin/env bash
# Canario SASSEPE: uma reserva, mesmas credenciais do cron e mesmo lock global.
# So' executar depois de isolar no HOP um job SASSEPE conhecido no topo da fila.
set -euo pipefail

cd "$(dirname "$0")"
source venv/bin/activate
set -a; source .env; set +a

export MODO=cron
export DRENAR_MAX_JOBS=1
export SASSEPE_TELEMETRIA_DROPDOWN=true
export SASSEPE_TRACE_FALHAS=true

# O crontab de producao ja' usa este mesmo arquivo. Reutiliza-lo impede que uma
# rodada manual e o cron disputem o claim atomico do proximo job.
exec /usr/bin/flock -n /tmp/autorizador.lock python worker.py
