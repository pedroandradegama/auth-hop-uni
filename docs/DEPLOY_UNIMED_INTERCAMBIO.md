# Deploy — Adapter Unimed Intercambio (CONNECTA)

## Pré-requisitos VPS
- Xvfb + xvfb-run (confirmados: `/usr/bin/Xvfb`, `/usr/bin/xvfb-run`).
- Chromium do Playwright (confirmado em `/root/.cache/ms-playwright/`).
- `venv/bin/pip install pyvirtualdisplay` (nova dep; já em requirements.txt).
- `.env`: `UNIMED_CONECTA_USER`, `UNIMED_CONECTA_PASS`, `CONTEXTO_PRESTADOR`.

## Passos (cron pausado, como no deploy do agente)
1. Pausar cron autorizador + backup do crontab.
2. `git pull --ff-only origin main`.
3. `venv/bin/pip install -r requirements.txt` (traz pyvirtualdisplay).
4. Smoke: `venv/bin/python -c "import worker; from adapters.unimed_intercambio import submit; print('ok')"`.
5. `venv/bin/pip install -r requirements-dev.txt && venv/bin/python -m pytest tests/ -q` (todos verdes).
6. Religar cron.

## Validação ao vivo (Fase 0 do adapter — antes de confiar em produção)
- Semear 1 job real de intercâmbio (carteirinha de OUTRA Unimed + `crm`) e drenar
  na mão: `MODO=cron venv/bin/python worker.py`.
- Confirmar no fluxo: contexto selecionado, beneficiário localizado, procedimento
  na tabela, alerta de **TRÂNSITO respondido "Sim"**, recibo lido,
  `numero_protocolo` = **Guia Operadora** (validar se é esse o canônico).
- Ajustar `codigos_unimed_intercambio.csv` com os exames reais de intercâmbio.

## Notas de engine
- Este adapter usa **chromium + headless=False + Xvfb** (via `pyvirtualdisplay`,
  só no Linux). Os demais adapters seguem firefox headless — intactos.
- O `worker.py` roda por cron; o `pyvirtualdisplay.Display` é iniciado dentro do
  `sessao.navegador()` só quando um job de intercâmbio é processado.

## Rollback
- `git reset --hard <hash_anterior>`. Não precisa remover `unimed_intercambio` de
  `_ADAPTERS`: sem job desse convênio, o adapter fica inerte.

## Fora deste deploy
- Roteamento por prefixo de carteirinha (HOP: `cfg_convenios` + regra → seta
  `convenio="unimed_intercambio"`).
- Costura A (FalhaDeterministica → agente) = Fase 2, após validação ao vivo.
