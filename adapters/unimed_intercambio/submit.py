"""submit.py — Tempo 1 (SUBMIT) do adapter Unimed Intercambio (portal CONNECTA).

Portado de bot_connecta.py (validado ao vivo 14/07/2026). Os helpers de portal
sao preservados VERBATIM (a mecanica DevExpress/Materialize/ASP.NET e' fina e
validada); adaptam-se so' as bordas:
  - browser/login/contexto via sessao.navegador()/sessao.login();
  - contrato de saida submit_result (protocolado|erro_submit|requer_humano);
  - dados vem do job da esteira (codigo_tuss -> identidade; crm dedicado);
  - Beneficiario de Transito -> "Sim" (a autorizacao E' o teste de validacao do
    paciente de intercambio); Exames realizados sem justificativa -> requer_humano.

Costura A (FalhaDeterministica -> agente) NAO entra nesta fase (ver plano Task 7):
erros in-portal retornam erro_submit ate' o caminho ser validado ao vivo.
"""
import os
from datetime import datetime

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from . import config, sessao
from . import codigos as codigos_mod
from agente import FalhaDeterministica, MotivoFalha


# ── Evidencia ────────────────────────────────────────────────────────────────
async def _salvar_screenshot_erro(page, motivo: str) -> str:
    if page is None:
        return ""
    try:
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho = os.path.join(config.SCREENSHOTS_DIR, f"erro_{motivo}_{ts}.png")
        await page.screenshot(path=caminho, full_page=True)
        return os.path.basename(caminho)
    except Exception:
        return ""


# ── Helpers de campo (VERBATIM do bot_connecta.py) ───────────────────────────
async def _set_value(locator, valor: str):
    page = locator.page
    try:
        await locator.fill(valor, force=True, timeout=10000)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(500)
        await locator.fill(valor, force=True, timeout=10000)
    try:
        await locator.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
    except Exception:
        pass
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass


async def _select_by_text(locator, texto: str) -> bool:
    page = locator.page
    for tentativa in range(2):
        try:
            opcoes = await locator.locator("option").all_inner_texts()
            alvo = next((o for o in opcoes if texto in o), None)
            if not alvo:
                return False
            await locator.select_option(label=alvo, force=True, timeout=10000)
            return True
        except Exception:
            if tentativa == 0:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(500)
                continue
            return False
    return False


async def _ler_valor_campo(page, id_campo: str, tentativas: int = 5, espera_ms: int = 500):
    for _ in range(tentativas):
        try:
            valor = await page.evaluate(
                """(id) => {
                    const el = document.getElementById(id);
                    return el ? el.value : null;
                }""",
                id_campo,
            )
        except Exception:
            valor = None
        if valor and valor.strip():
            return valor
        await page.wait_for_timeout(espera_ms)
    return None


async def _click(locator):
    await locator.click(force=True, timeout=10000)


async def _blur_e_aguardar(page, segundos: int = 8):
    try:
        await page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
    except Exception:
        pass
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=2000)
    except Exception:
        pass

    intervalo_ms = 400
    decorrido_ms = 0
    estavel_ms = 0
    limite_ms = segundos * 1000
    while decorrido_ms < limite_ms:
        try:
            carregando = await page.evaluate(
                """() => {
                    const t = document.body.innerText || '';
                    return t.includes('Carregando...') || t.includes('Pesquisando...');
                }"""
            )
        except Exception:
            carregando = False
        if carregando:
            estavel_ms = 0
        else:
            estavel_ms += intervalo_ms
            if estavel_ms >= 1000:
                break
        await page.wait_for_timeout(intervalo_ms)
        decorrido_ms += intervalo_ms

    await expandir_todos_blocos(page)


async def _preencher_com_espera(page, obter_locator, valor: str, segundos: int = 8, cliques_fora: int = 1):
    await _set_value(obter_locator(), valor)
    for _ in range(cliques_fora):
        await _blur_e_aguardar(page, segundos)


async def _selecionar_com_espera(page, obter_locator, texto: str, segundos: int = 8, cliques_fora: int = 1) -> bool:
    ok = await _select_by_text(obter_locator(), texto)
    for _ in range(cliques_fora):
        await _blur_e_aguardar(page, segundos)
    return ok


async def _assentar_pagina(page):
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    await expandir_todos_blocos(page)


async def expandir_todos_blocos(page):
    try:
        await page.evaluate(
            """() => {
                document.querySelectorAll('a[href="#!"]').forEach(a => {
                    const texto = (a.textContent || '').toLowerCase();
                    if (texto.includes('expandir')) { a.click(); }
                });
            }"""
        )
    except Exception:
        pass
    await page.wait_for_timeout(500)


