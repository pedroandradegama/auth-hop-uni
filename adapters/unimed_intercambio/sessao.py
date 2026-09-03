"""sessao.py — Sessao do portal Unimed CONNECTA (Xvfb + chromium + contexto).

Portado de bot_connecta.py (validado 14/07/2026). Mecanica preservada:
- Xvfb SOMENTE em Linux (VPS sem monitor); Windows/Mac: no-op.
- chromium headless=False + anti-automation (o CONNECTA esconde o form em
  headless puro).
- Apos o login, o CONNECTA SEMPRE abre o modal 'Selecao de Contexto'; e' preciso
  setar o valor no <select> real e clicar 'Selecionar'.
"""
import contextlib
import sys

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from . import config

_display = None


def _garantir_display_virtual():
    """Xvfb SOMENTE em Linux (VPS sem monitor). Windows/Mac: no-op."""
    global _display
    if not sys.platform.startswith("linux"):
        return None
    if _display is None:
        from pyvirtualdisplay import Display
        _display = Display(visible=0, size=(1280, 900))
        _display.start()
    return _display


_JS_ERRO_CREDENCIAL = r"""() => {
  const vis = (e) => { const r = e.getBoundingClientRect();
                       return r.width > 0 && r.height > 0; };
  const norm = (t) => (t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
                        .replace(/\s+/g, ' ').trim().toLowerCase();
  const alvo = Array.from(document.querySelectorAll('body *'))
    .filter(vis)
    .find(e => e.children.length === 0 && /usuario e\/ou senha/.test(norm(e.textContent)));
  return alvo ? (alvo.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200) : null;
}"""


async def erro_credencial(page) -> str | None:
    """Texto do ALERTA de credencial rejeitada, se estiver na tela.

    Sem isso, credencial invalida se disfarcava de problema de portal: o modal
    de contexto nao aparecia (porque o login nao passou) e o erro reportado era
    'modal_nao_apareceu', mandando a investigacao para timeout/seletor. Nunca
    levanta."""
    try:
        return await page.evaluate(_JS_ERRO_CREDENCIAL)
    except Exception:
        return None


async def selecionar_contexto(page, nome_contexto: str) -> tuple:
    """Apos o login, o Connecta sempre abre o modal 'Selecao de Contexto'.
    E preciso setar o valor no <select> real (nao so clicar no item da lista
    renderizada) e clicar em 'Selecionar' em seguida."""
    try:
        await page.wait_for_selector("text=Seleção de Contexto", state="attached", timeout=8000)
    except PlaywrightTimeoutError:
        return False, "modal_nao_apareceu"

    try:
        try:
            await page.wait_for_function(
                """(nome) => {
                    const sels = Array.from(document.querySelectorAll('select'));
                    return sels.some(s => Array.from(s.options).some(o => o.text.includes(nome)));
                }""",
                arg=nome_contexto,
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            try:
                diag = await page.evaluate(
                    """() => {
                        const sels = Array.from(document.querySelectorAll('select'));
                        return sels.map(s => ({id: s.id, totalOpcoes: s.options.length, primeiras: Array.from(s.options).slice(0,3).map(o=>o.text)}));
                    }"""
                )
            except Exception:
                diag = "indisponivel"
            return False, f"select_nao_populou_20s | diagnostico_selects={diag}"

        ok = await page.evaluate(
            """(nome) => {
                const sels = Array.from(document.querySelectorAll('select'));
                for (const s of sels) {
                    const opt = Array.from(s.options).find(o => o.text.includes(nome));
                    if (opt) {
                        s.value = opt.value;
                        s.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }""",
            nome_contexto,
        )
        if not ok:
            return False, "falha_ao_setar_valor_no_select"

        await page.wait_for_timeout(500)

        clicou = await page.evaluate(
            """() => {
                const links = Array.from(document.querySelectorAll('a'));
                const link = links.find(a => a.textContent.trim().toLowerCase() === 'selecionar');
                if (link) { link.click(); return true; }
                return false;
            }"""
        )
        if not clicou:
            return False, "botao_selecionar_nao_encontrado"
    except Exception as e:
        return False, f"excecao_inesperada: {e}"

    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)

    if "ErroLogin" in page.url:
        return False, "caiu_em_ErroLogin_apos_clicar_Selecionar"
    return True, "ok"


async def login(page):
    """Login (user/senha via evaluate) + selecionar_contexto. Levanta
    RuntimeError se o contexto falhar (alto, nao silencioso)."""
    await page.goto(config.PORTAL_URL, wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass

    campo_user = page.get_by_label("Usuário").first
    campo_senha = page.get_by_label("Senha").first
    await campo_user.wait_for(state="attached", timeout=30000)
    await page.wait_for_timeout(2000)

    await campo_user.evaluate(
        "(el, v) => { el.value=v; el.dispatchEvent(new Event('input',{bubbles:true}));"
        " el.dispatchEvent(new Event('change',{bubbles:true})); }",
        config.unimed_conecta_user(),
    )
    await campo_senha.evaluate(
        "(el, v) => { el.value=v; el.dispatchEvent(new Event('input',{bubbles:true}));"
        " el.dispatchEvent(new Event('change',{bubbles:true})); }",
        config.unimed_conecta_pass(),
    )

    await page.get_by_role("button", name="entrar").first.evaluate("el => el.click()")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)

    # Credencial rejeitada tem que falhar com o motivo CERTO — senao o erro
    # vira 'modal_nao_apareceu' e a investigacao vai para timeout/seletor.
    alerta = await erro_credencial(page)
    if alerta:
        raise RuntimeError(
            "CONNECTA rejeitou a credencial (verificar UNIMED_CONECTA_USER/PASS "
            f"e se a conta nao foi bloqueada): {alerta}")

    ok, motivo = await selecionar_contexto(page, config.contexto_prestador())
    if not ok:
        raise RuntimeError(f"Falha ao selecionar contexto CONNECTA: {motivo}")


@contextlib.asynccontextmanager
async def navegador():
    """Context manager: Xvfb (Linux) + chromium headless=False + anti-automation.
    Entrega uma `page` e garante o fechamento."""
    _garantir_display_virtual()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=config.BROWSER_HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1600, "height": 1000},
                ignore_https_errors=True,
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
            )
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = await context.new_page()
            page.set_default_timeout(60000)
            yield page
        finally:
            with contextlib.suppress(Exception):
                await browser.close()
