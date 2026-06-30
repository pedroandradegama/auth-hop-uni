"""
adapters/sulamerica/submit.py — Tempo 1 (SUBMIT) do adapter Sul America.

Portado do molde do colega (sulamerica_bot.autorizar), adaptado ao contrato da
espinha: executar(job) -> {status: protocolado|erro_submit, numero_protocolo,
evidencias, mensagem}. Diferencas chave vs molde:
  - I1 (hard stop antes do irreversivel): se QUALQUER procedimento ou anexo
    falhar, aborta ANTES de Validar/Confirmar (nada de guia parcial).
  - I3 (protocolo conservador): captura o numero real pos-Confirmar; se nao
    casar com seguranca, retorna requer_captura_manual (nunca inventa numero).
  - medico vem como "CRM NOME" (split em crm + nome).
  - carteirinha 20 digitos (3-5-4-4-4), identificador do beneficiario.

Fluxo do portal (validado no molde): login -> Segurado/solicitacao ->
carteirinha (iframe) -> Eletivo -> SP/SADT -> formulario (guia, medico, conselho,
CBO, data, carater, tecnica) -> procedimentos -> anexos -> Validar -> Confirmar.
"""
import random
import string
from datetime import datetime

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from . import config, sessao, _ui
from . import codigos as codigos_mod
from . import varredura


class SubmitAbortado(Exception):
    """Erro de regra/preenchimento — vira erro_submit, nunca guia parcial."""


def _numero_guia_aleatorio() -> str:
    """Numero da guia DO PRESTADOR (campo de entrada, nao e' o protocolo).
    Aleatorio de 12 digitos, como no molde."""
    return "".join(random.choices(string.digits, k=12))


# ── Navegacao ───────────────────────────────────────────────────────────────
async def _navegar_para_solicitacao(page):
    """Abre o menu 'Segurado' e entra na tela de solicitacao."""
    await page.wait_for_timeout(2000)
    try:
        await page.evaluate(
            """() => {
              const link = document.querySelector('a[data-label="Segurado"]');
              if (link) {
                link.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                link.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
              }
            }"""
        )
        await page.wait_for_timeout(1500)
    except Exception:
        pass
    # Tenta o link direto de solicitacao.
    try:
        link = page.locator("a[href*='solicitacao']").first
        await link.wait_for(timeout=8000)
        await link.click()
        await page.wait_for_timeout(3000)
        return
    except Exception:
        pass
    # Fallback: clica via JS.
    try:
        await page.evaluate(
            """() => {
              const a = Array.from(document.querySelectorAll('a'))
                .find(a => a.href && a.href.includes('solicitacao'));
              if (a) a.click();
            }"""
        )
        await page.wait_for_timeout(3000)
    except Exception:
        pass


# ── Carteirinha ──────────────────────────────────────────────────────────────
async def _preencher_carteirinha(page, partes, evidencias):
    """Preenche os 5 campos da carteirinha (no iframe) e confirma com 'Ok'."""
    await page.wait_for_timeout(2000)
    frame = await _ui.achar_frame(page, "#codigo-beneficiario-1")
    if frame is None:
        await _ui.snap(page, "erro_carteirinha", evidencias)
        raise SubmitAbortado("Campos da carteirinha nao encontrados (iframe).")

    for i, parte in enumerate(partes, start=1):
        campo = frame.locator(f"#codigo-beneficiario-{i}")
        await campo.wait_for(timeout=10000)
        await campo.fill(parte)
        await page.wait_for_timeout(200)

    for seletor in ("a.sas-form-submit span:text('Ok')", "a:has-text('Ok')",
                    "input[value='Ok']", "button:has-text('Ok')"):
        try:
            btn = frame.locator(seletor).first
            await btn.wait_for(timeout=3000)
            await btn.click()
            break
        except Exception:
            continue
    await page.wait_for_timeout(2000)