async def _id_input_por_label(page, texto_label: str):
    try:
        return await page.evaluate(
            """(texto) => {
                function acharInput(el) {
                    let cur = el.parentElement;
                    let nivel = 0;
                    while (cur && nivel < 8) {
                        const comboTable = cur.querySelector('table[title*="4 primeiros caracteres"]');
                        if (comboTable) {
                            const input = document.getElementById(comboTable.id + '_I');
                            if (input) return input.id;
                        }
                        const generic = Array.from(cur.querySelectorAll('input[type="text"], select')).find(i => i.id);
                        if (generic) return generic.id;
                        cur = cur.parentElement;
                        nivel++;
                    }
                    return null;
                }
                const els = Array.from(document.querySelectorAll('*'));
                const alvo = els.find(e => e.children.length === 0 && e.textContent && e.textContent.trim().startsWith(texto));
                if (!alvo) return null;
                return acharInput(alvo);
            }""",
            texto_label,
        )
    except Exception:
        return None


async def _preencher_autocomplete_locator(page, campo, valor: str, contains: str = None) -> bool:
    alvo = contains or valor
    await campo.wait_for(state="attached", timeout=10000)
    try:
        await campo.clear(force=True, timeout=5000)
    except Exception:
        pass
    await campo.fill(valor, force=True, timeout=10000)
    await page.wait_for_timeout(2500)
    try:
        sugestao = page.locator(f"text={alvo}").first
        await sugestao.wait_for(state="attached", timeout=8000)
        await _click(sugestao)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        rect = await page.evaluate(
            """(alvo) => {
                const els = Array.from(document.querySelectorAll('body *'));
                const candidatos = els.filter(e => e.children.length === 0 && e.textContent && e.textContent.includes(alvo));
                for (const el of candidatos) {
                    const item = el.closest('tr,li,td') || el;
                    const r = item.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
                    }
                }
                return null;
            }""",
            alvo,
        )
        if not rect:
            return False
        await page.mouse.click(rect["x"], rect["y"])
        await page.wait_for_timeout(500)
        return True


async def preencher_autocomplete_por_id(page, id_campo: str, valor: str, contains: str = None) -> bool:
    campo = page.locator(f"#{id_campo}")
    return await _preencher_autocomplete_locator(page, campo, valor, contains)


async def adicionar_item_procedimento(page, codigo: str, quantidade: int) -> tuple:
    ID_CODIGO_DESCRICAO = "cphConteudo_UcBlocoConteudo8_ctl00_UcItensSolicitacao_udcAcProcItens_udcAcProcItens_aspxComboBox_I"
    ID_QUANTIDADE = "cphConteudo_UcBlocoConteudo8_ctl00_UcItensSolicitacao_txbQuantidade"
    ID_BOTAO_ADICIONAR = "cphConteudo_UcBlocoConteudo8_ctl00_UcItensSolicitacao_btnAddProcedimento"

    tipo_ok = await _selecionar_com_espera(page, lambda: page.get_by_label("Tipo:").first, config.TIPO_ITEM_FIXO, segundos=6, cliques_fora=1)

    campo_codigo_descricao = page.locator(f"#{ID_CODIGO_DESCRICAO}")
    try:
        await campo_codigo_descricao.wait_for(state="attached", timeout=10000)
        ok = await _preencher_autocomplete_locator(page, campo_codigo_descricao, codigo)
        if ok:
            await _blur_e_aguardar(page, 6)
    except PlaywrightTimeoutError:
        id_codigo_descricao = None
        for _ in range(10):
            id_codigo_descricao = await _id_input_por_label(page, "Código/Descrição")
            if id_codigo_descricao:
                break
            await page.wait_for_timeout(500)
        if not id_codigo_descricao:
            return False, f"Campo 'Código/Descrição' nao encontrado (nem por ID direto, nem por busca de texto) apos tentativas (tipo_select_ok={tipo_ok})."
        ok = await preencher_autocomplete_por_id(page, id_codigo_descricao, codigo)

    if not ok:
        return False, f"Codigo '{codigo}' nao encontrado no autocomplete do Connecta."

    for _ in range(15):
        try:
            tipo_despesa_ok = await page.evaluate(
                """() => {
                    const els = Array.from(document.querySelectorAll('*'));
                    const alvo = els.find(e => e.children.length === 0 && e.textContent && e.textContent.trim().startsWith('Tipo despesa'));
                    if (!alvo) return null;
                    let cur = alvo.parentElement, nivel = 0;
                    while (cur && nivel < 8) {
                        const sel = cur.querySelector('select');
                        if (sel) {
                            const opt = sel.options[sel.selectedIndex];
                            return opt ? opt.text : null;
                        }
                        cur = cur.parentElement; nivel++;
                    }
                    return null;
                }"""
            )
        except Exception:
            tipo_despesa_ok = None
        if tipo_despesa_ok and "selecione" not in tipo_despesa_ok.lower():
            break
        await page.wait_for_timeout(500)

    if not tipo_despesa_ok or "selecione" in (tipo_despesa_ok or "").lower():
        try:
            await page.evaluate(
                """() => {
                    const els = Array.from(document.querySelectorAll('*'));
                    const alvo = els.find(e => e.children.length === 0 && e.textContent && e.textContent.trim().startsWith('Tipo despesa'));
                    if (!alvo) return false;
                    let cur = alvo.parentElement, nivel = 0;
                    while (cur && nivel < 8) {
                        const sel = cur.querySelector('select');
                        if (sel && sel.options.length > 1) {
                            sel.selectedIndex = 1;
                            sel.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                        cur = cur.parentElement; nivel++;
                    }
                    return false;
                }"""
            )
            await page.wait_for_timeout(1500)
        except Exception:
            pass

    campo_qtd = page.locator(f"#{ID_QUANTIDADE}")
    await campo_qtd.wait_for(state="attached", timeout=10000)
    try:
        await campo_qtd.clear(force=True, timeout=5000)
    except Exception:
        pass
    try:
        await campo_qtd.press_sequentially(str(quantidade), delay=80)
    except Exception:
        await campo_qtd.fill(str(quantidade), force=True, timeout=10000)

    qtd_ok = await _ler_valor_campo(page, ID_QUANTIDADE, tentativas=3, espera_ms=400)
    if not qtd_ok:
        try:
            await campo_qtd.clear(force=True, timeout=5000)
        except Exception:
            pass
        try:
            await campo_qtd.press_sequentially(str(quantidade), delay=80)
        except Exception:
            await campo_qtd.fill(str(quantidade), force=True, timeout=10000)
        qtd_ok = await _ler_valor_campo(page, ID_QUANTIDADE, tentativas=3, espera_ms=400)
    if not qtd_ok:
        return False, f"Campo Quantidade nao ficou preenchido para o codigo '{codigo}'."

    async def _contar_linhas_tabela_procedimentos():
        try:
            return await page.evaluate(
                """() => {
                    const tables = Array.from(document.querySelectorAll('table'));
                    const tabela = tables.find(t => (t.innerText || '').includes('Ações') && (t.innerText || '').includes('Quantidade'));
                    if (!tabela) return 0;
                    return tabela.querySelectorAll('tbody tr').length;
                }"""
            )
        except Exception:
            return 0

    linhas_antes = await _contar_linhas_tabela_procedimentos()

    botao_adicionar = page.locator(f"#{ID_BOTAO_ADICIONAR}")
    await botao_adicionar.wait_for(state="attached", timeout=10000)
    await _click(botao_adicionar)
    await page.wait_for_timeout(800)

    try:
        alerta_presente = await page.evaluate(
            """() => (document.body.innerText || '').includes('Digite os dados obrigatórios')"""
        )
    except Exception:
        alerta_presente = False
    if alerta_presente:
        try:
            await _click(page.get_by_role("button", name="Ok").first)
        except Exception:
            try:
                await page.get_by_text("Ok", exact=True).first.evaluate("el => el.click()")
            except Exception:
                pass
        await page.wait_for_timeout(500)

    await _blur_e_aguardar(page, 7)
    await _assentar_pagina(page)

    linhas_depois = await _contar_linhas_tabela_procedimentos()
    if linhas_depois <= linhas_antes:
        await _click(botao_adicionar)
        await _blur_e_aguardar(page, 7)
        linhas_depois = await _contar_linhas_tabela_procedimentos()
        if linhas_depois <= linhas_antes:
            return False, f"Codigo '{codigo}' nao entrou na tabela de Procedimentos apos clicar Adicionar (2 tentativas)."

    return True, None


