"""
portal/submit.py — Tempo 1 do processo: SUBMIT (Gerar Solicitacao).

Descendente direto do autorizar() do unimed_bot.py original. Preserva todo o
conhecimento de portal (seletores, ordem dos campos, upload via iframe) e
adiciona as duas cirurgias do contrato de handoff:

  1.1  Captura do numero_protocolo como DADO ESTRUTURADO apos o gravar
       (chave de join com a varredura).
  1.2  gravar BLINDADO por pre-condicoes duras: beneficiario encontrado,
       TODOS os codigos adicionados, TODOS os anexos confirmados. Qualquer
       invariante que falha -> erro_submit, e o gravar NAO acontece.

Resultado: dict pronto para virar payload de callback (submit_result).
"""
import os
from datetime import datetime, date
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

import config
import codigos as codigos_mod
from . import sessao, varredura


class SubmitAbortado(Exception):
    """Pre-condicao dura falhou. O gravar NAO deve acontecer."""


# ── Carteirinha ───────────────────────────────────────────────────────────
def split_carteirinha(carteirinha: str):
    """Normaliza e quebra a carteirinha nos 3 campos do portal.
    Logica preservada do original (tratamento 15/16/17 digitos)."""
    apenas_numeros = "".join(filter(str.isdigit, carteirinha))
    total = len(apenas_numeros)

    if total < 16:
        raise SubmitAbortado(
            f"Carteirinha invalida: '{carteirinha}' tem {total} digitos "
            "(esperado 16). Se tiver 15, adicione um zero a' frente."
        )
    if total == 16:
        dezesseis = apenas_numeros
    elif total == 17:
        dezesseis = apenas_numeros[1:]
    else:
        raise SubmitAbortado(
            f"Carteirinha invalida: '{carteirinha}' tem {total} digitos "
            "(maximo 17)."
        )

    return dezesseis[0:3], dezesseis[3:15], dezesseis[15]


# ── Evidencia ──────────────────────────────────────────────────────────────
async def _snap(page, etapa: str, evidencias: list) -> str:
    os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"{etapa}_{ts}.png"
    caminho = os.path.join(config.SCREENSHOTS_DIR, nome)
    await page.screenshot(path=caminho, full_page=True)
    evidencias.append({"etapa": etapa, "screenshot_path": caminho,
                       "ts": datetime.now().isoformat()})
    return caminho


# ── Procedimentos ───────────────────────────────────────────────────────────
async def _adicionar_procedimento(page, codigo: str, sub_tipo: str):
    """Adiciona UM procedimento. Retorna (ok, erro)."""
    valor_sub = config.SUBTIPO_VALUE.get(sub_tipo.upper())
    if valor_sub is None:
        return False, f"Sub-tipo desconhecido '{sub_tipo}' para o codigo {codigo}."

    try:
        await page.select_option('select[name="subtipotratamento"]', value=valor_sub)
        await page.wait_for_timeout(500)
    except Exception:
        pass  # o select pode nao existir no 1o procedimento; nao e' fatal aqui

    await page.fill('#codrolmostra', codigo)
    await page.press('#codrolmostra', 'Tab')

    try:
        await page.wait_for_selector('td[onclick*="filleprocedimento"]', timeout=6000)
    except PlaywrightTimeoutError:
        return False, f"Codigo '{codigo}' nao encontrado no portal."

    celulas = page.locator('td[onclick*="filleprocedimento"]')
    total = await celulas.count()
    clicado = False
    for i in range(total):
        celula = celulas.nth(i)
        if codigo in (await celula.inner_text()):
            await celula.click()
            clicado = True
            break
    if not clicado and total > 0:
        await celulas.first.click()
        clicado = True

    if not clicado:
        return False, f"Nao foi possivel selecionar o procedimento '{codigo}'."

    await page.wait_for_timeout(500)
    await page.click('input[name="adicionar"]')
    await page.wait_for_timeout(800)
    return True, None


