"""
teste_login_amil.py
Testa apenas o login no portal Amil. Headless. Nada é gravado.
Execute com: set -a && source .env && set +a && python teste_login_amil.py
Esperado: "LOGIN OK" no terminal + screenshot em evidencias/amil/
"""
import asyncio
import os
import sys

# Garante que o projeto raiz está no path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapters.amil.sessao import abrir_sessao


async def main():
    print("Amil: iniciando teste de login...")
    try:
        pw, browser, context, page = await abrir_sessao(headless=True)
        url_atual = page.url
        print(f"Amil: LOGIN OK — página atual: {url_atual}")
        await browser.close()
        await pw.stop()
    except RuntimeError as e:
        print(f"Amil: FALHA NO LOGIN — {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