async def tratar_alertas_pos_envio(page) -> dict:
    try:
        presentes = await page.evaluate(
            """() => {
                const texto = document.body.innerText || '';
                return {
                    beneficiario_transito: texto.includes('Cadastro de Beneficiário de Trânsito'),
                    exames_realizados: texto.includes('Alerta - Exames realizados'),
                };
            }"""
        )
    except Exception:
        presentes = {"beneficiario_transito": False, "exames_realizados": False}
    return {"alertas": [k for k, v in presentes.items() if v]}


async def clicar_enviar(page) -> dict:
    """Dispara o Enviar. O onclick real (mapeado ao vivo 2026-08-04) e':
    `if (validarFormulario('#conteudoFormulario')) __doPostBack('ctl00$cphConteudo$HiddenPostBack')`.
    Chamar validarFormulario por page.evaluate quebra em strict-mode (a funcao usa
    arguments.callee). Solucao: injeta a MESMA logica via add_script_tag, que roda
    em contexto NAO-strict, capturando o retorno de validarFormulario e postando
    so' se true. Retorna {valido: True|False|str, erro?: str}."""
    try:
        await page.add_script_tag(content=(
            "window.__envRes = (function(){ try {"
            " var ok = (typeof validarFormulario === 'function')"
            "   ? validarFormulario('#conteudoFormulario') : 'sem_validarFormulario';"
            " if (ok === true) { __doPostBack('ctl00$cphConteudo$HiddenPostBack'); }"
            " return {valido: ok};"
            " } catch(e) { return {erro: String(e)}; } })();"
        ))
        res = await page.evaluate("() => window.__envRes") or {}
    except Exception as e:
        # CSP pode bloquear inline script — fallback p/ dispatch_event nativo.
        try:
            await page.locator("#ButtonFloat_JSFunction_BtnEnviar_BtnFloat").dispatch_event("click")
            res = {"valido": "fallback_dispatch"}
        except Exception:
            res = {"erro": f"add_script_tag e dispatch falharam: {e}"}
    if res.get("valido") is True or res.get("valido") == "fallback_dispatch":
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
    return res


