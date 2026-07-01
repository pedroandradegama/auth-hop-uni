#!/usr/bin/env bash
# run_demonstrativo.sh — modo CRON da coleta de demonstrativos: drena a fila e encerra.
# Espelha run_autorizador.sh. Chamado pelo cron (ex.: diário, ou no início do mês).
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
set -a; source .env; set +a
export MODO=cron
exec python worker_demonstrativo.py
