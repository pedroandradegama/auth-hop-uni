"""
teste_login.py (SulAmerica) — testa SO' o login. Nao grava nada. Headless.
Execute: set -a && source .env && set +a && python adapters/sulamerica/teste_login.py
Esperado: "LOGIN OK" + URL fora de /login.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapters.sulamerica import sessao


async def main():
    print(">> SulAmerica: abrindo navegador e tentando login...\n")
    async with sessao.navegador() as page:
        try:
            await sessao.login(page)
        except Exception as e:
            print(f">>> ERRO durante o login: {e}")
            return
        url = page.url
        print(f"URL apos login: {url}")
        print(f"Titulo: {await page.title()}\n")
        if "login" in url:
            print(">>> ATENCAO: ainda na tela de login — FALHOU.")
        else:
            print("LOGIN OK")


if __name__ == "__main__":
    asyncio.run(main())
