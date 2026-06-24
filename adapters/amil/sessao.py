"""
adapters/amil/sessao.py
Login no portal Amil credenciado.
Portal Angular com sessão persistente via cookie.
Seletores confirmados em 22/06/2026.
"""
import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext

from . import config

logger = logging.getLogger(__name__)

EVIDENCIAS_DIR = Path("evidencias/amil")
EVIDENCIAS_DIR.mkdir(parents=True, exist_ok=True)


def _screenshot_path(nome: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(EVIDENCIAS_DIR / f"{ts}_{nome}.png")


async def abrir_sessao(headless: bool = True) -> tuple:
    """
    Inicia playwright, abre browser, faz login.
    Retorna (playwright, browser, context, page).
    Fechar é responsabilidade do chamador.
    """
    pw      = await async_playwright().start()
    browser = await pw.chromium.launch(headless=headless)
    context: BrowserContext = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
    )
    page: Page = await context.new_page()
    await _login(page)
    return pw, browser, context, page


async def _login(page: Page) -> None:
    """
    Navega para a URL de login e autentica.
    O portal redireciona para /home após login bem-sucedido.
    Lança RuntimeError se o login falhar.
    """
    logger.info("Amil: navegando para login → %s", config.URL_LOGIN)
    await page.goto(config.URL_LOGIN, timeout=config.TIMEOUT_NAVEGACAO)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

    url_atual = page.url
    logger.info("Amil: URL após navegar para login → %s", url_atual)

    # Portal com SSO ativo redireciona direto para /home — considera autenticado
    if "login" not in url_atual:
        logger.info("Amil: sessão SSO ativa — já autenticado → %s", url_atual)
        await page.screenshot(path=_screenshot_path("sessao_ativa"))
        return

    # Aguarda campos de login (Angular pode demorar)
    try:
        await page.wait_for_selector(config.SEL_LOGIN_USUARIO, timeout=config.TIMEOUT_ELEMENTO)
    except Exception:
        # Segunda tentativa: verificar se redirecionou durante a espera
        if "login" not in page.url:
            logger.info("Amil: redirecionado durante espera → %s", page.url)
            await page.screenshot(path=_screenshot_path("sessao_ativa"))
            return
        await page.screenshot(path=_screenshot_path("login_timeout"))
        raise RuntimeError(
            f"Amil: campos de login não apareceram e portal não redirecionou. URL: {page.url}"
        )

    # Preenche credenciais
    await page.fill(config.SEL_LOGIN_USUARIO, config.AMIL_USER)
    await page.fill(config.SEL_LOGIN_SENHA,   config.AMIL_PASS)
    await page.screenshot(path=_screenshot_path("login_preenchido"))

    # Clica em entrar
    await page.click(config.SEL_LOGIN_BTN)
    await page.wait_for_load_state("networkidle", timeout=config.TIMEOUT_NAVEGACAO)
    await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

    # Verifica erro de login
    erro = await page.query_selector(config.SEL_LOGIN_ERRO)
    if erro:
        msg = await erro.inner_text()
        await page.screenshot(path=_screenshot_path("login_erro"))
        raise RuntimeError(f"Amil: falha no login — {msg.strip()!r}")

    # Verifica se ainda está na página de login
    if "login" in page.url:
        await page.screenshot(path=_screenshot_path("login_falhou"))
        raise RuntimeError(f"Amil: login não redirecionou — URL atual: {page.url}")

    await page.screenshot(path=_screenshot_path("login_ok"))
    logger.info("Amil: login OK → %s", page.url)
