# Deploy — adapter Sassepe (Maida Health)

Validado ponta a ponta no portal real (envio real gerou a guia 1189780).

## Variaveis de ambiente (.env da VPS)

```
SASSEPE_USER=<CPF do usuario MVOnePass>     # NAO e' email — e' CPF
SASSEPE_PASS=<senha do MVOnePass>
# opcionais (defaults no config.py):
# SASSEPE_PORTAL_URL=https://sassepe.maida.health/sso/login
# SASSEPE_BROWSER_ENGINE=chromium
```

## Dependencias

Engine **chromium** (Unimed usa firefox). Instalar no venv do cron (`venv/`,
sem ponto):

```
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m playwright install-deps chromium   # libs do SO (root)
```

## Como roda

- **submit**: worker (cron `run_autorizador.sh`, 5 min) roteia `convenio:"sassepe"`
  -> `adapters.sassepe.submit`. Login MVOnePass (CPF+senha) + aceite LGPD ->
  SP/SADT -> CPF -> campos fixos + solicitante (do job) + CBO (2 secoes) ->
  exames (Tabela 22) -> anexo (tipo doc 03) -> Proximo -> resumo -> Enviar ->
  protocolo capturado no Historico por CPF+data (I3).
- **varredura**: `cron_varredura.py` (cron `run_varredura.sh`, diario) raspa o
  Historico de solicitacoes, normaliza status. CRON_CONVENIOS limita quais rodam.

## Testes

```
python adapters/sassepe/smoke_test.py                 # offline
set -a && source .env && set +a
python adapters/sassepe/teste_login.py                # login real (so' loga)
python adapters/sassepe/teste_submit.py               # ⚠️ GERA GUIA REAL
```

## Notas

- Identificador = **CPF** (Sassepe nao tem carteirinha). Exigiu `cpf` no schema.
- Solicitante (`medico` do job): formato "NUM NOME" ou "NUM - NOME" (busca pelo
  numero, casa pelo nome — metodo do piloto); so' nome cai no fallback.
- Profissional executante fixo: 21798 - PEDRO ANDRADE GAMA DE OLIVEIRA.
