"""
smoke_test_amil.py
Testa imports e contrato do adapter Amil SEM rede, SEM credenciais reais.
Execute com: python smoke_test_amil.py
Deve dar tudo OK antes de qualquer teste com portal real.
"""
import asyncio
import inspect
import sys
import os

# Stub de credenciais para o smoke não explodir no os.environ["AMIL_USER"]
os.environ.setdefault("AMIL_USER", "smoke_user")
os.environ.setdefault("AMIL_PASS", "smoke_pass")

ERROS = []

def chk(desc: str, cond: bool):
    status = "OK  " if cond else "FAIL"
    print(f"  [{status}] {desc}")
    if not cond:
        ERROS.append(desc)

# 1. Import do pacote
try:
    import adapters.amil as adapter
    chk("import adapters.amil", True)
except Exception as e:
    chk(f"import adapters.amil — {e}", False)
    sys.exit(1)

# 2. Contrato: submit existe e é async
chk("adapter.submit existe", hasattr(adapter, "submit"))
chk("adapter.submit é coroutine", inspect.iscoroutinefunction(adapter.submit))

# 3. Contrato: coletar existe e é async
chk("adapter.coletar existe", hasattr(adapter, "coletar"))
chk("adapter.coletar é coroutine", inspect.iscoroutinefunction(adapter.coletar))

# 4. NOME definido
chk("adapter.NOME == 'amil'", getattr(adapter, "NOME", None) == "amil")

# 5. Config carrega sem erro
try:
    from adapters.amil import config
    chk("config importa OK", True)
    chk("config.URL_LOGIN definido", bool(config.URL_LOGIN))
    chk("config.STATUS_MAP tem 'validado'", "validado" in config.STATUS_MAP)
    chk("config.STATUS_MAP['validado'] == AUTORIZADO", config.STATUS_MAP["validado"] == "AUTORIZADO")
    chk("config.STATUS_MAP['não validado'] == NEGADO",  config.STATUS_MAP.get("não validado") == "NEGADO")
    chk("config.STATUS_MAP['em análise'] == EM_ANALISE", config.STATUS_MAP.get("em análise") == "EM_ANALISE")
    chk("config.STATUS_MAP['pendente de documentação'] == EM_ANALISE",
        config.STATUS_MAP.get("pendente de documentação") == "EM_ANALISE")
except Exception as e:
    chk(f"config — {e}", False)

# 6. _normalizar_status
try:
    from adapters.amil.varredura import _normalizar_status
    chk("_normalizar_status('Validado') → AUTORIZADO",     _normalizar_status("Validado")                  == "AUTORIZADO")
    chk("_normalizar_status('Não Validado') → NEGADO",     _normalizar_status("Não Validado")              == "NEGADO")
    chk("_normalizar_status('Cancelado') → NEGADO",        _normalizar_status("Cancelado")                 == "NEGADO")
    chk("_normalizar_status('Em Análise') → EM_ANALISE",   _normalizar_status("Em Análise")                == "EM_ANALISE")
    chk("_normalizar_status('Pendente de Documentação') → EM_ANALISE",
        _normalizar_status("Pendente de Documentação")     == "EM_ANALISE")
    chk("_normalizar_status('XYZ') → DESCONHECIDO",        _normalizar_status("XYZ")                       == "DESCONHECIDO")
except Exception as e:
    chk(f"_normalizar_status — {e}", False)

# 7. submit retorna erro_submit com job vazio (sem rede)
async def _teste_submit_vazio():
    try:
        resultado = await adapter.submit({})
        chk("submit({}) → status presente",           "status" in resultado)
        chk("submit({}) → status == erro_submit",     resultado.get("status") == "erro_submit")
        chk("submit({}) → numero_protocolo == None",  resultado.get("numero_protocolo") is None)
        chk("submit({}) → evidencias é lista",        isinstance(resultado.get("evidencias"), list))
    except Exception as e:
        chk(f"submit({{}}) — exceção inesperada: {e}", False)

asyncio.run(_teste_submit_vazio())

# Resultado final
print()
if ERROS:
    print(f"SMOKE FALHOU — {len(ERROS)} erro(s):")
    for e in ERROS:
        print(f"  • {e}")
    sys.exit(1)
else:
    print("SMOKE OK — adapter Amil passa em todos os checks offline.")
