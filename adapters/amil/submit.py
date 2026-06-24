"""
adapters/amil/submit.py
Preenche e grava uma autorização prévia no portal Amil.

Fluxo confirmado via inspeção do portal real (22/06/2026):
  1. Navegar para /pedidos-autorizacao → clicar "Autorização prévia" no menu
  2. Digitar carteirinha/CPF → Consultar → selecionar beneficiário no select
  3. Preencher: tipo de atendimento, data pedido, indicação clínica
  4. Preencher médico (nome/CPF/conselho) e CBO-S
  5. Adicionar procedimentos via autocomplete → clicar Incluir (um a um)
  6. Upload de anexos via input#simple-upload
  7. Clicar Incluir final (.container-botao[touranchor='tour4Concluir'])
  8. Capturar protocolo (I3 — conservador)

Invariantes respeitados: I1 (hard stops), I2 (falha explícita),
I3 (protocolo conservador), I4 (evidências), I5/I6 (credenciais por env).
"""
import logging
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page

from . import config
from .sessao import abrir_sessao, _screenshot_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ponto de entrada (contrato com a espinha)
# ---------------------------------------------------------------------------
async def executar(job: dict) -> dict:
    evidencias: list[str] = []
    pw = browser = context = page = None
    try:
        pw, browser, context, page = await abrir_sessao(headless=True)
        return await _executar_submit(page, job, evidencias)
    except Exception as exc:
        logger.exception("Amil submit: exceção inesperada")
        if page:
            p = _screenshot_path("submit_excecao")
            await page.screenshot(path=p)
            evidencias.append(p)
        return {
            "status": "erro_submit",
            "numero_protocolo": None,
            "evidencias": evidencias,
            "mensagem": f"Exceção inesperada: {exc}",
        }
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------
async def _executar_submit(page: Page, job: dict, evidencias: list) -> dict:

    # --- I1: validar entradas ANTES de qualquer ação irreversível ----------
    carteirinha = (job.get("carteirinha") or "").strip()
    cpf         = (job.get("cpf") or "").strip()
    codigos     = job.get("codigos") or []
    arquivos    = job.get("arquivos") or []
    medico      = (job.get("medico") or "").strip()
    # Indicacao clinica: valor FIXO (decisao IMAG). Nao vem do HITL/job.
    indicacao   = config.INDICACAO_CLINICA_PADRAO
    data_pedido = (job.get("data_pedido") or datetime.now().strftime("%d/%m/%Y")).strip()

    if not carteirinha and not cpf:
        return _erro("Identificador ausente: nem carteirinha nem CPF.", evidencias)
    if not medico:
        return _erro("Médico solicitante ausente.", evidencias)
    if not codigos:
        return _erro("Nenhum código de procedimento informado.", evidencias)
    for arq in arquivos:
        if not Path(arq).exists():
            return _erro(f"Arquivo não encontrado: {arq}", evidencias)

    # --- 1. Navegar para autorização prévia --------------------------------
    await page.goto(config.URL_AUTORIZACAO, timeout=config.TIMEOUT_NAVEGACAO)
    await page.wait_for_load_state("networkidle")
    await _navegar_menu_autorizacao(page)
    p = _screenshot_path("01_tela_inicial")
    await page.screenshot(path=p); evidencias.append(p)

    # --- 2. Buscar beneficiário -------------------------------------------
    identificador = carteirinha if carteirinha else cpf
    res = await _buscar_beneficiario(page, identificador, evidencias)
    if res.get("erro"):
        return _erro(res["erro"], evidencias, page)

    # --- 3. Selecionar beneficiário no select (se há dependentes) ---------
    await _selecionar_beneficiario(page, carteirinha or cpf)

    # --- 4. Preencher tipo de atendimento ---------------------------------
    await _preencher_tipo_atendimento(page)
    p = _screenshot_path("02_tipo_atendimento")
    await page.screenshot(path=p); evidencias.append(p)

    # --- 5. Preencher data do pedido médico (obrigatório) -----------------
    await _preencher_angular(page, config.SEL_DATA_PEDIDO_MEDICO, data_pedido, "data pedido")

    # --- 6. Selecionar Caráter = Eletivo e RN = Não (padrão) --------------
    await _clicar_se_existir(page, config.SEL_CARATER_ELETIVO)
    await _clicar_se_existir(page, config.SEL_RN_NAO)

    # --- 7. Preencher indicação clínica (obrigatório) ---------------------
    await _preencher_angular(page, config.SEL_INDICACAO_CLINICA, indicacao, "indicação clínica")

    # --- 8. Preencher médico solicitante e CBO-S (obrigatório) -----------
    await _preencher_angular(page, config.SEL_CAMPO_MEDICO, medico, "médico")
    # CBO-S: valor FIXO do config (obrigatorio no portal; nao vem do HITL).
    cbo_s = (job.get("cbo_s") or config.CBO_S_PADRAO).strip()
    if cbo_s:
        await _preencher_angular(page, config.SEL_CAMPO_CBO_S, cbo_s, "CBO-S")

    p = _screenshot_path("03_dados_preenchidos")
    await page.screenshot(path=p); evidencias.append(p)

    # --- 9. Adicionar procedimentos (um a um) ----------------------------
    for idx, proc in enumerate(codigos):
        ok = await _adicionar_procedimento(page, proc, idx, evidencias)
        if not ok:
            return _erro(
                f"Hard stop (I1): falha ao adicionar procedimento {proc.get('codigo_tuss')}.",
                evidencias, page,
            )

    # --- I1: confirmar quantidade de procedimentos -----------------------
    # SEGURANCA: se NAO conseguimos confirmar a contagem (0 ou -1), ABORTAMOS.
    # Nao gravar sem evidencia de que os procedimentos entraram na lista.
    # (O seletor SEL_LISTA_PROCS e' palpite; se nao casar, melhor falhar do que
    #  gravar guia sem procedimento.)
    n_procs = await _contar_na_lista(page, config.SEL_LISTA_PROCS)
    if n_procs != len(codigos):
        return _erro(
            f"Hard stop (I1): nao confirmei {len(codigos)} proc(s) na lista "
            f"(contei {n_procs}). Abortando antes de gravar. "
            f"Se o portal adicionou os proc(s) mas o seletor SEL_LISTA_PROCS nao "
            f"casa, ajustar o seletor — NUNCA relaxar este gate.",
            evidencias, page,
        )

    # --- 10. Upload de anexos --------------------------------------------
    for arq in arquivos:
        ok = await _fazer_upload(page, arq, evidencias)
        if not ok:
            return _erro(f"Hard stop (I1): falha no upload: {arq}", evidencias, page)

    # --- I1: confirmar quantidade de anexos ------------------------------
    # SEGURANCA: mesma regra dos procedimentos. Pedido medico e' obrigatorio;
    # gravar sem confirmar o anexo = guia que sera' negada. Se nao confirmo, paro.
    n_anexos = await _contar_na_lista(page, config.SEL_LISTA_ANEXOS)
    if n_anexos != len(arquivos):
        return _erro(
            f"Hard stop (I1): nao confirmei {len(arquivos)} anexo(s) na lista "
            f"(contei {n_anexos}). Abortando antes de gravar. "
            f"Ajustar SEL_LISTA_ANEXOS se o upload ocorreu mas o seletor nao casa.",
            evidencias, page,
        )

    # --- Screenshot pré-gravar (I4 — evidência crítica) ------------------
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(500)
    p = _screenshot_path("04_pre_gravar")
    await page.screenshot(path=p); evidencias.append(p)

    # --- 11. GRAVAR — clicar botão Incluir final (irreversível) ----------
    # SEGURANCA: usar SOMENTE o botao final especifico. NAO cair para o
    # button.incluir generico (que tambem serve p/ adicionar procedimento) —
    # clicar o botao errado numa acao irreversivel viola I1. Se o botao final
    # nao existe, ABORTAMOS (a guia esta pronta; capturar manualmente e' melhor
    # que clicar no botao incerto).
    btn_final = await page.query_selector(config.SEL_BTN_INCLUIR_FINAL)
    if not btn_final:
        return _erro(
            "Hard stop (I1): botão de envio final (SEL_BTN_INCLUIR_FINAL) não "
            "encontrado. NÃO clico no botão genérico (ambíguo). Guia montada mas "
            "não gravada — revisar screenshot 04_pre_gravar e o seletor.",
            evidencias, page,
        )

    await btn_final.click()

    # Confirmar modal se aparecer
    try:
        await page.wait_for_selector(config.SEL_BTN_CONFIRMAR_MODAL, timeout=5_000)
        await page.click(config.SEL_BTN_CONFIRMAR_MODAL)
    except Exception:
        pass

    await page.wait_for_load_state("networkidle", timeout=config.TIMEOUT_NAVEGACAO)
    await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

    # --- Screenshot pós-gravar (I4 — obrigatório) ------------------------
    p = _screenshot_path("05_pos_gravar")
    await page.screenshot(path=p); evidencias.append(p)

    # --- 12. Capturar protocolo (I3 — conservador) -----------------------
    protocolo = await _capturar_protocolo(page)

    if protocolo:
        logger.info("Amil: protocolado → %s", protocolo)
        return {
            "status": "protocolado",
            "numero_protocolo": protocolo,
            "evidencias": evidencias,
            "mensagem": f"Autorização protocolada com sucesso. Pedido: {protocolo}",
        }
    else:
        logger.warning("Amil: protocolo não capturado — requer_captura_manual")
        return {
            "status": "protocolado",
            "numero_protocolo": None,
            "requer_captura_manual": True,
            "evidencias": evidencias,
            "mensagem": "Guia gravada mas protocolo não capturado automaticamente. Verifique o screenshot 05_pos_gravar.",
        }


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

