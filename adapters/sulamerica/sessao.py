"""
adapters/sulamerica/sessao.py — Sessao do portal Sul America Saude.

Espelha sassepe/sessao.py: so' abre browser e autentica. Sem regra de negocio.
login() e' usado tanto pelo submit quanto pela varredura.

Login classico (sem SSO): formulario com #code (codigo do prestador),
#user (usuario) e #senha, botao #entrarLogin. Apos logar, a home do prestador
aparece (menu lateral / link 'Segurado').
"""
import contextlib
from playwright.async_api import async_playwright

from . import config


async def _aceitar_cookies(page):
    """Fecha o banner de cookies se aparecer (best-effort)."""
    try:
        btn = page.locator(
            "button:has-text('Continuar'), button:has-text('Aceitar')"
        )
        await btn.first.wait_for(timeout=4000)
        await btn.first.click()
        await page.wait_for_timeout(500)
    except Exception:
        pass


async def login(page):
    """Autentica no portal SulAmerica. Falha alto se permanecer no /login."""
    await page.goto(config.PORTAL_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    await _aceitar_cookies(page)

    await page.fill("#code", config.sa_codigo())
    await page.fill("#user", config.sa_usuario())
    await page.fill("#senha", config.sa_senha())
    await page.click("#entrarLogin")

    # Aguarda elemento da home (mais confiavel que networkidle).
    try:
        await page.wait_for_selector(
            "a[data-label='Segurado'], .nacbgmenu, #LumNav", timeout=25000
        )
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    if "login" in page.url:
        raise RuntimeError(
            f"Falha no login SulAmerica (credencial invalida ou portal mudou). "
            f"URL: {page.url}"
        )


@contextlib.asynccontextmanager
async def navegador():
    """Context manager que entrega uma `page` (Firefox por padrao) e garante o
    fechamento. Viewport 1920x1080 (layout desktop validado no molde)."""
    async with async_playwright() as p:
        engine = getattr(p, config.BROWSER_ENGINE)
        browser = await engine.launch(headless=config.BROWSER_HEADLESS)
        try:
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()
            page.set_default_timeout(60000)
            yield page
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