async def ler_recibo(page) -> dict:
    # IDs reais do bloco de recibo (mapeados ao vivo 2026-08-03) — mais robusto
    # que casar por title (evita colidir com campos do formulario).
    _P = "cphConteudo_ucrReciboGuia_ubcCabecalhoRecibo_ctl00_"
    ids = {
        "Número Guia Prestador": _P + "txbRecNumGuiaPrestador",
        "Número Guia Operadora": _P + "txbRecNumGuiaOperadora",
        "Status": _P + "txbRecStatus",
        "Nº da Autorização": _P + "txbRecNumAutorizacao",
        "Data de Validade da Autorização": _P + "txbRecDataValidade",
    }
    dados = {}
    for titulo, id_campo in ids.items():
        dados[titulo] = await _ler_valor_campo(page, id_campo, tentativas=1, espera_ms=100)
    return dados


# ── Contrato da esteira ──────────────────────────────────────────────────────
def _mapear_recibo(recibo: dict, status: str | None) -> dict:
    """Recibo do CONNECTA -> submit_result. Autorizado -> protocolado
    (numero_protocolo = Guia Operadora); qualquer outro status -> requer_humano
    (conservador I3, nunca inventa)."""
    if status and status.strip().lower() == "autorizado":
        return {
            "status": "protocolado",
            "numero_protocolo": recibo.get("Número Guia Operadora") or None,
            "numero_autorizacao": recibo.get("Nº da Autorização"),
            "validade": recibo.get("Data de Validade da Autorização"),
            "evidencias": [],
            "mensagem": "Autorizacao CONNECTA (intercambio) efetivada.",
        }
    return {
        "status": "requer_humano", "numero_protocolo": None,
        "requer_captura_manual": True, "evidencias": [],
        "mensagem": f"Guia enviada, status retornado: {status!r}. Conferir manual.",
    }


# ── Captura pos-envio via Historico (o CONNECTA nao mostra recibo inline) ─────
async def _capturar_no_historico(page, numero_guia_prestador, carteirinha, data_hoje):
    """Busca a guia recem-enviada no Historico de Autorizacoes (filtro por
    carteirinha + periodo=hoje) e casa a linha pelo Nº Guia Prestador. Colunas da
    dtLista (mapeadas ao vivo 2026-08-04): [3]=Status Guia, [4]=Nº Autorizacao
    (senha), [5]=carteira, [7]=data, [10]=Nº Guia (operadora), [11]=Nº Guia
    Prestador. Retorna dict do registro, ou None (I3: sem match seguro, nao chuta)."""
    try:
        await page.goto(config.URL_HISTORICO_AUTORIZACAO, wait_until="domcontentloaded")
    except Exception:
        return None
    await page.wait_for_timeout(1500)
    cart = "".join(filter(str.isdigit, carteirinha or ""))
    try:
        await page.locator("#cphConteudo_txbCodBeneficiario").fill(cart)
    except Exception:
        pass
    for camp in ("#cphConteudo_txbDataInicial", "#cphConteudo_txbDataFinal"):
        try:
            await page.locator(camp).fill(data_hoje)
        except Exception:
            pass
    try:
        await page.locator("#cphConteudo_btnConfirmar").click(force=True, timeout=10000)
    except Exception:
        pass
    for _ in range(20):
        await page.wait_for_timeout(1000)
        try:
            pronto = await page.evaluate(
                """() => !((document.body.innerText||'').includes('Carregando...')
                          || (document.body.innerText||'').includes('Pesquisando'))""")
        except Exception:
            pronto = False
        if pronto:
            break
    try:
        rows = await page.evaluate(
            """() => {
              const t = document.querySelector('#cphConteudo_dtLista')
                        || document.querySelector('#dtLista');
              if (!t) return [];
              return Array.from(t.querySelectorAll('tbody tr')).map(r =>
                Array.from(r.querySelectorAll('td')).map(c => (c.innerText || '').trim()));
            }""")
    except Exception:
        rows = []
    alvo = "".join(filter(str.isdigit, numero_guia_prestador or ""))
    melhor = None
    for cells in rows:
        if len(cells) < 12:
            continue
        reg = {"status_guia": cells[3], "autorizacao": cells[4],
               "guia_operadora": cells[10], "guia_prestador": cells[11], "data": cells[7]}
        if alvo and "".join(filter(str.isdigit, cells[11])) == alvo:
            return reg                      # match exato pelo Nº Guia Prestador
        if melhor is None:
            melhor = reg                    # fallback (so' usado se nao houver alvo)
    return None if alvo else melhor