async def _navegar_menu_autorizacao(page: Page) -> None:
    """Clica em 'Autorização prévia' no menu lateral se necessário."""
    if "pedidos-autorizacao" in page.url:
        return
    try:
        for link in await page.query_selector_all("a"):
            if (await link.inner_text()).strip() == config.TEXTO_MENU_AUTORIZACAO:
                await link.click()
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(config.TIMEOUT_ANGULAR)
                return
    except Exception as exc:
        logger.warning("Amil: _navegar_menu_autorizacao — %s", exc)


async def _buscar_beneficiario(page: Page, identificador: str, evidencias: list) -> dict:
    """Preenche carteirinha/CPF e clica Consultar."""
    try:
        campo = await page.wait_for_selector(config.SEL_CAMPO_BENEFICIARIO, timeout=config.TIMEOUT_ELEMENTO)
        await campo.click()
        await campo.fill("")
        await campo.type(identificador, delay=60)
        await page.wait_for_timeout(500)

        btn = await page.wait_for_selector(config.SEL_BTN_CONSULTAR_PAC, timeout=config.TIMEOUT_ELEMENTO)
        await btn.click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

        # Verificar erro
        erro_el = await page.query_selector(config.SEL_ERRO_BENEFICIARIO)
        if erro_el:
            msg = (await erro_el.inner_text()).strip()
            p = _screenshot_path("beneficiario_erro")
            await page.screenshot(path=p); evidencias.append(p)
            return {"erro": f"Beneficiário não encontrado ({identificador!r}): {msg}"}

        p = _screenshot_path("02_beneficiario_ok")
        await page.screenshot(path=p); evidencias.append(p)
        return {}
    except Exception as exc:
        p = _screenshot_path("beneficiario_excecao")
        await page.screenshot(path=p); evidencias.append(p)
        return {"erro": f"Erro ao buscar beneficiário: {exc}"}


