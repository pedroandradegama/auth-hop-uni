"""
adapters/amil/varredura.py
Consulta e raspa o status das guias no portal Amil.
Seletores confirmados em 22/06/2026 via inspeção do portal real.
"""
import logging
from datetime import datetime, timedelta

from playwright.async_api import Page

from . import config
from .sessao import abrir_sessao, _screenshot_path

logger = logging.getLogger(__name__)


async def coletar(janela_dias: int = 30) -> list[dict]:
    """
    Login → tela de autorização prévia → filtro personalizado → raspa tabela.
    Retorna lista de dicts com vocabulário normalizado.
    """
    pw = browser = context = page = None
    try:
        pw, browser, context, page = await abrir_sessao(headless=True)
        return await _raspar(page, janela_dias)
    except Exception as exc:
        logger.exception("Amil varredura: exceção — %s", exc)
        return []
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()


async def _raspar(page: Page, janela_dias: int) -> list[dict]:
    hoje   = datetime.now()
    inicio = hoje - timedelta(days=janela_dias)
    fmt    = "%d/%m/%Y"

    # --- Navegar para a tela de autorização prévia -------------------------
    await page.goto(config.URL_CONSULTA, timeout=config.TIMEOUT_NAVEGACAO)
    await page.wait_for_load_state("networkidle")

    # O portal redireciona para um comunicado — clicar no menu lateral
    await _navegar_para_autorizacao(page)

    # --- Selecionar período personalizado ----------------------------------
    await page.wait_for_selector(config.SEL_RADIO_PERSONALIZADO, timeout=config.TIMEOUT_ELEMENTO)
    await page.click(config.SEL_RADIO_PERSONALIZADO)
    await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

    # --- Preencher datas ---------------------------------------------------
    await _preencher_data(page, config.SEL_DATA_INICIAL, inicio.strftime(fmt))
    await _preencher_data(page, config.SEL_DATA_FINAL, hoje.strftime(fmt))

    # --- Garantir todos os status marcados --------------------------------
    for chk_sel in (
        config.SEL_CHK_AUTORIZADO,
        config.SEL_CHK_EM_ANALISE,
        config.SEL_CHK_NEGADO,
        config.SEL_CHK_PENDENTE_DOC,
        config.SEL_CHK_CANCELADO,
    ):
        try:
            chk = await page.query_selector(chk_sel)
            if chk and not await chk.is_checked():
                await chk.click()
        except Exception as exc:
            logger.warning("Amil varredura: checkbox %s — %s", chk_sel, exc)

    # --- Pesquisar --------------------------------------------------------
    await _clicar_btn_texto(page, "Pesquisar")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

    p = _screenshot_path("varredura_resultado")
    await page.screenshot(path=p)
    logger.info("Amil varredura: screenshot → %s", p)

    # --- Raspar todas as páginas -----------------------------------------
    guias = []
    pagina = 1
    while True:
        linhas = await page.query_selector_all(config.SEL_TABELA_LINHAS)
        logger.info("Amil varredura: pág %d — %d linhas", pagina, len(linhas))
        for linha in linhas:
            guia = await _extrair_linha(linha)
            if guia:
                guias.append(guia)

        # Próxima página
        btn_prox = await page.query_selector("button.proximo:not(.disabled), button[class*='next']:not([disabled])")
        if not btn_prox:
            break
        await btn_prox.click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(config.TIMEOUT_ANGULAR)
        pagina += 1

    logger.info("Amil varredura: total %d guias em %d página(s)", len(guias), pagina)
    return guias


async def _navegar_para_autorizacao(page: Page) -> None:
    """Clica em 'Autorização prévia' no menu lateral."""
    try:
        links = await page.query_selector_all("a")
        for link in links:
            texto = (await link.inner_text()).strip()
            if texto == config.TEXTO_MENU_AUTORIZACAO:
                await link.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(config.TIMEOUT_ANGULAR)
                return
    except Exception as exc:
        logger.warning("Amil: _navegar_para_autorizacao — %s", exc)


async def _preencher_data(page: Page, seletor: str, valor: str) -> None:
    """Preenche campo de data via Playwright (Angular input)."""
    try:
        el = await page.wait_for_selector(seletor, timeout=config.TIMEOUT_ELEMENTO)
        await el.triple_click()
        await el.type(valor, delay=50)
        await page.wait_for_timeout(300)
    except Exception as exc:
        logger.warning("Amil varredura: preencher data %s=%s — %s", seletor, valor, exc)


async def _clicar_btn_texto(page: Page, texto: str) -> None:
    """Clica em botão pelo texto exato."""
    buttons = await page.query_selector_all("button")
    for btn in buttons:
        t = (await btn.inner_text()).strip()
        if t == texto:
            await btn.click()
            return
    logger.warning("Amil: botão '%s' não encontrado", texto)


async def _extrair_linha(linha) -> dict | None:
    """Extrai uma guia de uma <tr>. Retorna None se inválida."""
    try:
        # Usar aria-label para localizar as colunas corretas
        async def col(aria: str) -> str:
            td = await linha.query_selector(f"td[aria-label='{aria}']")
            return (await td.inner_text()).strip() if td else ""

        # Fallback por índice quando aria-label não existir
        cols = await linha.query_selector_all("td")
        async def idx(i: int) -> str:
            try:
                return (await cols[i - 1].inner_text()).strip()
            except Exception:
                return ""

        data_solic    = await col("Data solicitação") or await idx(config.COL_DATA_SOLICITACAO)
        protocolo_ans = await col("Protocolo ANS")    or await idx(config.COL_PROTOCOLO_ANS)
        pedido        = await col("Pedido")            or await idx(config.COL_PEDIDO)
        senha         = await col("Senha")             or await idx(config.COL_SENHA)
        carteirinha   = await col("N° da carteirinha") or await idx(config.COL_CARTEIRINHA)
        data_aut      = await col("Data")              or await idx(config.COL_DATA_AUTORIZACAO)
        status_raw    = await col("Situação")          or await idx(config.COL_SITUACAO)
        beneficiario  = await col("Beneficiário")      or await idx(config.COL_BENEFICIARIO)

        # Número do pedido é o identificador principal
        numero_protocolo = pedido or protocolo_ans
        if not numero_protocolo:
            return None

        return {
            "numero_protocolo": numero_protocolo,    # pedido interno Amil
            "protocolo_ans":    protocolo_ans,        # protocolo ANS (longo)
            "status_portal":    _normalizar_status(status_raw),
            "status_raw":       status_raw,
            "paciente":         beneficiario,
            "carteirinha":      carteirinha,
            "data":             data_solic,
            "data_autorizacao": data_aut,
            "senha":            senha or None,        # senha de autorização
            "especialidade":    "",
            "medico":           "",
            "ts":               datetime.now().isoformat(),
        }
    except Exception as exc:
        logger.warning("Amil varredura: erro ao extrair linha — %s", exc)
        return None


def _normalizar_status(status_raw: str) -> str:
    """
    Mapeia rótulos REAIS do portal Amil para vocabulário normalizado.
    Confirmados: 'Validado', 'Em análise', 'Não validado',
                 'Pendente de documentação', 'Cancelado'
    """
    chave = status_raw.lower().strip()
    return config.STATUS_MAP.get(chave, "DESCONHECIDO")
