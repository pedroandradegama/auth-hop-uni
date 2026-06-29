"""
adapters/sassepe/submit.py — Tempo 1 (SUBMIT) do adapter Sassepe.

Porta para Playwright o fluxo SP/SADT validado no piloto (browser-harness/CDP),
aplicando os invariantes do contrato (I1 hard stops, I2 falha explicita,
I3 protocolo conservador, I4 evidencia).

ESTADO DO MAPEAMENTO: fluxo COMPLETO validado no portal real (envio real
gerou a guia 1189780 p/ a paciente AUREA, status Autorizada): login
(MVOnePass + aceite LGPD) -> SP/SADT -> CPF -> campos fixos + solicitante +
CBO (2 secoes) -> exames -> anexo -> "Próximo" -> resumo (/confirmar-dados) ->
"Enviar solicitação" (IRREVERSIVEL) -> captura do protocolo no Historico de
solicitacoes, casando por CPF (exato) + data de hoje (I3). A captura por carteira
(regex na tela de confirmacao) foi DESCARTADA: confundia o numero da carteira
com o protocolo. Sem casamento seguro -> numero_protocolo=None +
requer_captura_manual.

Contrato job (o worker entrega; anexos JA' em disco):
  {
    "cpf": "64387720468",            # identificador do Sassepe (NAO ha carteira)
    "medico": "DR FULANO",            # profissional SOLICITANTE (variavel)
    "paciente_nome": "...",           # p/ casar protocolo (quando mapeado)
    "codigos": [{"codigo_tuss": "40808041", "sub_tipo": "RM", "nome": "..."}],
    "arquivos": ["/abs/pedido.png"],  # pedido medico (1+), ja' salvos
  }
Saida: dict no vocabulario do contrato (status in {protocolado, erro_submit}).
"""
import os
import re
from datetime import datetime
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from . import config, codigos as codigos_mod
from . import sessao
from . import _ui
from . import varredura


class SubmitAbortado(Exception):
    """Pre-condicao dura (I1) falhou. O ato irreversivel NAO deve acontecer."""


# ── Solicitante (busca pelo metodo do piloto) ────────────────────────────────
def _split_medico(medico: str):
    """Quebra o `medico` do job em (crm, nome). O numero E' o CRM (descoberto no
    portal: o dropdown de solicitante exibe 'CRM - NOME' e casa por ambos).

    Formatos aceitos (HOP):
      "16188 NUBIA ROSA LOPES"   -> ("16188", "NUBIA ROSA LOPES")
      "16188 - NUBIA ROSA LOPES" -> ("16188", "NUBIA ROSA LOPES")
      "Dra. Nubia Rosa Lopes"    -> (None, "Dra. Nubia Rosa Lopes")
    Sem CRM, cai no fallback: busca pelo proprio nome (menos confiavel).
    O strip de prefixo (Dr./Dra.) e a normalizacao ficam no _ui.
    """
    t = (medico or "").strip()
    m = re.match(r"^\s*(\d+)\s*-?\s*(.*)$", t)
    if m and m.group(1):
        return m.group(1), m.group(2).strip()
    return None, t


# ── CPF ─────────────────────────────────────────────────────────────────────
def normalizar_cpf(cpf: str) -> str:
    """So' digitos; exige 11 (I1: identificador valido antes de qualquer coisa)."""
    digitos = "".join(filter(str.isdigit, cpf or ""))
    if len(digitos) != 11:
        raise SubmitAbortado(
            f"CPF invalido: '{cpf}' tem {len(digitos)} digitos (esperado 11)."
        )
    return digitos


# ── Evidencia (I4) ───────────────────────────────────────────────────────────
async def _snap(page, etapa: str, evidencias: list) -> str:
    os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(config.SCREENSHOTS_DIR, f"{etapa}_{ts}.png")
    await page.screenshot(path=caminho, full_page=True)
    evidencias.append({"etapa": etapa, "screenshot_path": caminho,
                       "ts": datetime.now().isoformat()})
    return caminho


