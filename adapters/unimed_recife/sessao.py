"""
portal/sessao.py — Camada compartilhada de sessao do portal Unimed Recife.

Extraido diretamente do unimed_bot.py original. login() e fechar_popup() sao
usados TANTO pelo submit QUANTO pela varredura — por isso vivem aqui, isolados.
Nao contem regra de negocio; so abre browser, fecha popup e autentica.
"""
import contextlib
from playwright.async_api import async_playwright

import config


async def fechar_popup(page):
    """Fecha o popup/dialog inicial do portal, se existir. Silencioso de
    proposito: a ausencia do popup nao e' erro."""
    try:
        btn = page.locator(
            'xpath=//*[@id="dialog"]/div/div/div/table/tbody/tr[1]/td/a'
        )
        await btn.wait_for(timeout=3000)
        await btn.click()
        await page.wait_for_timeout(800)
    except Exception:
        pass


async def login(page):
    """Autentica no portal. Levanta excecao se os campos de login nao
    aparecerem (falha alto, nao silenciosa)."""
    await page.goto(config.PORTAL_URL, wait_until="domcontentloaded")
    await fechar_popup(page)

    await page.fill('input[name="login"]', config.unimed_user())
    await page.fill('#senha', config.unimed_pass())
    await page.click('input[name="Acessar"]')
    await page.wait_for_load_state("domcontentloaded")
    await fechar_popup(page)


@contextlib.asynccontextmanager
async def navegador():
    """Context manager que entrega uma `page` ja com browser/context montados
    e garante o fechamento. Uso:

        async with navegador() as page:
            await login(page)
            ...
    """
    async with async_playwright() as p:
        engine = getattr(p, config.BROWSER_ENGINE)
        browser = await engine.launch(headless=config.BROWSER_HEADLESS)
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()
            page.set_default_timeout(120000)
            yield page
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