async def _selecionar_beneficiario(page: Page, identificador: str) -> None:
    """Seleciona o beneficiário correto no <select#beneficiario> quando há dependentes."""
    try:
        sel = await page.query_selector(config.SEL_SELECT_BENEFICIARIO)
        if not sel:
            return
        opts = await sel.query_selector_all("option")
        for opt in opts:
            val = (await opt.get_attribute("value") or "")
            if identificador in val:
                await page.select_option(config.SEL_SELECT_BENEFICIARIO, value=val)
                await page.wait_for_timeout(config.TIMEOUT_ANGULAR)
                return
        # Fallback: segunda opção (primeira costuma ser placeholder/responsável)
        if len(opts) > 1:
            val = await opts[1].get_attribute("value")
            await page.select_option(config.SEL_SELECT_BENEFICIARIO, value=val)
            await page.wait_for_timeout(config.TIMEOUT_ANGULAR)
    except Exception as exc:
        logger.warning("Amil: _selecionar_beneficiario — %s", exc)


async def _preencher_tipo_atendimento(page: Page) -> None:
    """Preenche o autocomplete de tipo de atendimento via clique físico."""
    try:
        campo = await page.wait_for_selector(config.SEL_TIPO_ATENDIMENTO, timeout=config.TIMEOUT_ELEMENTO)
        val_atual = await campo.input_value()
        if val_atual:
            return  # já preenchido
        await campo.click()
        await campo.type(config.VALOR_TIPO_ATENDIMENTO[:7], delay=80)  # "CONSULT"
        await page.wait_for_timeout(config.TIMEOUT_AUTOCOMPLETE)
        opt = await page.query_selector(config.SEL_PROC_OPCAO)
        if opt:
            await opt.click()
        await page.wait_for_timeout(config.TIMEOUT_ANGULAR)
    except Exception as exc:
        logger.warning("Amil: tipo de atendimento — %s", exc)


