from urllib.parse import urlparse

from . import sessao                      # exposto p/ o runner abrir page fresh
from .submit import executar as submit
from .varredura import coletar
from .verificar import verificar          # async verificar(senha, numero_carteira) -> dict
import config

NOME = "unimed_recife"
DOMINIO = urlparse(config.PORTAL_URL).netloc   # "autorizador.unimedrecife.com.br"