# ── Carater -> SP/SADT ───────────────────────────────────────────────────────
async def _selecionar_carater(page, evidencias):
    """Sempre 'Eletivo' e depois 'SP/SADT' (do bloco eletivo, nao urgencia)."""
    try:
        btn = page.locator("button:has-text('Eletivo')").first
        await btn.wait_for(timeout=10000)
        await btn.click()
        await page.wait_for_timeout(2000)
    except Exception as e:
        await _ui.snap(page, "erro_eletivo", evidencias)
        raise SubmitAbortado(f"Botao 'Eletivo' nao encontrado: {e}")

    try:
        btn = page.locator("#box-tipo #btn-sp-sadt, #box-tipo.tipo-criar #btn-sp-sadt")
        await btn.wait_for(timeout=8000)
        await btn.click()
        await page.wait_for_timeout(2000)
    except Exception as e:
        await _ui.snap(page, "erro_sadt", evidencias)
        raise SubmitAbortado(f"Botao 'SP/SADT' (eletivo) nao encontrado: {e}")


# ── Formulario (cabecalho) ───────────────────────────────────────────────────
async def _preencher_cabecalho(page, crm, nome, evidencias, guia_prestador):
    """Preenche o cabecalho do SP/SADT. Retorna o frame_alvo (do formulario).
    `guia_prestador` e' gerado pelo chamador e reusado na captura do protocolo
    (a Consulta casa o protocolo real por este numero)."""
    await page.wait_for_timeout(3000)
    campo_guia_sel = "input[name='solicitacao-sp-sadt.numero-guia-prestador']"
    frame = await _ui.achar_frame(page, campo_guia_sel)
    if frame is None:
        await _ui.snap(page, "erro_formulario", evidencias)
        raise SubmitAbortado("Formulario SP/SADT nao carregou (campo da guia).")

    # Numero da guia do prestador (campo de entrada; nao e' o protocolo, mas e'
    # a CHAVE que usamos depois para achar o protocolo real na Consulta).
    await frame.locator(campo_guia_sel).fill(guia_prestador)
    await page.wait_for_timeout(300)

    # Nome do profissional solicitante.
    await frame.locator(
        "input[name='solicitacao-sp-sadt.executante-solicitante.nome-profissional-solicitante']"
    ).fill(nome)
    await page.wait_for_timeout(300)

    # Conselho (06 = CRM) + UF (26 = PE).
    await frame.locator("#conselho-profissional").select_option(value=config.CONSELHO_SOLICITANTE)
    await page.wait_for_timeout(400)
    await frame.locator("#uf-conselho-profissional").select_option(value=config.UF_CONSELHO)
    await page.wait_for_timeout(400)

    # Numero do conselho (CRM).
    await frame.locator(
        "input[name='solicitacao-sp-sadt.executante-solicitante.conselho-profissional.numero']"
    ).fill(crm)
    await page.wait_for_timeout(300)

    # CBO (autocomplete por codigo).
    campo_cbo = frame.locator(
        "input[placeholder='Digite o código ou descrição do CBO'], "
        "input[alt='Código e descrição CBO']"
    ).first
    await campo_cbo.fill(config.CBO_SOLICITANTE)
    await page.wait_for_timeout(800)
    try:
        sugestao = frame.locator(
            f"li:has-text('{config.CBO_SOLICITANTE}'), .autocomplete-suggestion"
        ).first
        await sugestao.wait_for(timeout=4000)
        await sugestao.click()
    except Exception:
        await campo_cbo.press("Tab")
    await page.wait_for_timeout(500)

    # Data do atendimento (datepicker jQuery com mascara — digita char a char).
    hoje = datetime.now().strftime("%d/%m/%Y")
    campo_data = frame.locator("#data-atendimento")
    await campo_data.click()
    await campo_data.fill("")
    await page.wait_for_timeout(200)
    for ch in hoje:
        await campo_data.press(ch)
        await page.wait_for_timeout(50)
    await page.wait_for_timeout(300)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    valor = await campo_data.input_value()
    if not valor or "/" not in valor:
        await campo_data.evaluate(
            "(el, v) => { el.value = v; "
            "el.dispatchEvent(new Event('change', {bubbles: true})); "
            "el.dispatchEvent(new Event('blur', {bubbles: true})); }",
            hoje,
        )
        await page.wait_for_timeout(300)

    # Recem-nato (Nao), Carater (Eletivo), Tecnica (Convencional).
    await frame.locator("#recem-nato").select_option(value=config.RECEM_NATO)
    await page.wait_for_timeout(300)
    await frame.locator("#carater-atendimento").select_option(value=config.CARATER_ATENDIMENTO)
    await page.wait_for_timeout(300)
    await frame.locator(
        "select[name='solicitacao-sp-sadt.atendimento.tecnica-utilizada.codigo']"
    ).select_option(value=config.TECNICA_UTILIZADA)
    await page.wait_for_timeout(300)

    await _ui.snap(page, "cabecalho_preenchido", evidencias)
    return frame


