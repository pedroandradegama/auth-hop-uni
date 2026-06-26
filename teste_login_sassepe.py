"""
teste_login_sassepe.py — Testa SO' o login no portal Sassepe.

Nao faz submit, nao grava nada. Abre o navegador, tenta logar (2 passos + escolha
de workspace) com as credenciais do .env e diz se passou. Primeiro teste real de
browser do adapter Sassepe — valida credenciais + acesso a partir desta maquina.

Uso (com o venv ativo e o playwright instalado):
    set -a && source .env && set +a
    BROWSER_HEADLESS=false python teste_login_sassepe.py
"""
import asyncio
from adapters.sassepe import sessao


async def main():
    print(">> abrindo navegador e tentando login no Sassepe...\n")
    async with sessao.navegador() as page:
        try:
            await sessao.login(page)
        except Exception as e:
            print(f">>> ERRO durante o login: {e}")
            print(">>> Provavel causa: credencial errada, portal fora do ar,")
            print("    layout de login mudou, ou MFA exigido.")
            await page.wait_for_timeout(3000)
            return

        url = page.url
        titulo = await page.title()
        ainda_login = "/sso/login" in url

        print(f"URL apos login: {url}")
        print(f"Titulo da pagina: {titulo}\n")
        if ainda_login:
            print(">>> ATENCAO: ainda na tela de login — login provavelmente FALHOU.")
        else:
            print(">>> LOGIN OK: saimos da tela de /sso/login.")
        await page.wait_for_timeout(5000)


if __name__ == "__main__":
    asyncio.run(main())
