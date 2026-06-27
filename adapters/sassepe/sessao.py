"""
adapters/sassepe/sessao.py — Sessao do portal Sassepe (Maida Health).

Espelha portal/sessao.py do Unimed: so' abre browser, autentica e escolhe o
workspace. Sem regra de negocio. login() e' usado tanto pelo submit quanto pela
varredura.

Login via SSO MVOnePass (mudou desde o piloto interativo):
  1. sassepe.maida.health/sso/login -> botao "Acessar com MVOnePass"
  2. redireciona p/ onepass.mv.com.br/login (e-mail + senha + "Start session")
  3. volta p/ o Sassepe -> escolha do card de workspace de prestadores
Em contexto Playwright limpo (sem profile persistente) o login SEMPRE acontece.
"""
import contextlib
from playwright.async_api import async_playwright

from . import config

_ONEPASS_HOST = "onepass.mv.com.br"


async def login(page):
    """Autentica no Sassepe via MVOnePass e escolhe o workspace.
    Falha alto se um passo essencial nao acontecer (nao silenciosa)."""
    await page.goto(config.PORTAL_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)

    # Passo 1 — botao "Acessar com MVOnePass" (na tela do Sassepe).
    if _ONEPASS_HOST not in page.url:
        try:
            await page.get_by_role(
                "button", name="Acessar com MVOnePass"
            ).click(timeout=15000)
        except Exception as e:
            raise RuntimeError(
                f"Botao 'Acessar com MVOnePass' nao encontrado/clicavel: {e}"
            )
        await page.wait_for_url(f"**{_ONEPASS_HOST}**", timeout=30000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)

    # Passo 2 — e-mail + senha + "Start session" (na tela do MVOnePass).
    email = page.locator('input[type="text"]').first
    senha = page.locator('input[type="password"]').first
    await email.wait_for(state="visible", timeout=20000)
    await email.fill(config.sassepe_user())
    await senha.fill(config.sassepe_pass())
    await page.wait_for_timeout(300)
    try:
        await page.get_by_role("button", name="Start session").click(timeout=15000)
    except Exception as e:
        raise RuntimeError(f"Botao 'Start session' nao clicavel no MVOnePass: {e}")

    # Passo 2.5 — aceite LGPD/Termos (so' na 1a vez da conta). Autorizado pelo
    # titular; e' aceite de CONTA (persiste no servidor MVOnePass).
    await page.wait_for_timeout(2500)
    if "/terms-accept" in page.url:
        await _aceitar_termos(page)

    # Passo 3 — volta para o Sassepe (sai do dominio do OnePass).
    try:
        await page.wait_for_url(
            lambda url: _ONEPASS_HOST not in url, timeout=30000
        )
    except Exception:
        raise RuntimeError(
            "Login MVOnePass nao retornou ao Sassepe (credencial invalida, "
            "MFA, aceite de termos pendente, ou erro de autenticacao)."
        )
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)

    await _escolher_workspace(page)


async def _aceitar_termos(page):
    """Marca 'I accept the Terms of Use and Privacy Policy' e confirma. O
    checkbox e' estilizado (oculto) — clica via .click() no DOM. Falha alto se
    nao achar (mudanca de layout)."""
    marcou = await page.evaluate(
        """() => {
          const cb = document.querySelector('input[type=checkbox]');
          if (cb) { cb.click(); return true; }
          return false;
        }"""
    )
    if not marcou:
        raise RuntimeError("Checkbox de aceite (LGPD) nao encontrado no terms-accept.")
    await page.wait_for_timeout(500)
    try:
        await page.get_by_role("button", name="Start session").click(timeout=15000)
    except Exception as e:
        raise RuntimeError(f"'Start session' (apos aceite) nao clicavel: {e}")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)


async def _escolher_workspace(page):
    """Escolhe o card de workspace de prestadores, se a tela aparecer.
    Ausencia do card nao e' erro (sessao pode ir direto ao painel)."""
    m1, m2 = config.WORKSPACE_MARCADORES
    coord = await page.evaluate(
        """([m1, m2]) => {
          const c = Array.from(document.querySelectorAll('div')).find(e => {
            const r = e.getBoundingClientRect();
            return r.width > 100 && r.width < 400 && r.height > 100 && r.height < 400
              && e.textContent.includes(m1) && e.textContent.includes(m2);
          });
          if (!c) return null;
          const r = c.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }""",
        [m1, m2],
    )
    if coord:
        await page.mouse.click(coord["cx"], coord["cy"])
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)


@contextlib.asynccontextmanager
async def navegador():
    """Context manager que entrega uma `page` ja' com browser/context montados
    (Chromium por padrao) e garante o fechamento. Viewport largo: a mecanica de
    coordenadas do _ui.py pressupoe o layout desktop validado no piloto."""
    async with async_playwright() as p:
        engine = getattr(p, config.BROWSER_ENGINE)
        browser = await engine.launch(headless=config.BROWSER_HEADLESS)
        try:
            context = await browser.new_context(
                viewport={"width": 1536, "height": 864}
            )
            page = await context.new_page()
            page.set_default_timeout(120000)
            yield page
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
