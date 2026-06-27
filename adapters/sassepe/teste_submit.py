"""
teste_submit.py (Sassepe) — ensaio REAL do submit. ⚠️ GERA GUIA REAL no portal
de producao. Nao rodar a' toa (duplicatas). Usa arquivo local (nao baixa do HOP).
Execute: set -a && source .env && set +a && python adapters/sassepe/teste_submit.py
"""
import asyncio
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# __init__ sombreia o nome 'submit' (alias de executar); pega o MODULO real.
submit = importlib.import_module("adapters.sassepe.submit")

JOB = {
    "cpf": "64387720468",
    "medico": "25245 PRISCILLA CARDOSO LAMEIRA ANDRADE",
    "paciente_nome": "AUREA BARBOSA DA SILVA FISCHLER",
    "codigos": [{"codigo_tuss": "40808041", "sub_tipo": "RM",
                 "nome": "MAMOGRAFIA DIGITAL", "quantidade": 1}],
    "arquivos": ["/Users/pedro/Documents/MetaAds/Solicitações/Solicitacao 01.png"],
}


async def main():
    res = await submit.executar(JOB)
    print("\n=== RESULTADO ===")
    print(json.dumps({k: v for k, v in res.items() if k != "detalhe"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
