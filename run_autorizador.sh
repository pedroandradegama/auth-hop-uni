#!/usr/bin/env bash
# run_autorizador.sh — modo CRON do submit: drena a fila e encerra.
# Molde do run_voz_diario.sh. Chamado pelo cron a cada 5 min.
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate
set -a; source .env; set +a
export MODO=cron

# Canario investigado: usa EXATAMENTE o mesmo caminho do cron (incluindo .env),
# mas limita a uma reserva e habilita a instrumentacao SASSEPE. So' use depois
# de o HOP deixar um job SASSEPE conhecido no topo da fila: o claim e' generico.
if [[ "${CANARIO_SASSEPE_DIAG:-false}" == "true" ]]; then
  export DRENAR_MAX_JOBS=1
  export SASSEPE_TELEMETRIA_DROPDOWN=true
  export SASSEPE_TRACE_FALHAS=true
fi

# O cron e uma execucao manual nao podem disputar o proximo lease. Recusar a
# segunda execucao e' melhor que processar dois jobs em paralelo.
command -v flock >/dev/null || { echo "flock nao encontrado; recusando iniciar sem lock" >&2; exit 1; }
lock_file="${AUTORIZADOR_LOCK_FILE:-$PWD/.autorizador.lock}"
exec 9>"$lock_file"
if ! flock -n 9; then
  echo "autorizador ja esta em execucao; saindo sem buscar job" >&2
  exit 0
fi
exec python worker.py