# ── Navegacao ────────────────────────────────────────────────────────────────
async def _abrir_sp_sadt(page):
    """Menu Solicitacoes -> card SP/SADT. Falha alto se nao navegar (I2)."""
    coord = await page.evaluate(
        """() => {
          const el = Array.from(document.querySelectorAll('*')).find(e =>
            e.textContent.trim() === 'Solicitações'
            && e.getBoundingClientRect().width > 0);
          if (!el) return null;
          el.scrollIntoView({block: 'center'});
          const r = el.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not coord:
        raise SubmitAbortado("Menu 'Solicitações' nao encontrado pos-login.")
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)

    clicou = await page.evaluate(
        """() => {
          const h = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
            .find(e => e.textContent.trim() === 'SP/SADT');
          if (!h) return false;
          h.parentElement.click();
          return true;
        }"""
    )
    if not clicou:
        raise SubmitAbortado("Card 'SP/SADT' nao encontrado.")
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)


async def _buscar_e_selecionar_paciente(page, cpf: str):
    """Digita o CPF e seleciona a 1a linha de resultado. HARD STOP (I1): se
    nenhum resultado aparece, o beneficiario nao foi encontrado -> aborta."""
    # O input do CPF e' React e pode demorar a renderizar: poll ate' 12s.
    pos = None
    for _ in range(12):
        pos = await page.evaluate(
            """() => {
              const inp = Array.from(document.querySelectorAll('input'))
                .find(i => i.placeholder && i.placeholder.includes('CPF'));
              if (!inp) return null;
              const r = inp.getBoundingClientRect();
              if (r.width === 0) return null;
              return {cx: r.x + r.width / 2, cy: r.y + r.height / 2, bottom: r.bottom};
            }"""
        )
        if pos:
            break
        await page.wait_for_timeout(1000)
    if not pos:
        raise SubmitAbortado("Campo de busca por CPF nao encontrado.")
    await page.mouse.click(pos["cx"], pos["cy"])
    await page.keyboard.type(cpf)
    await page.wait_for_timeout(2000)

    async def _achar_linha():
        return await page.evaluate(
            """(b) => {
              const vw = window.innerWidth;
              const rows = Array.from(document.querySelectorAll('*')).filter(e => {
                const r = e.getBoundingClientRect();
                return r.top > b && r.top < b + 200 && r.height > 20
                  && r.height < 150 && r.width > 200 && r.left >= 0 && r.right <= vw;
              });
              if (!rows.length) return null;
              const r = rows[0].getBoundingClientRect();
              return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
            }""",
            pos["bottom"],
        )

    linha = await _achar_linha()
    if not linha:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1500)
        linha = await _achar_linha()
    if not linha:
        raise SubmitAbortado(f"Nenhum beneficiario encontrado para o CPF '{cpf}'.")

    await page.mouse.click(linha["cx"], linha["cy"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)
    await page.mouse.click(linha["cx"], linha["cy"])  # confirma selecao
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)


# ── Campos fixos da pagina 1 ─────────────────────────────────────────────────
async def _preencher_cabecalho(page, medico: str):
    """Checkbox + solicitante (variavel) + CBO + executante (fixo) + CBO +
    regime/especialidade/carater/tipo (fixos). Cada passo e' hard stop (I1):
    campo que nao preenche aborta antes de qualquer gravar."""
    await _ui.marcar_paciente_no_local(page)

    # Profissional SOLICITANTE (variavel: vem do job). Busca por CRM + casa por
    # nome tolerante (acento/sobrenome extra). Conservador (I3): match unico ou
    # aborta para captura manual — CRM repete por UF, chutar = solicitante errado.
    crm, nome = _split_medico(medico)
    status, candidatos = await _ui.selecionar_solicitante(page, crm, nome)
    if status != "ok":
        if status == "ambiguo":
            raise SubmitAbortado(
                f"Profissional solicitante '{medico}' ambiguo no dropdown "
                f"({len(candidatos)} matches: {candidatos}); requer captura manual."
            )
        raise SubmitAbortado(
            f"Profissional solicitante '{medico}' nao localizado no dropdown."
        )
    await page.wait_for_timeout(500)

    if not await _ui.preencher_cbo(page, indice=0):  # CBO da secao SOLICITANTE
        raise SubmitAbortado("CBO (solicitante) nao preenchido.")
    await page.wait_for_timeout(300)

    # Profissional EXECUTANTE (fixo: Pedro Andrade 21798).
    if not await _ui.preencher_dropdown(
        page, "Profissional executante",
        config.PROF_EXECUTANTE_NUM, config.PROF_EXECUTANTE_NOME,
    ):
        raise SubmitAbortado("Profissional executante fixo nao localizado.")
    await page.wait_for_timeout(500)

    if not await _ui.preencher_cbo(page, indice=1):  # CBO da secao EXECUTANTE
        raise SubmitAbortado("CBO (executante) nao preenchido.")
    await page.wait_for_timeout(300)

    fixos = [
        ("Regime de Atendimento", config.REGIME_BUSCA, config.REGIME_OPCAO),
        ("Especialidade da guia", config.ESPECIALIDADE_BUSCA, config.ESPECIALIDADE_OPCAO),
        ("Caráter do Atendimento", config.CARATER_BUSCA, config.CARATER_OPCAO),
        ("Tipo de Atendimento", config.TIPO_ATEND_BUSCA, config.TIPO_ATEND_OPCAO),
    ]
    for label, busca, opcao in fixos:
        if not await _ui.preencher_dropdown(page, label, busca, opcao):
            raise SubmitAbortado(f"Campo fixo nao preenchido: {label}.")
        await page.wait_for_timeout(300)


# ── Exames (loop) ─────────────────────────────────────────────────────────────
async def _adicionar_exame(page, codigo: str, qty: int):
    """Adiciona UM exame: Tabela 22 -> codigo -> quantidade (+) -> Adicionar.
    Retorna (ok, erro). Tabela e' SEMPRE 22 (busca/match por numero)."""
    if not await _ui.preencher_dropdown(page, "Tabela", config.TABELA_NUM,
                                        config.TABELA_NUM):
        return False, "Tabela 22 nao selecionada."
    await page.wait_for_timeout(500)

    if not await _ui.preencher_dropdown(
        page, "Código e descrição do procedimento ou item", codigo, codigo
    ):
        return False, f"Codigo '{codigo}' nao encontrado no portal."
    await page.wait_for_timeout(500)

    # Quantidade: botao '+' e' SVG sem texto. Acha por geometria (canto direito,
    # largura pequena); o ultimo da lista e' o '+' (o outro e' '-').
    coord = await page.evaluate(
        """() => {
          const cands = Array.from(document.querySelectorAll('button')).filter(e => {
            const r = e.getBoundingClientRect();
            return r.left > 1300 && r.width < 30 && r.width > 0;
          });
          const b = cands[cands.length - 1];
          if (!b) return null;
          const r = b.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not coord:
        return False, "Botao '+' de quantidade nao encontrado."
    for _ in range(max(1, qty)):
        await page.mouse.click(coord["cx"], coord["cy"])
        await page.wait_for_timeout(300)

    # Botao '+ Adicionar' (submit do exame): ha' DOIS elementos com "Adicionar"
    # (o toggle da secao e o submit). Filtra largura>100 e left>700; pega o mais
    # a' direita = submit.
    add = await page.evaluate(
        """() => {
          const btns = Array.from(document.querySelectorAll('button')).filter(e => {
            const r = e.getBoundingClientRect();
            return e.textContent.includes('Adicionar') && r.width > 100 && r.left > 700;
          });
          if (!btns.length) return null;
          btns.sort((a, b) =>
            b.getBoundingClientRect().left - a.getBoundingClientRect().left);
          const r = btns[0].getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not add:
        return False, "Botao '+ Adicionar' do exame nao encontrado."
    await page.mouse.click(add["cx"], add["cy"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)
    return True, None


# ── Anexo ─────────────────────────────────────────────────────────────────────
async def _anexar(page, arquivo: str):
    """Anexa UM arquivo: abre modal, seleciona tipo doc 03, faz upload via
    set_input_files (input[type=file] oculto), confirma. Retorna (ok, erro)."""
    if not os.path.exists(arquivo):
        return False, f"Anexo nao encontrado em disco: {arquivo}"

    # Click nativo do Playwright (actionability + scroll + centro). O texto pode
    # vir com ou sem o '+' (icone SVG); get_by_text casa o rotulo do botao.
    try:
        await page.get_by_text("Anexar arquivo", exact=False).first.click(timeout=10000)
    except Exception as e:
        return False, f"Botao 'Anexar arquivo' nao clicavel: {e}"

    # Espera o modal abrir: o label 'Tipo de documento' aparece quando pronto.
    modal_ok = False
    for _ in range(8):
        await page.wait_for_timeout(1000)
        modal_ok = await page.evaluate(
            """() => !!Array.from(document.querySelectorAll('*')).find(e => {
              const t = e.textContent.trim();
              return (t === 'Tipo de documento*' || t === 'Tipo de documento')
                && e.getBoundingClientRect().width > 0;
            })"""
        )
        if modal_ok:
            break
    if not modal_ok:
        return False, "Modal de anexo nao abriu (label 'Tipo de documento' ausente)."

    if not await _ui.preencher_dropdown(page, "Tipo de documento",
                                        config.TIPO_DOC_BUSCA, config.TIPO_DOC_OPCAO):
        return False, "Tipo de documento (03) nao selecionado."
    await page.wait_for_timeout(500)

    # Upload pelo input[type=file] oculto (Playwright preenche mesmo oculto).
    file_input = page.locator('input[type=file]').first
    try:
        await file_input.wait_for(state="attached", timeout=8000)
        await file_input.set_input_files(arquivo)
    except Exception as e:
        return False, f"Falha no upload de '{os.path.basename(arquivo)}': {e}"
    await page.wait_for_timeout(1500)

    concl = await page.evaluate(
        """() => {
          const b = Array.from(document.querySelectorAll('button')).find(e =>
            e.textContent.trim() === 'Concluir'
            && e.getBoundingClientRect().width > 0);
          if (!b) return null;
          const r = b.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not concl:
        return False, "Botao 'Concluir' do anexo nao encontrado."
    await page.mouse.click(concl["cx"], concl["cy"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)
    return True, None


async def _clicar_proximo(page):
    """Clica 'Proximo' (reversivel — avanca de pagina, nao gera guia)."""
    coord = await page.evaluate(
        """() => {
          const el = Array.from(document.querySelectorAll('button')).find(e =>
            e.textContent.trim() === 'Próximo'
            && e.getBoundingClientRect().width > 0);
          if (!el) return null;
          el.scrollIntoView({block: 'center'});
          const r = el.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not coord:
        raise SubmitAbortado("Botao 'Próximo' nao encontrado apos preencher pagina 1.")
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)


async def _enviar_solicitacao(page, cpf_paciente, evidencias) -> dict:
    """Pagina /confirmar-dados (Resumo): clica 'Enviar solicitacao' — ATO
    IRREVERSIVEL (gera a guia). Chegamos aqui = todos os invariantes (I1) ok.
    Depois, captura conservadora do protocolo (I3) + evidencia (I4)."""
    # Confirma que estamos na tela de resumo (defesa: nao enviar fora dela).
    if "confirmar-dados" not in page.url:
        raise SubmitAbortado(
            f"Esperava a tela de resumo (confirmar-dados), URL atual: {page.url}"
        )

    data_hoje = datetime.now().strftime("%d/%m/%Y")
    try:
        await page.get_by_text("Enviar solicitação", exact=False).first.click(
            timeout=15000
        )
    except Exception as e:
        raise SubmitAbortado(f"Botao 'Enviar solicitação' nao clicavel: {e}")

    # Espera o envio concluir: sai de /confirmar-dados (a guia foi gerada).
    try:
        await page.wait_for_url(
            lambda url: "confirmar-dados" not in url, timeout=30000
        )
    except Exception:
        pass  # alguns fluxos mostram modal sem trocar URL; seguimos p/ captura
    await page.wait_for_timeout(2500)
    await _snap(page, "pos_enviar", evidencias)

    # Captura conservadora do protocolo (I3) VIA HISTORICO, casando por CPF
    # (exato) + data de hoje. Mais confiavel que raspar a tela de confirmacao
    # (onde a regex confundia o numero da carteira com o protocolo). Sem
    # casamento seguro -> numero_protocolo=None + requer_captura_manual.
    protocolo = None
    try:
        protocolo = await varredura.buscar_guia_por_cpf(page, cpf_paciente, data_hoje)
    except Exception:
        protocolo = None

    if protocolo:
        return {
            "status": "protocolado",
            "numero_protocolo": protocolo,
            "evidencias": evidencias,
            "mensagem": "Solicitacao enviada e numero da guia capturado do historico.",
        }
    return {
        "status": "protocolado",
        "numero_protocolo": None,
        "requer_captura_manual": True,
        "evidencias": evidencias,
        "mensagem": "Enviado, mas guia nao casada com seguranca no historico. "
                    "Conferir pelo screenshot pos_enviar / historico.",
    }


# ── Fluxo principal ───────────────────────────────────────────────────────────
async def executar(job: dict) -> dict:
    """Submit do Sassepe a partir de um job validado. Retorna submit_result
    (sem job_id/idempotency_key, que o worker injeta)."""
    evidencias: list = []

    # Pre-flight em memoria (I1: antes de abrir browser) ----------------------
    try:
        cpf = normalizar_cpf(job.get("cpf") or "")
    except SubmitAbortado as e:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": str(e)}

    if not (job.get("medico") or "").strip():
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Profissional solicitante (medico) ausente."}

    codigos = [c for c in job.get("codigos", []) if c.get("codigo_tuss", "").strip()]
    if not codigos:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Nenhum codigo de procedimento informado."}

    arquivos = [a for a in job.get("arquivos", []) if a]
    if not arquivos:
        return {"status": "erro_submit", "numero_protocolo": None,
                "evidencias": [], "mensagem": "Nenhum anexo (pedido medico) informado."}

    try:
        async with sessao.navegador() as page:
            await sessao.login(page)
            await _abrir_sp_sadt(page)
            await _buscar_e_selecionar_paciente(page, cpf)
            await _preencher_cabecalho(page, job["medico"])

            # Exames — HARD STOP (I1): TODOS tem que entrar, senao aborta antes
            # de qualquer ato irreversivel (nada de guia parcial).
            for item in codigos:
                codigo_portal = codigos_mod.resolver_codigo_portal(item["codigo_tuss"])
                qty = int(item.get("quantidade") or item.get("qty") or 1)
                ok, erro = await _adicionar_exame(page, codigo_portal, qty)
                if not ok:
                    await _snap(page, "erro_exame", evidencias)
                    raise SubmitAbortado(f"Exame nao adicionado: {erro}")

            # Anexos — HARD STOP (I1): TODOS tem que confirmar.
            for arquivo in arquivos:
                ok, erro = await _anexar(page, arquivo)
                if not ok:
                    await _snap(page, "erro_anexo", evidencias)
                    raise SubmitAbortado(f"Anexo nao confirmado: {erro}")

            await _snap(page, "pagina1_preenchida", evidencias)
            await _clicar_proximo(page)
            await _snap(page, "pos_proximo", evidencias)

            # Tela de resumo (/confirmar-dados) -> Enviar (irreversivel) + protocolo.
            return await _enviar_solicitacao(page, cpf, evidencias)

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
