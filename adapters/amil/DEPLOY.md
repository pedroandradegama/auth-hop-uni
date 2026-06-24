# Adapter Amil — Guia de Deploy

## 1. Estrutura de arquivos

```
adapters/amil/
├── __init__.py          ← expõe submit() e coletar()
├── config.py            ← URLs, seletores, mapa de status
├── sessao.py            ← login (SSO automático)
├── submit.py            ← nova autorização (fluxo completo)
├── varredura.py         ← consulta e raspagem de guias
├── smoke_test.py        ← 23 checks offline
├── teste_login.py       ← teste isolado de login
└── teste_varredura.py   ← teste isolado de varredura
```

## 2. Registrar no worker.py

```python
_ADAPTERS = {
    "unimed_recife": "adapters.unimed_recife",
    "amil":          "adapters.amil",   # ← adicionar
}
```

## 3. Credenciais no .env

```
AMIL_USER=seu_usuario
AMIL_PASS=sua_senha
```

## 4. Instalar dependências

```bash
pip install playwright --break-system-packages
playwright install chromium
```

## 5. Testar

```bash
# Smoke (sem rede)
PYTHONPATH=. AMIL_USER=x AMIL_PASS=x python adapters/amil/smoke_test.py

# Varredura (só leitura)
set -a && source .env && set +a
PYTHONPATH=. python adapters/amil/teste_varredura.py
```

## 6. Campos do job (submit)

| Campo              | Obrigatório | Descrição                              |
|--------------------|-------------|----------------------------------------|
| carteirinha        | *um dos dois| Número da carteirinha Amil             |
| cpf                | *um dos dois| CPF do beneficiário                    |
| medico             | ✓           | Nome ou CRM do médico solicitante      |
| cbo_s              | ✓           | Código CBO-S do médico (ex: 225125)    |
| indicacao_clinica  | ✓           | Indicação clínica do pedido            |
| data_pedido        | —           | dd/mm/aaaa (padrão: hoje)              |
| codigos            | ✓           | Lista de {codigo_tuss, quantidade}     |
| arquivos           | —           | Caminhos absolutos dos PDFs no servidor|

## 7. Status normalizados (varredura)

| Portal                    | Normalizado   |
|---------------------------|---------------|
| Validado                  | AUTORIZADO    |
| Não validado              | NEGADO        |
| Cancelado                 | NEGADO        |
| Em análise                | EM_ANALISE    |
| Pendente de documentação  | EM_ANALISE    |
