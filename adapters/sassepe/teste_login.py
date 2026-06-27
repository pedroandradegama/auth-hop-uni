"""
teste_login.py (Sassepe) — testa SO' o login (MVOnePass + aceite LGPD + workspace).
Nao grava nada. Headless por padrao.
Execute: set -a && source .env && set +a && python adapters/sassepe/teste_login.py
Esperado: "LOGIN OK" + saida de /sso/login.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapters.sassepe import sessao


async def main():
    print(">> Sassepe: abrindo navegador e tentando login...\n")
    async with sessao.navegador() as page:
        try:
            await sessao.login(page)
        except Exception as e:
            print(f">>> ERRO durante o login: {e}")
            await page.wait_for_timeout(2000)
            return
        url = page.url
        print(f"URL apos login: {url}")
        print(f"Titulo: {await page.title()}\n")
        if "/sso/login" in url:
            print(">>> ATENCAO: ainda na tela de login — FALHOU.")
        else:
            print(">>> LOGIN OK: saimos da tela de /sso/login.")
        await page.wait_for_timeout(3000)


if __name__ == "__main__":
    asyncio.run(main())
