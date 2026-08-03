# adapters/unimed_intercambio/__init__.py
# Adapter do portal Unimed CONNECTA (intercambio). Molde dos demais.
from . import sessao                      # exposto p/ o runner (page fresh do agente)
from . import config
from .submit import executar as submit          # async submit(job: dict) -> dict

NOME = "unimed_intercambio"
DOMINIO = config.DOMINIO                        # "remote.unimedrecife.com.br:444"
