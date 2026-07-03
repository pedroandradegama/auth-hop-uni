"""adapters/hapvida/sessao.py — Sessão do Portal do Prestador Hapvida. navegador() + login()."""
import contextlib
import re

from playwright.async_api import async_playwright

from . import config


async def login(page):
    """Autentica no Portal do Prestador. Best-effort nos seletores do form (mapear no 1º run real).
    Falha alto se permanecer em /login."""
    await page.goto(config.PORTAL_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)

    try:
        # usuário: 1º input de texto/email; senha: input password
        user_in = page.locator('input[type="text"], input[type="email"], input:not([type])').first
        await user_in.wait_for(state="visible", timeout=20000)
        await user_in.fill(config.hapvida_user())
        await page.locator('input[type="password"]').first.fill(config.hapvida_pass())
        await page.wait_for_timeout(300)
        try:
            await page.get_by_role("button", name=re.compile("entrar|acessar|login|continuar", re.I)).first.click(timeout=8000)
        except Exception:
            await page.locator('button[type="submit"], form button').first.click(timeout=8000)
    except Exception as e:
        raise RuntimeError(f"Form de login não mapeado: {e}")

    # aguarda sair do /login
    try:
        await page.wait_for_url(lambda u: "/login" not in u, timeout=30000)
    except Exception:
        raise RuntimeError(f"Login Hapvida falhou (ainda em /login). URL: {page.url}")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)


@contextlib.asynccontextmanager
async def navegador():
    async with async_playwright() as p:
        engine = getattr(p, config.BROWSER_ENGINE)
        browser = await engine.launch(headless=config.BROWSER_HEADLESS)
        try:
            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
            page = await context.new_page()
            page.set_default_timeout(60000)
            yield page
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
