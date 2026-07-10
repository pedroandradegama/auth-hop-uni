# agente — loop de fallback do imag-autorizador (v0.1.0)
from .tipos import (FalhaDeterministica, MotivoFalha, MOTIVOS_AGENTE,
                    ResultadoAgente, ResultadoStatus)
from .loop import AgenteFallback
from .acoes import ContextoSeguranca
