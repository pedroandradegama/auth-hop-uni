"""
teste_submit.py (SulAmerica) — ⚠️ SUBMIT REAL: preenche e CONFIRMA no portal,
gerando uma autorizacao de verdade. Use so' com dados reais e intencao de enviar.

Edite o JOB abaixo (carteirinha 20 digitos, medico 'CRM NOME', codigos, arquivos).
Execute: set -a && source .env && set +a && python adapters/sulamerica/teste_submit.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapters.sulamerica import submit

JOB = {
    "carteirinha": "12345678901234567890",
    "medico": "16188 NUBIA ROSA LOPES",
    "codigos": [{"codigo_tuss": "40901114", "nome": "USG MAMAS"}],
    "arquivos": ["/caminho/para/pedido.pdf"],
}


async def main():
    print(">> SulAmerica: SUBMIT REAL — isto grava no portal.\n")
    r = await submit.executar(JOB)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