def _mapear_captura(cap: dict | None) -> dict:
    """Registro do Historico -> submit_result. Autorizado -> protocolado
    (numero_protocolo = Nº Autorizacao/senha). Negado/Cancelada/desconhecido ->
    requer_humano (nao e' erro do bot; e' decisao do portal). I3 conservador."""
    if not cap:
        return {"status": "requer_humano", "numero_protocolo": None,
                "requer_captura_manual": True, "evidencias": [],
                "mensagem": "Enviado, mas guia nao localizada no Historico. Conferir manual."}
    st = (cap.get("status_guia") or "").strip().lower()
    # Contrato acordado com o HOP (Codex 2026-08-04): o HOP grava
    #   autorizacoes.senha           <- numero_autorizacao (a "Senha" do CONNECTA)
    #   autorizacoes.numero_protocolo<- numero_guia_operadora (fallback numero_protocolo)
    # Por isso numero_protocolo carrega a GUIA OPERADORA (nao a senha), e a senha
    # vai em numero_autorizacao/senha. Validade fica ausente (nao vem na lista;
    # captura no detalhe e' passo futuro — nunca inferir).
    base = {"senha": cap.get("autorizacao"),
            "numero_autorizacao": cap.get("autorizacao"),
            "numero_guia_operadora": cap.get("guia_operadora"),
            "numero_guia_prestador": cap.get("guia_prestador"),
            "validade": None,
            "evidencias": []}
    if st == "autorizado":
        return {"status": "protocolado",
                "numero_protocolo": cap.get("guia_operadora") or cap.get("autorizacao"),
                "mensagem": (f"Autorizado. Senha {cap.get('autorizacao')}, "
                             f"guia operadora {cap.get('guia_operadora')}."), **base}
    if st.startswith("negad"):
        return {"status": "requer_humano", "numero_protocolo": None,
                "requer_captura_manual": True,
                "mensagem": f"Guia NEGADA pela Unimed (guia prestador {cap.get('guia_prestador')}).",
                **base}
    if st.startswith("cancelad"):
        return {"status": "requer_humano", "numero_protocolo": None,
                "requer_captura_manual": True,
                "mensagem": f"Guia CANCELADA (guia prestador {cap.get('guia_prestador')}).",
                **base}
    return {"status": "requer_humano", "numero_protocolo": None,
            "requer_captura_manual": True,
            "mensagem": f"Status '{cap.get('status_guia')}' — conferir manual.", **base}


def _job_para_dados(job: dict) -> dict:
    return {
        "carteirinha": job["carteirinha"],
        "medico": job["medico"],
        "crm": job["crm"],
        "codigo_prestador": job.get("codigo_prestador") or config.CODIGO_PRESTADOR_FIXO,
        "codigos": [
            {"codigo": codigos_mod.resolver_codigo_portal(c["codigo_tuss"]),
             "quantidade": c.get("quantidade", 1)}
            for c in job.get("codigos", [])
        ],
        # Intercambio: beneficiario e' de outra Unimed -> Transito e' a norma.
        "resposta_beneficiario_transito": "sim",
        "justificativa_exames_realizados": job.get("justificativa_exames_realizados"),
        "indicacao_clinica": job.get("indicacao_clinica"),
    }


async def executar(job: dict) -> dict:
    """Contrato da esteira. job (dict do worker): carteirinha, medico, crm,
    codigos:[{codigo_tuss,quantidade}], codigo_prestador?. Retorna submit_result."""
    for campo in ("carteirinha", "medico", "crm"):
        if not (job.get(campo) or "").strip():
            return {"status": "erro_submit", "numero_protocolo": None,
                    "evidencias": [], "mensagem": f"Campo obrigatorio ausente: '{campo}'."}
    if not job.get("codigos"):
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Nenhum codigo de procedimento informado."}
    return await _fluxo_connecta(_job_para_dados(job))