# ── Procedimentos ────────────────────────────────────────────────────────────
async def _adicionar_procedimento(frame, page, codigo, quantidade=1):
    """Adiciona um codigo UMA vez (portal rejeita duplicado). qty>1 -> edita
    'Qt. Solic.' da linha. Retorna (ok, erro)."""
    try:
        campo = frame.locator("input[name='codigo-procedimento']")
        await campo.wait_for(timeout=8000)
        await campo.click()
        await campo.fill("")
        await page.wait_for_timeout(200)
        await campo.fill(codigo)
        await page.wait_for_timeout(500)
        await frame.locator("#btn-incluir-procedimento").click()
        await page.wait_for_timeout(1800)

        # Alerta de procedimento nao permitido.
        try:
            alerta = frame.locator("text=Não foi possível inserir esse procedimento")
            if await alerta.count() > 0:
                with_close = frame.locator(
                    "a:has-text('Fechar'), button:has-text('Fechar')"
                ).first
                await with_close.click()
                await page.wait_for_timeout(800)
                return False, (f"Codigo '{codigo}': nao permitido pela operadora "
                               "para este plano.")
        except Exception:
            pass

        if quantidade and int(quantidade) > 1:
            try:
                linha = frame.locator(f"tr:has-text('{codigo}')").last
                campo_qtd = linha.locator(
                    "input[type='text'], input[type='number']"
                ).first
                await campo_qtd.click()
                await campo_qtd.fill(str(int(quantidade)))
                await campo_qtd.press("Tab")
                await page.wait_for_timeout(800)
            except Exception as e:
                return False, f"Codigo '{codigo}': falha ao ajustar quantidade: {e}"
        return True, None
    except Exception as e:
        return False, f"Codigo '{codigo}': {e}"


# ── Anexos ───────────────────────────────────────────────────────────────────
async def _anexar(frame, page, arquivo, evidencias):
    """Faz upload de 1 arquivo (valida formato/nome), seleciona tipo de
    documento (16) e clica 'Anexar'. Retorna (ok, erro)."""
    valido, motivo = _ui.validar_arquivo(arquivo)
    if valido is None:
        return False, motivo
    try:
        file_input = frame.locator("input[type='file']").first
        await file_input.wait_for(timeout=8000)
        await file_input.set_input_files(valido)
        await page.wait_for_timeout(800)

        try:
            await frame.locator("#anexos-tipo-documento").select_option(
                value=config.TIPO_DOC_ANEXO
            )
            await page.wait_for_timeout(300)
        except Exception as e:
            return False, f"tipo de documento nao selecionado: {e}"

        btn = frame.locator(
            "button:has-text('Anexar'), input[value='Anexar']"
        ).first
        await btn.wait_for(timeout=5000)
        await btn.click()
        await page.wait_for_timeout(1500)
        return True, None
    except Exception as e:
        return False, f"falha ao anexar: {e}"


# ── Gravar (Validar -> Confirmar) ────────────────────────────────────────────
async def _gravar(frame, page, evidencias):
    """Validar Solicitacao -> Confirmar (IRREVERSIVEL)."""
    await _ui.snap(page, "pre_validar", evidencias)
    try:
        btn = frame.locator(
            "button:has-text('Validar Solicitação'), "
            "a:has-text('Validar Solicitação'), "
            "input[value*='Validar Solicitação']"
        ).first
        await btn.wait_for(timeout=8000)
        await btn.click()
        await page.wait_for_timeout(2500)
        await _ui.snap(page, "pos_validar", evidencias)
    except Exception as e:
        await _ui.snap(page, "erro_validar", evidencias)
        raise SubmitAbortado(f"Botao 'Validar Solicitacao' nao encontrado: {e}")

    try:
        btn = frame.locator(
            "button:has-text('Confirmar'), a:has-text('Confirmar'), "
            "input[value='Confirmar']"
        ).first
        await btn.wait_for(timeout=8000)
        await btn.click()
        await page.wait_for_timeout(2500)
        await _ui.snap(page, "pos_confirmar", evidencias)
    except Exception as e:
        await _ui.snap(page, "erro_confirmar", evidencias)
        raise SubmitAbortado(f"Botao 'Confirmar' final nao encontrado: {e}")