# ── Fluxo principal ───────────────────────────────────────────────────────────
async def executar(job: dict) -> dict:
    """Executa o submit a partir de um job validado.

    job = {
      "carteirinha": str, "medico": str,
      "codigos": [{"codigo": str, "sub_tipo": "RM"|"TC"}],
      "arquivos": [caminho, ...]   # pedido medico, ja salvo em disco
    }

    Retorna dict no formato submit_result (sem job_id/idempotency_key, que o
    worker injeta).
    """
    evidencias: list = []

    # Pre-flight em memoria (antes de abrir browser) ------------------------
    try:
        campo1, campo2, campo3 = split_carteirinha(job["carteirinha"])
    except SubmitAbortado as e:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": str(e)}

    codigos = [c for c in job.get("codigos", []) if c.get("codigo_tuss", "").strip()]
    if not codigos:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Nenhum codigo de procedimento informado."}

    arquivos = [a for a in job.get("arquivos", []) if a]

    try:
        async with sessao.navegador() as page:
            await sessao.login(page)

            # 3. Gerar Solicitacao
            await page.get_by_role("link", name="GERAR SOLICITAÇÃO").click()
            await page.wait_for_load_state("domcontentloaded")

            # 4. Carteirinha (de tras pra frente, como o portal exige)
            await page.fill('#campo3', campo3)
            await page.fill('#campo2', campo2)
            await page.fill('#campo1', campo1)
            await page.click('input[name="buscar"]')
            await page.wait_for_load_state("domcontentloaded")

            # HARD STOP 1 (1.2): beneficiario tem que ser encontrado
            try:
                await page.wait_for_selector('#emailprestador', timeout=8000)
            except PlaywrightTimeoutError:
                await _snap(page, "erro_carteirinha", evidencias)
                raise SubmitAbortado(
                    f"Beneficiario nao encontrado para a carteirinha "
                    f"'{job['carteirinha']}'."
                )

            # 5. Dados fixos do prestador
            await page.fill('#emailprestador', config.email_prestador())
            await page.fill('#setor', config.setor())
            await page.select_option('select[name="tipoprestador"]',
                                     value=config.TIPO_PRESTADOR_VALUE)
            await page.wait_for_timeout(800)

            # 6-9. Medico, especialidade, tipo, ngl/urgencia
            await page.fill('#mediconcooperados', job["medico"].upper())
            await page.select_option('select[name="especialidadencooperados"]',
                                     value=config.ESPECIALIDADE_VALUE)
            await page.select_option('select[name="tipo"]',
                                     value=config.TIPO_TRATAMENTO_VALUE)
            await page.wait_for_timeout(1500)
            await page.select_option('select[name="ngl"]', value=config.NGL_VALUE)
            await page.select_option('#urgencia', value=config.URGENCIA_VALUE)

            # 10. Procedimentos — HARD STOP 2 (1.2): TODOS tem que entrar
            for item in codigos:
                # Resolve o codigo que vai no portal (identidade hoje p/ Unimed;
                # de-para, se existir, mora no worker — nunca no HOP).
                codigo_portal = codigos_mod.resolver_codigo_portal(item["codigo_tuss"])
                ok, erro = await _adicionar_procedimento(
                    page, codigo_portal, item.get("sub_tipo", "RM")
                )
                if not ok:
                    await _snap(page, "erro_codigo", evidencias)
                    raise SubmitAbortado(
                        f"Codigo nao adicionado: {erro} "
                        "(gravar abortado para nao gerar guia parcial)."
                    )

            # 11-12. Ja executado + data
            try:
                await page.select_option('select[name="jaexecutado"]', label="Não")
            except Exception:
                pass
            try:
                await page.fill('input[name="datarealizacao"]',
                                date.today().strftime('%d/%m/%Y'))
            except Exception:
                pass

            # 12.5 Limpa anexos anteriores (aceita os 2 confirms)
            try:
                await page.wait_for_selector('a[onclick*="ExcluirAnexosTraamento"]',
                                             timeout=5000)
                await page.evaluate(
                    "window.confirm=function(){return true};"
                    "window.alert=function(){return true};"
                )
                await page.locator('a[onclick*="ExcluirAnexosTraamento"]').click()
                await page.wait_for_timeout(3000)
            except Exception:
                pass

            # 13. Anexos — HARD STOP 3 (1.2): TODOS tem que confirmar.
            # Antes engolia falha em silencio -> guia sem pedido medico.
            for arquivo in arquivos:
                if not os.path.exists(arquivo):
                    raise SubmitAbortado(f"Anexo nao encontrado em disco: {arquivo}")
                try:
                    await page.wait_for_selector('#box1', timeout=8000)
                    await page.wait_for_timeout(1000)
                    frame = page.frame_locator('#box1')
                    file_input = frame.locator('input[type="file"]')
                    await file_input.wait_for(state='attached', timeout=8000)
                    await file_input.set_input_files(arquivo)
                    await frame.locator('form').evaluate('f => f.submit()')
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    await _snap(page, "erro_anexo", evidencias)
                    raise SubmitAbortado(
                        f"Falha ao anexar '{os.path.basename(arquivo)}': {e} "
                        "(gravar abortado para nao gravar sem pedido medico)."
                    )

            # 14. Localidade (opcional — depende do tipo de carteirinha)
            await page.wait_for_timeout(3000)
            try:
                estado = page.locator('select[name="estadolocalidade"]')
                await estado.wait_for(state='visible', timeout=8000)
                await page.select_option('select[name="estadolocalidade"]',
                                         value=config.ESTADO_LOCALIDADE_VALUE)
                await page.wait_for_timeout(2000)
                for _ in range(8):
                    n = await page.eval_on_selector(
                        'select[name="cidadelocalidade"]', "el => el.options.length")
                    if n > 1:
                        break
                    await page.wait_for_timeout(1000)
                await page.select_option('select[name="cidadelocalidade"]',
                                         value=config.CIDADE_LOCALIDADE_VALUE)
                await page.wait_for_timeout(500)
            except Exception:
                pass

            # 15. GRAVAR (ato irreversivel; chegamos aqui = invariantes OK)
            momento_gravar = datetime.now()
            await page.click('input[id="gravar"]')
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            await _snap(page, "pos_gravar", evidencias)

            # 1.1 Captura do protocolo VIA LISTA (Acompanhar Solicitacoes).
            # Mais confiavel que raspar a tela de confirmacao: a lista mostra o
            # protocolo de toda guia recem-criada. Conservador: so' retorna se
            # casar nome+recencia com seguranca (ver buscar_protocolo_na_lista).
            protocolo = None
            try:
                protocolo = await varredura.buscar_protocolo_na_lista(
                    page, job.get("paciente_nome", ""), momento_gravar
                )
            except Exception:
                protocolo = None

            if protocolo:
                return {
                    "status": "protocolado",
                    "numero_protocolo": protocolo,
                    "evidencias": evidencias,
                    "mensagem": "Solicitacao gravada e protocolo capturado da lista.",
                }
            # Gravou, mas nao localizou o protocolo com seguranca: NUNCA inventar
            # nem chutar (protocolo errado correlaciona ao paciente errado).
            return {
                "status": "protocolado",
                "numero_protocolo": None,
                "requer_captura_manual": True,
                "evidencias": evidencias,
                "mensagem": "Gravado, mas protocolo nao casado com seguranca na "
                            "lista. Capturar manualmente pelo screenshot pos_gravar.",
            }

    except SubmitAbortado as e:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": evidencias, "mensagem": str(e)}
    except PlaywrightTimeoutError as e:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": evidencias, "mensagem": f"Tempo excedido: {e}"}
    except Exception as e:
        import traceback
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": evidencias,
                "mensagem": f"Erro inesperado: {e}",
                "detalhe": traceback.format_exc()}
