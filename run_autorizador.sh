#!/usr/bin/env bash
# run_autorizador.sh — modo CRON do submit: drena a fila e encerra.
# Molde do run_voz_diario.sh. Chamado pelo cron a cada 5 min.
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
set -a; source .env; set +a
export MODO=cron
exec python worker.py
