"""
teste_intercambio_manual.py — Validacao ISOLADA do adapter unimed_intercambio.

Chama submit.executar() DIRETO (sem HOP, sem fila), com dados de um paciente
real, para provar o fluxo do portal CONNECTA ponta-a-ponta antes de depender do
roteamento HOP.

⚠️  ATENCAO: ISTO ENVIA UMA SOLICITACAO REAL AO PORTAL (ato IRREVERSIVEL — gera
    guia de verdade). So' rodar com um caso real aprovado.

Pre-requisitos (VPS):
  - .env com UNIMED_CONECTA_USER / UNIMED_CONECTA_PASS / CONTEXTO_PRESTADOR.
  - chromium do Playwright + Xvfb (o adapter sobe display virtual sozinho no Linux).

Uso (na raiz do repo, com o venv):
  cd /opt/imag-autorizador
  set -a; source .env; set +a
  venv/bin/python teste_intercambio_manual.py

Sobrescrever dados via env (opcional):
  TESTE_CART=... TESTE_MEDICO="..." TESTE_CRM=... TESTE_TUSS=... venv/bin/python teste_intercambio_manual.py
"""
import asyncio
import importlib
import json
import os

# import via importlib p/ pegar o MODULO submit (o __init__ reexporta 'submit'
# como a FUNCAO executar; aqui queremos o modulo, p/ chamar executar()).
_submit = importlib.import_module("adapters.unimed_intercambio.submit")

JOB = {
    "carteirinha": os.environ.get("TESTE_CART", "08650004956229017"),
    "medico": os.environ.get("TESTE_MEDICO", "PEDRO ANDRADE GAMA"),
    "crm": os.environ.get("TESTE_CRM", "21798"),
    # 40901122 = US - Abdome total (validado no autocomplete do CONNECTA 2026-08-03).
    "codigos": [{"codigo_tuss": os.environ.get("TESTE_TUSS", "40901122"),
                 "quantidade": int(os.environ.get("TESTE_QTD", "1"))}],
}


async def main():
    print(">> JOB:", json.dumps(JOB, ensure_ascii=False), flush=True)
    resultado = await _submit.executar(JOB)
    print(">> RESULTADO:", json.dumps(resultado, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
