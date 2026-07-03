# adapters/sulamerica/__init__.py
# Expoe as DUAS funcoes do contrato com nomes canonicos (a espinha so' chama
# essas duas). Espelha adapters/sassepe/__init__.py do molde.
from .submit import executar as submit          # async submit(job: dict) -> dict
from .varredura import coletar                   # async coletar(janela_dias) -> list[dict]
from .demonstrativos import coletar_demonstrativos  # async (data_ini, data_fim) -> dict

NOME = "sulamerica"
