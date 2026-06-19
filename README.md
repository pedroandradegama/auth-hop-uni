# imag-autorizador — Adapter Unimed Recife (HOP)

Refatoracao do zip `junior-imag-main` no **adapter Unimed** do Authorization
Gateway do HOP. **Nao foi reescrito do zero** — o conhecimento de portal do
`unimed_bot.py` original foi preservado e evoluido.

## Origem de cada modulo (rastreabilidade)

| Modulo | Origem | O que mudou |
|---|---|---|
| `portal/sessao.py` | `unimed_bot.py` (`login`, `fechar_popup`, launch) | Extraido para ser compartilhado por submit e varredura. |
| `portal/submit.py` | `unimed_bot.py` (`autorizar`, `adicionar_procedimento`, `_split_carteirinha`) | + captura de protocolo (1.1) + hard stops (1.2). |
| `portal/varredura.py` | **novo** | Reusa `sessao.login()`. Seletores a mapear (TODO). |
| `config.py` | valores magicos do `unimed_bot.py` | Externalizados; credenciais sem default. |
| `worker.py` | `app.py` (reescrito → POLLER) | Loop POLL: puxa job, processa, callback. |
| `callback.py` | **novo** | POST HMAC para a Edge Function. |
| `cron_varredura.py` | **novo** | Entry point do cron diario. |
| `codigos_unimed.csv` | mantido | — |

Aposentados: `index.html`, `railway.toml`, `install.bat`, `start.bat`,
`Dockerfile` (Railway), `.env.example` com senha real.

## Pendencias antes de produzir (marcadas como TODO no codigo)

1. **`submit._extrair_protocolo`** — secao 5 do contrato. Confirmar se o portal
   exibe o numero de protocolo na tela pos-gravar e fixar o seletor real. Hoje
   tenta heuristicas e devolve `requer_captura_manual` se nao achar (nunca inventa).
2. **`varredura.coletar`** — mapear os seletores da tela "Consultar Solicitacoes"
   (mesma engenharia reversa ja feita para o submit) e os rotulos reais de status.

## Rodar local (validacao)

```bash
python -m playwright install firefox
pip install -r requirements.txt
cp .env.example .env   # preencher
python smoke_test.py      # 9/9 — valida tudo que da' offline
python teste_login.py     # login real no portal (precisa de credencial)
python teste_callback.py  # caminho de volta (HMAC), sem rede
python worker.py          # inicia o POLLER (puxa jobs de proximo-job-autorizacao)
```

## Modelo de execucao: POLL

O worker NAO expoe endpoint. Ele PUXA o proximo job de
`proximo-job-autorizacao` (Bearer `WORKER_INBOUND_SECRET`), processa um por vez
(serializa o browser), e posta o resultado em `receive-autorizacao` (HMAC). A
porta da VPS fica fechada ao mundo — o HOP nunca alcanca o worker.

## Deploy (VPS oficial)

PM2 em `/opt/imag-autorizador/`, dois processos longos:
- `worker.py` — poller do submit (Tempo 1).
- `cron_varredura.py` — varredura diaria (Tempo 2):

```
0 7 * * * cd /opt/imag-autorizador && /usr/bin/python3 cron_varredura.py >> logs/varredura.log 2>&1
```

Worker e cron **nunca** tocam o Postgres — so' puxam de `proximo-job-autorizacao`
e postam para `receive-autorizacao` com HMAC.
