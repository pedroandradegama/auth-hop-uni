"""
teste_login.py — Testa SO' o login no portal Unimed Recife.

Nao faz submit, nao grava nada, nao mexe em guia. Abre o navegador, tenta
logar com as credenciais do .env e diz se passou. E' o primeiro teste real
de browser — valida credenciais + acesso ao portal a partir desta maquina.

Uso (com o venv ativo):
    set -a && source .env && set +a
    BROWSER_HEADLESS=false python teste_login.py
"""
import asyncio
from portal import sessao


async def main():
    print(">> abrindo Firefox e tentando login...\n")
    async with sessao.navegador() as page:
        try:
            await sessao.login(page)
        except Exception as e:
            print(f">>> ERRO durante o login: {e}")
            print(">>> Provavel causa: credencial errada, portal fora do ar,")
            print("    ou o IP desta maquina nao esta liberado no portal.")
            await page.wait_for_timeout(3000)
            return

        url = page.url
        titulo = await page.title()
        ainda_tem_login = await page.locator('input[name="login"]').count()

        print(f"URL apos login: {url}")
        print(f"Titulo da pagina: {titulo}\n")

        if ainda_tem_login:
            print(">>> ATENCAO: o campo de login AINDA aparece na tela.")
            print("    O login provavelmente FALHOU (credencial ou IP bloqueado).")
        else:
            print(">>> LOGIN OK: o campo de login sumiu — entramos no portal.")

        # deixa a janela aberta 5s pra voce ver com seus olhos
        await page.wait_for_timeout(5000)


if __name__ == "__main__":
    asyncio.run(main())
