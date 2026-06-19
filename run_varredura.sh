#!/usr/bin/env bash
# run_varredura.sh — varredura diaria (Tempo 2). Chamado pelo cron 1x/dia.
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
set -a; source .env; set +a
exec python cron_varredura.py