# ── Fluxo principal ───────────────────────────────────────────────────────────
async def executar(job: dict) -> dict:
    """Submit do SulAmerica a partir de um job validado. Retorna submit_result
    (sem job_id/idempotency_key, que o worker injeta)."""
    evidencias: list = []

    # Pre-flight em memoria (I1: antes de abrir browser) ----------------------
    try:
        partes = _ui.split_carteirinha(job.get("carteirinha") or "")
    except ValueError as e:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": str(e)}

    crm, nome = _ui.split_medico(job.get("medico") or "")
    if not nome:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Profissional solicitante (medico) ausente."}
    if not crm:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [],
                "mensagem": ("CRM do solicitante ausente: envie 'medico' como "
                             "'CRM NOME' (o portal exige o numero do conselho).")}

    codigos = [c for c in job.get("codigos", []) if (c.get("codigo_tuss") or "").strip()]
    if not codigos:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Nenhum codigo de procedimento informado."}

    arquivos = [a for a in job.get("arquivos", []) if a]
    if not arquivos:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Nenhum anexo (pedido medico) informado."}

    guia_prestador = _numero_guia_aleatorio()

    try:
        async with sessao.navegador() as page:
            await sessao.login(page)
            await _navegar_para_solicitacao(page)
            await _preencher_carteirinha(page, partes, evidencias)
            await _selecionar_carater(page, evidencias)
            frame = await _preencher_cabecalho(page, crm, nome, evidencias, guia_prestador)

            # Procedimentos — HARD STOP (I1): TODOS entram, senao aborta antes
            # de Validar/Confirmar (nada de guia parcial).
            for item in codigos:
                codigo_portal = codigos_mod.resolver_codigo_portal(item["codigo_tuss"])
                qty = int(item.get("quantidade") or item.get("qty") or 1)
                ok, erro = await _adicionar_procedimento(frame, page, codigo_portal, qty)
                if not ok:
                    await _ui.snap(page, "erro_procedimento", evidencias)
                    raise SubmitAbortado(f"Procedimento nao adicionado: {erro}")

            # Anexos — HARD STOP (I1): TODOS confirmam.
            for arquivo in arquivos:
                ok, erro = await _anexar(frame, page, arquivo, evidencias)
                if not ok:
                    await _ui.snap(page, "erro_anexo", evidencias)
                    raise SubmitAbortado(f"Anexo nao confirmado: {erro}")

            await _ui.snap(page, "pre_gravar", evidencias)
            await _gravar(frame, page, evidencias)

            # Captura conservadora do protocolo (I3): casa na Consulta pelo
            # numero do prestador que geramos (deterministico).
            return await _capturar_resultado(page, guia_prestador, evidencias)

    except SubmitAbortado as e:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": evidencias, "mensagem": str(e)}
    except PlaywrightTimeoutError as e:
        await _ui.snap(page, "timeout", evidencias) if "page" in dir() else None
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": evidencias, "mensagem": f"Tempo excedido: {e}"}
    except Exception as e:
        import traceback
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": evidencias,
                "mensagem": f"Erro inesperado: {e}",
                "detalhe": traceback.format_exc()}


async def _capturar_resultado(page, guia_prestador, evidencias):
    """Captura o protocolo pos-Confirmar pela Consulta, casando pelo numero do
    prestador (unico). Conservador (I3): sem match seguro -> captura manual."""
    await _ui.snap(page, "resultado_final", evidencias)
    protocolo = await varredura.buscar_guia_por_prestador(page, guia_prestador)
    if protocolo:
        return {"status": "protocolado", "numero_protocolo": protocolo,
                "evidencias": evidencias,
                "mensagem": "Solicitacao SulAmerica enviada e protocolo capturado "
                            f"(Nº Guia {protocolo}, guia prestador {guia_prestador})."}
    return {"status": "protocolado", "numero_protocolo": None,
            "requer_captura_manual": True, "evidencias": evidencias,
            "mensagem": ("Enviado (guia prestador "
                         f"{guia_prestador}), mas protocolo nao casado na Consulta. "
                         "Conferir pelo screenshot resultado_final / Consulta.")}
