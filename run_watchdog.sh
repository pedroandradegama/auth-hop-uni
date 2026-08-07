#!/usr/bin/env bash
# run_watchdog.sh — reverte reservas expiradas (chama a edge watchdog-autorizacao).
# Molde do run_autorizador.sh. Cron sugerido: a cada 10 min.
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
set -a; source .env; set +a
exec python watchdog.py