async def _preencher_angular(page: Page, seletor: str, valor: str, nome: str) -> None:
    """Preenche campo Angular com clique real + type (compatível com ng-model)."""
    try:
        el = await page.wait_for_selector(seletor, timeout=config.TIMEOUT_ELEMENTO)
        await el.click()
        await el.fill("")
        await el.type(valor, delay=40)
        await page.wait_for_timeout(300)
    except Exception as exc:
        logger.warning("Amil: campo '%s' (%s) — %s", nome, seletor, exc)


async def _clicar_se_existir(page: Page, seletor: str) -> None:
    """Clica num elemento se ele existir e não estiver já selecionado."""
    try:
        el = await page.query_selector(seletor)
        if el and not await el.is_checked():
            await el.click()
            await page.wait_for_timeout(200)
    except Exception:
        pass


async def _adicionar_procedimento(page: Page, proc: dict, idx: int, evidencias: list) -> bool:
    """
    Digita código TUSS no autocomplete, seleciona primeira opção, clica Incluir.
    Retorna True se procedimento adicionado com sucesso.
    """
    codigo = proc.get("codigo_tuss", "")
    try:
        # Aguardar campo de busca
        campo = await page.wait_for_selector(config.SEL_CAMPO_PROC_BUSCA, timeout=config.TIMEOUT_ELEMENTO)
        await campo.scroll_into_view_if_needed()
        await campo.click()
        await campo.fill("")
        await campo.type(codigo, delay=80)
        await page.wait_for_timeout(config.TIMEOUT_AUTOCOMPLETE)

        # Selecionar primeira opção do dropdown
        opt = await page.wait_for_selector(config.SEL_PROC_OPCAO, timeout=config.TIMEOUT_AUTOCOMPLETE)
        await opt.click()
        await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

        # Clicar no botão Incluir (adiciona o procedimento à lista)
        btn = await page.wait_for_selector(config.SEL_BTN_INCLUIR, timeout=config.TIMEOUT_ELEMENTO)
        await btn.scroll_into_view_if_needed()
        await btn.click()
        await page.wait_for_timeout(config.TIMEOUT_ANGULAR)

        p = _screenshot_path(f"proc_{idx:02d}_{codigo}")
        await page.screenshot(path=p); evidencias.append(p)
        return True

    except Exception as exc:
        logger.error("Amil: erro ao adicionar proc %s — %s", codigo, exc)
        p = _screenshot_path(f"proc_{idx:02d}_erro")
        await page.screenshot(path=p); evidencias.append(p)
        return False


async def _contar_na_lista(page: Page, seletor: str) -> int:
    try:
        items = await page.query_selector_all(seletor)
        return len(items)
    except Exception:
        return -1


async def _fazer_upload(page: Page, caminho: str, evidencias: list) -> bool:
    """Upload de anexo via input#simple-upload. Aceita PDF, JPG, TIF, JPEG."""
    try:
        input_el = await page.wait_for_selector(config.SEL_INPUT_ANEXO, timeout=config.TIMEOUT_ELEMENTO)
        await input_el.set_input_files(caminho)
        await page.wait_for_timeout(config.TIMEOUT_ANGULAR)
        p = _screenshot_path(f"anexo_{Path(caminho).stem}")
        await page.screenshot(path=p); evidencias.append(p)
        return True
    except Exception as exc:
        logger.error("Amil: upload %s — %s", caminho, exc)
        return False


async def _capturar_protocolo(page: Page) -> str | None:
    """Extrai número do pedido da tela de confirmação. (I3 — conservador)"""
    for sel in (config.SEL_NUMERO_PROTOCOLO, config.SEL_PROTOCOLO_TOAST):
        try:
            el = await page.wait_for_selector(sel, timeout=8_000)
            texto = (await el.inner_text()).strip()
            nums = re.findall(r"\d{5,}", texto)
            if nums:
                return nums[0]
        except Exception:
            continue
    # Fallback: varrer o body por padrões de pedido/protocolo
    try:
        body = await page.inner_text("body")
        for pattern in (
            r"[Pp]edido[:\s#]*(\d{5,})",
            r"[Pp]rotocolo[:\s#]*(\d{5,})",
            r"\b(\d{9,})\b",
        ):
            m = re.search(pattern, body)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def _erro(msg: str, evidencias: list, page=None) -> dict:
    logger.error("Amil submit erro: %s", msg)
    return {
        "status": "erro_submit",
        "numero_protocolo": None,
        "evidencias": evidencias,
        "mensagem": msg,
    }
