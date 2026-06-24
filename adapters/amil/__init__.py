# adapters/amil/__init__.py
# Expõe as DUAS funções do contrato com nomes canônicos.
from .submit import executar as submit       # async submit(job: dict) -> dict
from .varredura import coletar               # async coletar(janela_dias) -> list[dict]
NOME = "amil"
