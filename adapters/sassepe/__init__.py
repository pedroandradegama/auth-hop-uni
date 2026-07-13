# adapters/sassepe/__init__.py
# Expoe as DUAS funcoes do contrato com nomes canonicos (a espinha so' chama
# essas duas). Espelha adapters/unimed_recife/__init__.py do molde.
from urllib.parse import urlparse

from . import sessao                      # exposto p/ o runner abrir page fresh
from . import config
from .submit import executar as submit          # async submit(job: dict) -> dict
from .varredura import coletar                   # async coletar(janela_dias) -> list[dict]

NOME = "sassepe"
DOMINIO = urlparse(config.PORTAL_URL).netloc   # "sassepe.maida.health"