async def _fluxo_connecta(dados: dict) -> dict:
    """Corpo portado de bot_connecta._autorizar_uma_tentativa, das bordas p/
    dentro: usa sessao.navegador()/login(); retorna submit_result."""
    os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
    codigos = dados["codigos"]

    async with sessao.navegador() as page:
        # Aceita qualquer dialogo (confirm/alert). O Playwright auto-DISPENSA
        # dialogos por padrao (confirm -> false), o que CANCELARIA o envio se o
        # portal pedir "Deseja enviar?". Aceitando, o submit prossegue; tambem
        # registra o que apareceu (evidencia).
        dialogos: list = []

        async def _on_dialog(d):
            dialogos.append({"type": d.type, "message": (d.message or "")[:200]})
            try:
                await d.accept()
            except Exception:
                pass

        page.on("dialog", _on_dialog)
        try:
            try:
                await sessao.login(page)  # login + selecao de contexto
            except Exception as e:
                await _salvar_screenshot_erro(page, "login_contexto")
                raise FalhaDeterministica(
                    motivo=MotivoFalha.ESTADO_INESPERADO,
                    etapa="login_contexto",
                    detalhe=f"Falha no login/contexto CONNECTA: {e}",
                    url=page.url,
                )

            await page.goto(config.URL_SOLICITACAO, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                pass
            await expandir_todos_blocos(page)
            await page.wait_for_timeout(1000)

            campo_carteira = page.locator("#txbNumeroCarteira")
            await campo_carteira.wait_for(state="attached", timeout=15000)
            await _preencher_com_espera(page, lambda: page.locator("#txbNumeroCarteira"), dados["carteirinha"], segundos=8, cliques_fora=1)

            valor_carteira_ok = await _ler_valor_campo(page, "txbNumeroCarteira", tentativas=3, espera_ms=500)
            if not valor_carteira_ok:
                await _salvar_screenshot_erro(page, "carteira_nao_preencheu")
                raise FalhaDeterministica(
                    motivo=MotivoFalha.SELETOR_NAO_ACHADO,
                    etapa="preencher_carteira",
                    detalhe="Campo Numero da Carteira nao ficou preenchido.",
                    seletor="#txbNumeroCarteira",
                    url=page.url,
                )

            nome_atual = await _ler_valor_campo(
                page, "cphConteudo_udbBeneficiario_UcBlocoConteudo1_ctl00_txbNome", tentativas=20, espera_ms=500)
            if not nome_atual:
                await _salvar_screenshot_erro(page, "beneficiario_nao_encontrado")
                raise FalhaDeterministica(
                    motivo=MotivoFalha.VALIDACAO_PORTAL,
                    etapa="buscar_beneficiario",
                    detalhe=f"Beneficiario nao localizado para a carteirinha '{dados['carteirinha']}'.",
                    url=page.url,
                )

            ID_CODIGO_NOME_SOLICITANTE = "cphConteudo_udpDadosPrestadorCBO_ubcDadosPrestadorCBO_ctl00_udcAutoCompletePrestador_AcCombobox_I"
            ID_NOME_PROFISSIONAL = "cphConteudo_udpDadosPrestadorCBO_ubcDadosPrestadorCBO_ctl00_udcAcProfissional_udcAcProfissional_aspxComboBox_I"
            ID_NOME_CONTRATADO = "cphConteudo_udpDadosPrestadorCBO_ubcDadosPrestadorCBO_ctl00_txbNomeContratado"
            ID_NUMERO_CONSELHO = "txbNumeroConselho"
            ID_INDICACAO_CLINICA = "cphConteudo_UcBlocoConteudo7_ctl00_txbIndicacaoClinica"

            await _preencher_com_espera(
                page, lambda: page.locator(f"#{ID_CODIGO_NOME_SOLICITANTE}"),
                dados.get("codigo_prestador") or config.CODIGO_PRESTADOR_FIXO,
                segundos=8, cliques_fora=1)

            await _preencher_com_espera(
                page, lambda: page.locator(f"#{ID_NOME_CONTRATADO}"), dados["medico"], segundos=6, cliques_fora=2)

            await preencher_autocomplete_por_id(page, ID_NOME_PROFISSIONAL, dados["medico"])
            await _blur_e_aguardar(page, 6)
            await _blur_e_aguardar(page, 6)

            valor_nome_prof = await _ler_valor_campo(page, ID_NOME_PROFISSIONAL, tentativas=2, espera_ms=300)
            if not valor_nome_prof or valor_nome_prof.strip().isdigit():
                await preencher_autocomplete_por_id(page, ID_NOME_PROFISSIONAL, dados["medico"])
                await _blur_e_aguardar(page, 6)

            if not await _ler_valor_campo(page, ID_NOME_CONTRATADO, tentativas=2, espera_ms=300):
                await _preencher_com_espera(
                    page, lambda: page.locator(f"#{ID_NOME_CONTRATADO}"), dados["medico"], segundos=6, cliques_fora=1)

            await _selecionar_com_espera(
                page, lambda: page.get_by_label("Conselho Profissional:").first, config.CONSELHO_PROFISSIONAL_FIXO, segundos=6, cliques_fora=1)
            await _preencher_com_espera(
                page, lambda: page.locator(f"#{ID_NUMERO_CONSELHO}"), dados["crm"], segundos=6, cliques_fora=1)
            await _selecionar_com_espera(
                page, lambda: page.get_by_label("UF Conselho:").first, config.UF_CONSELHO_FIXO, segundos=6, cliques_fora=1)
            await _selecionar_com_espera(
                page, lambda: page.get_by_label("Código CBO:").first, config.CODIGO_CBO_FIXO, segundos=6, cliques_fora=1)
            await _selecionar_com_espera(
                page, lambda: page.get_by_label("Caráter do Atendimento:").first, config.CARATER_ATENDIMENTO_FIXO, segundos=6, cliques_fora=1)

            try:
                await _preencher_com_espera(
                    page, lambda: page.locator(f"#{ID_INDICACAO_CLINICA}"),
                    dados.get("indicacao_clinica") or "Medico solicitou",
                    segundos=3, cliques_fora=1)
            except Exception:
                pass

            await _assentar_pagina(page)

            erros_codigos = []
            for item in codigos:
                codigo = str(item.get("codigo", "")).strip()
                quantidade = item.get("quantidade", 1)
                if not codigo:
                    continue
                ok, erro = await adicionar_item_procedimento(page, codigo, quantidade)
                if not ok:
                    erros_codigos.append(erro)

            if erros_codigos and len(erros_codigos) == len(codigos):
                await _salvar_screenshot_erro(page, "todos_codigos_falharam")
                raise FalhaDeterministica(
                    motivo=MotivoFalha.SELETOR_NAO_ACHADO,
                    etapa="adicionar_procedimento",
                    detalhe=" | ".join(erros_codigos),
                    url=page.url,
                )

            await _salvar_screenshot_erro(page, "pre_envio_diagnostico")

            # Diagnostico env-gated (default off): dumpa o DOM do botao Enviar
            # SEM submeter, p/ mapear o seletor real com seguranca (nao gera guia).
            _diag = os.environ.get("INTERCAMBIO_DIAG", "")
            if _diag == "nosubmit":
                dump = await page.evaluate(
                    """() => {
                      const out = {fab: [], enviar: []};
                      document.querySelectorAll(
                        'a.fixed-action-btn, a[href*="ButtonFloat"], [id*="ButtonFloat"], '
                        + '[id*="BtnEnviar"], [id*="Enviar"], a[data-tooltip]'
                      ).forEach(e => out.fab.push({
                        tag: e.tagName, id: e.id, cls: e.className,
                        tip: e.getAttribute('data-tooltip'),
                        href: e.getAttribute('href'),
                        txt: (e.textContent || '').trim().slice(0, 50),
                        visivel: !!(e.offsetWidth || e.offsetHeight),
                      }));
                      Array.from(document.querySelectorAll('a,button,span,div,i')).forEach(e => {
                        const t = (e.textContent || '').trim();
                        if (t === 'Enviar' || (e.id || '').toLowerCase().includes('enviar'))
                          out.enviar.push({tag: e.tagName, id: e.id, cls: e.className, txt: t.slice(0, 50)});
                      });
                      const env = document.querySelector('#ButtonFloat_JSFunction_BtnEnviar_BtnFloat');
                      out.enviar_html = env ? env.outerHTML : null;
                      out.enviar_onclick = env ? env.getAttribute('onclick') : null;
                      const cont = document.querySelector('#ButtonFloat_BtnFloat');
                      out.container_html = cont ? cont.outerHTML.slice(0, 3000) : null;
                      return out;
                    }"""
                )
                return {"status": "diag_nosubmit", "numero_protocolo": None,
                        "evidencias": [], "mensagem": "DIAG nosubmit (nao submeteu)",
                        "dump": dump}

            # Diag do Historico (NAO submete — usa guias ja existentes p/ mapear a
            # tela onde o protocolo/senha e' capturado pos-envio).
            if _diag == "historico":
                dumphist = {}
                try:
                    await page.goto(config.URL_HISTORICO_AUTORIZACAO,
                                    wait_until="domcontentloaded")
                    await page.wait_for_timeout(3500)
                    dumphist = await page.evaluate(
                        """() => ({
                          url: location.href,
                          campos: Array.from(document.querySelectorAll('input,select'))
                            .map(e => ({id: e.id, title: e.getAttribute('title'),
                                        ph: e.placeholder})).filter(c => c.id).slice(0, 70),
                          tabelas: Array.from(document.querySelectorAll('table'))
                            .map(t => ({id: t.id, txt: (t.innerText || '').slice(0, 800)})).slice(0, 6),
                          body: (document.body.innerText || '').slice(0, 3500)
                        })"""
                    )
                except Exception as e:
                    dumphist = {"erro": str(e)}
                return {"status": "diag_historico", "numero_protocolo": None,
                        "evidencias": [], "mensagem": "DIAG historico (nao submeteu)",
                        "dump": dumphist}

            # Diag da CAPTURA (NAO submete): busca no Historico por carteirinha+hoje
            # e dumpa as linhas cruas da dtLista p/ mapear as colunas.
            if _diag == "capturar":
                data_hoje = datetime.now().strftime("%d/%m/%Y")
                dcap = {}
                try:
                    await page.goto(config.URL_HISTORICO_AUTORIZACAO, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                    cart = "".join(filter(str.isdigit, dados["carteirinha"]))
                    try:
                        await page.locator("#cphConteudo_txbCodBeneficiario").fill(cart)
                    except Exception:
                        pass
                    for camp in ("#cphConteudo_txbDataInicial", "#cphConteudo_txbDataFinal"):
                        try:
                            await page.locator(camp).fill(data_hoje)
                        except Exception:
                            pass
                    try:
                        await page.locator("#cphConteudo_btnConfirmar").click(force=True, timeout=10000)
                    except Exception:
                        pass
                    for _ in range(20):
                        await page.wait_for_timeout(1000)
                        pronto = await page.evaluate(
                            """() => !((document.body.innerText||'').includes('Carregando...')
                                      || (document.body.innerText||'').includes('Pesquisando'))""")
                        if pronto:
                            break
                    dcap = await page.evaluate(
                        """() => {
                          const t = document.querySelector('#cphConteudo_dtLista')
                                    || document.querySelector('#dtLista');
                          if (!t) return {achou_tabela: false};
                          const head = Array.from(t.querySelectorAll('thead th, thead td'))
                            .map(c => (c.innerText||'').trim());
                          const rows = Array.from(t.querySelectorAll('tbody tr')).slice(0, 8)
                            .map(r => Array.from(r.querySelectorAll('td'))
                              .map(c => (c.innerText||'').trim()));
                          return {achou_tabela: true, head, rows, n: rows.length};
                        }""")
                except Exception as e:
                    dcap = {"erro": str(e)}
                return {"status": "diag_capturar", "numero_protocolo": None,
                        "evidencias": [], "mensagem": "DIAG capturar (nao submeteu)",
                        "dump": dcap}

            # Captura o Nº da Guia (prestador) ANTES de enviar — chave p/ achar a
            # guia no Historico (o CONNECTA nao mostra recibo inline pos-envio).
            numero_guia_prestador = await _ler_valor_campo(
                page, "cphConteudo_UcBlocoConteudo2_ctl00_txbNumeroGuia",
                tentativas=2, espera_ms=200)

            env_res = await clicar_enviar(page)

            try:
                pagina_com_erro_500 = await page.evaluate(
                    """() => (document.body.innerText || '').includes('Erro 500')""")
            except Exception:
                pagina_com_erro_500 = False
            if pagina_com_erro_500:
                cam = await _salvar_screenshot_erro(page, "erro_500_unimed")
                return {"status": "erro_submit", "numero_protocolo": None, "evidencias": [],
                        "mensagem": "Servidor Unimed retornou Erro 500 (transitorio). Retentar em minutos.",
                        "screenshot": cam}

            # Diagnostico do ENVIO (env-gated): mostra o que aparece apos clicar
            # Enviar (modal de biometria? botoes p/ prosseguir sem biometria?).
            if os.environ.get("INTERCAMBIO_DIAG", "") == "envio":
                d = await page.evaluate(
                    """() => {
                      const vis = e => e && !!(e.offsetWidth || e.offsetHeight);
                      const modal = document.querySelector('[id*="ucrBlocoBiometriaModal"]');
                      const overlay = document.querySelector('.modal.open, .modal[style*="display: block"], .lean-overlay');
                      const btns = Array.from(document.querySelectorAll(
                        'a,button,input[type=button],input[type=submit]'))
                        .filter(vis).map(e => ({
                          tag: e.tagName, id: e.id, cls: e.className,
                          txt: (e.textContent || e.value || '').trim().slice(0, 50)})).slice(0, 80);
                      return {url: location.href,
                              modal_presente: !!modal, modal_visivel: vis(modal),
                              modal_html: modal ? modal.outerHTML.slice(0, 2000) : null,
                              overlay_aberto: vis(overlay),
                              botoes_visiveis: btns,
                              body: (document.body.innerText || '').slice(0, 4000)};
                    }"""
                )
                return {"status": "diag_envio", "numero_protocolo": None,
                        "evidencias": [], "mensagem": "DIAG envio", "dump": d}

            alertas = await tratar_alertas_pos_envio(page)

            if "beneficiario_transito" in alertas["alertas"]:
                # Intercambio: beneficiario de outra Unimed -> segue (Sim).
                if dados.get("resposta_beneficiario_transito", "sim") == "sim":
                    await _click(page.get_by_role("link", name="Sim").first)
                else:
                    await _click(page.get_by_role("link", name="Cancelar").first)
                    return {"status": "erro_submit", "numero_protocolo": None, "evidencias": [],
                            "mensagem": "Beneficiario nao reconhecido no cadastro Unimed."}
                await page.wait_for_timeout(1000)
                await clicar_enviar(page)
                await page.wait_for_timeout(1500)
                alertas = await tratar_alertas_pos_envio(page)

            if "exames_realizados" in alertas["alertas"]:
                justificativa = dados.get("justificativa_exames_realizados")
                if not justificativa:
                    cam = await _salvar_screenshot_erro(page, "alerta_exames_realizados")
                    return {"status": "requer_humano", "numero_protocolo": None,
                            "requer_captura_manual": True, "evidencias": [],
                            "mensagem": "Beneficiario ja possui historico dos mesmos procedimentos. "
                                        "Justificativa necessaria (HITL).",
                            "screenshot": cam}
                await _select_by_text(page.get_by_label("Justificativa:").first, justificativa)
                await _click(page.get_by_role("button", name="Continuar").first)
                await page.wait_for_timeout(1500)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                await page.screenshot(
                    path=os.path.join(config.SCREENSHOTS_DIR, f"pos_envio_{ts}.png"),
                    full_page=True)
            except Exception:
                pass

            # O CONNECTA nao mostra recibo inline: a guia vai pro Historico.
            # Captura status/senha/operadora la, casando pelo Nº Guia Prestador.
            data_hoje = datetime.now().strftime("%d/%m/%Y")
            cap = await _capturar_no_historico(
                page, numero_guia_prestador, dados["carteirinha"], data_hoje)
            resultado = _mapear_captura(cap)
            resultado["numero_guia_prestador_enviado"] = numero_guia_prestador
            if os.environ.get("INTERCAMBIO_DIAG", ""):
                resultado["envio"] = env_res
                resultado["dialogos"] = dialogos
                resultado["cap"] = cap
            return resultado

        except FalhaDeterministica:
            raise  # Costura A: o runner (worker) decide se aciona o agente.
        except PlaywrightTimeoutError as e:
            cam = await _salvar_screenshot_erro(page, "timeout")
            return {"status": "erro_submit", "numero_protocolo": None, "evidencias": [],
                    "mensagem": f"Tempo excedido: {e}", "screenshot": cam}
        except Exception as e:
            import traceback
            cam = await _salvar_screenshot_erro(page, "excecao")
            return {"status": "erro_submit", "numero_protocolo": None, "evidencias": [],
                    "mensagem": f"Erro inesperado: {e}", "detalhe": traceback.format_exc(),
                    "screenshot": cam}
