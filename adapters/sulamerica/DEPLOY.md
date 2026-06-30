# Deploy — adapter Sul America Saude

Portado do molde do colega (`junior-imag/sulamerica_bot.py`), adaptado ao
contrato da espinha (`submit` + `coletar`).

> **Estado:** submit completo (login -> carteirinha -> SP/SADT -> form -> proc ->
> anexo -> Validar -> Confirmar). **Pendente de sondagem ao vivo:** captura do
> numero de protocolo pos-Confirmar e a varredura de status (historico). Ate' la',
> o submit retorna `requer_captura_manual` no protocolo (I3) e `coletar()` = [].

## Variaveis de ambiente (.env da VPS)

```
SULAMERICA_CODIGO=<codigo do prestador>
SULAMERICA_USUARIO=master                  # default; troque se necessario
SULAMERICA_SENHA=<senha>
# opcionais (defaults no config.py):
# SULAMERICA_PORTAL_URL=https://saude.sulamericaseguros.com.br/prestador/login/?accessError=2
# SULAMERICA_BROWSER_ENGINE=firefox
```

## Dependencias

Engine **firefox** (mesma do Unimed). No venv do cron (`venv/`, sem ponto):

```
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install firefox
python -m playwright install-deps firefox   # libs do SO (root)
```

## Como roda

- **submit**: worker (cron `run_autorizador.sh`, 5 min) roteia
  `convenio:"sulamerica"` -> `adapters.sulamerica.submit`. Login (codigo+usuario+
  senha) -> Segurado/solicitacao -> carteirinha (20 digitos, 3-5-4-4-4, iframe) ->
  Eletivo -> SP/SADT -> formulario (guia, medico+CRM conselho 06/UF 26-PE,
  CBO 225125, data, carater eletivo, tecnica convencional) -> procedimentos
  (HARD STOP I1) -> anexos tipo 16 (HARD STOP I1) -> Validar -> Confirmar.
- **varredura**: registrada em `cron_varredura.py`, mas skeleton (retorna [])
  ate' o historico do portal ser mapeado.

## Identificador

Beneficiario por **carteirinha de 20 digitos** (formato 3-5-4-4-4). Diferente do
Sassepe (CPF). O `medico` vem como `"CRM NOME"` (o portal exige o numero do
conselho num campo e o nome noutro).

## Testes

```
python adapters/sulamerica/smoke_test.py     # offline (split carteirinha/medico, validar arquivo)
python adapters/sulamerica/teste_login.py    # login real (precisa .env)
python adapters/sulamerica/teste_submit.py   # ⚠️ submit real — gera autorizacao
```
