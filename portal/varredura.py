"""
portal/varredura.py — Tempo 2: VARREDURA (Acompanhar Solicitacoes).

Fluxo confirmado pelos screenshots do portal (jun/2026):
  login -> fechar_popup -> menu "ACOMPANHAR SOLICITACAO" -> filtra Periodo ->
  Buscar -> tabela "Listar Solicitacoes" com colunas:
    Prot. | Paciente | Data | Especialidade | Medico | Tipo | Status | Opcao

A lista exibe o numero de protocolo de TODA guia (inclusive recem "Solicitado"),
o que torna a varredura tambem a fonte de fallback para correlacao quando o
protocolo nao for capturado no submit.

Raspagem robusta: identifica linha de dados por "1a celula = protocolo de 6+
digitos" — independe de id/classe da tabela.

PENDENCIA conhecida: a SENHA de autorizacao NAO aparece na lista (so' status).
Para guias AUTORIZADO, a senha exige um drill-down (abrir a guia). Deixado como
segundo passo (TODO senha) — a varredura ja' entrega protocolo + status, que e'
o que move a maquina de estados; a senha e' enriquecimento para o faturamento.
"""
import re
from datetime import datetime, timedelta

import config
from portal import sessao


# Status reais do portal -> vocabulario normalizado do contrato.
# Preservamos o texto cru em status_raw; normalizamos para a maquina de estados.
_MAPA_STATUS = {
    "AUTORIZADO": "AUTORIZADO",
    "AUTORIZADA": "AUTORIZADO",
    "LIBERADO": "AUTORIZADO",
    "NEGADO": "NEGADO",
    "NEGADA": "NEGADO",
    "INDEFERIDO": "NEGADO",
    "CANCELADO": "NEGADO",
    "SOLICITADO": "EM_ANALISE",
    "AUDITORIA": "EM_ANALISE",           # "Auditoria Administrativa"
    "ANALISE": "EM_ANALISE",
    "ANÁLISE": "EM_ANALISE",
    "ORIENTACAO": "EM_ANALISE",          # "Orientacao ao Cliente / Prestador"
    "ORIENTAÇÃO": "EM_ANALISE",
    "PENDENTE": "EM_ANALISE",
}


def _normalizar_status(texto: str) -> str:
    t = (texto or "").strip().upper()
    for chave, valor in _MAPA_STATUS.items():
        if chave in t:
            return valor
    return "DESCONHECIDO"


async def _preencher_periodo(page, data_inicio: str, data_fim: str) -> bool:
    """Preenche Periodo (data1) e Ate (data2). Seletores confirmados no portal."""
    ok_i = await _tentar_preencher(page, ['input[name="data1"]'], data_inicio)
    ok_f = await _tentar_preencher(page, ['input[name="data2"]'], data_fim)
    return ok_i and ok_f


async def _tentar_preencher(page, seletores, valor) -> bool:
    for sel in seletores:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.fill(valor)
                return True
        except Exception:
            continue
    return False


async def _clicar_buscar(page):
    for tentativa in (
        lambda: page.locator('input[name="buscar"]').first.click(),
        lambda: page.get_by_role("button", name=re.compile("Buscar", re.I)).click(),
        lambda: page.locator('input[value="Buscar"]').first.click(),
    ):
        try:
            await tentativa()
            return True
        except Exception:
            continue
    return False


async def _ir_para_acompanhar(page):
    """Menu lateral -> Acompanhar Solicitacao. Reusavel (sessao ja' logada)."""
    await page.get_by_role("link", name=re.compile("ACOMPANHAR", re.I)).first.click()
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1000)


async def _filtrar_e_raspar(page, data_inicio: str, data_fim: str) -> list[dict]:
    """Filtra o periodo, clica Buscar e raspa a tabela. Pressupoe estar na tela
    Acompanhar Solicitacoes."""
    await _preencher_periodo(page, data_inicio, data_fim)
    await _clicar_buscar(page)
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(2000)
    return await _raspar_tabela(page)


async def coletar(janela_dias: int | None = None) -> list[dict]:
    """Login, abre Acompanhar Solicitacoes, filtra a janela e raspa as guias.

    Retorna: [{numero_protocolo, status_portal, status_raw, paciente, data,
               especialidade, medico, senha?, ts}]
    """
    janela_dias = janela_dias or config.VARREDURA_JANELA_DIAS
    data_inicio = (datetime.now() - timedelta(days=janela_dias)).strftime("%d/%m/%Y")
    data_fim = datetime.now().strftime("%d/%m/%Y")

    async with sessao.navegador() as page:
        await sessao.login(page)
        await _ir_para_acompanhar(page)
        return await _filtrar_e_raspar(page, data_inicio, data_fim)


async def _raspar_tabela(page) -> list[dict]:
    """Raspa as linhas de dados da tabela de resultados. Linha de dados =
    primeira celula contem um protocolo de 6+ digitos."""
    resultado: list[dict] = []
    filas = page.locator("table tr")
    total = await filas.count()
    for i in range(total):
        celulas = filas.nth(i).locator("td")
        if await celulas.count() < 7:
            continue
        prot = (await celulas.nth(0).inner_text()).strip()
        if not re.match(r"^\d{6,}$", prot):
            continue  # cabecalho / linha vazia / nao-dados
        status_raw = (await celulas.nth(6).inner_text()).strip()
        resultado.append({
            "numero_protocolo": prot,
            "status_portal": _normalizar_status(status_raw),
            "status_raw": status_raw,
            "paciente": (await celulas.nth(1).inner_text()).strip(),
            "data": (await celulas.nth(2).inner_text()).strip(),
            "especialidade": (await celulas.nth(3).inner_text()).strip(),
            "medico": (await celulas.nth(4).inner_text()).strip(),
            "senha": None,  # TODO: drill-down para AUTORIZADO (nao esta na lista)
            "ts": datetime.now().isoformat(),
        })
    return resultado


# ── Captura do protocolo pos-gravar VIA LISTA (cirurgia 1.1, reusando a lista) ──
import unicodedata


def _normalizar_nome(n: str) -> str:
    """Tira o prefixo 'NNN - ', acentos e caixa, para casar nomes da lista
    (que vem truncados) com o nome do paciente do job."""
    n = re.sub(r"^\s*\d+\s*-\s*", "", n or "")
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode("ascii")
    return " ".join(n.upper().split())


def _nomes_casam(real: str, lista: str) -> bool:
    """A lista trunca nomes longos; o mais curto deve ser prefixo do mais longo.
    Exige minimo de 6 chars para evitar casamento trivial."""
    a, b = sorted([real, lista], key=len)
    return len(a) >= 6 and b.startswith(a)


def _parse_data(s: str):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


async def buscar_protocolo_na_lista(page, nome_paciente: str, apos: datetime):
    """Acha o protocolo da guia recem-criada na lista Acompanhar Solicitacoes.

    CONSERVADOR de proposito: so' retorna se houver UM candidato confiavel —
    nome do paciente casando + timestamp >= momento do gravar (com folga).
    Pegar o protocolo ERRADO correlaciona a guia ao paciente errado no HOP, o
    que e' pior do que nao pegar. Em qualquer ambiguidade, retorna None
    (-> requer_captura_manual; humano confere pelo screenshot).

    Opera na MESMA sessao/page ja' logada (chamado logo apos o gravar).
    """
    real = _normalizar_nome(nome_paciente)
    if len(real) < 6:
        return None  # nome insuficiente para casar com seguranca

    await _ir_para_acompanhar(page)
    hoje = datetime.now().strftime("%d/%m/%Y")
    linhas = await _filtrar_e_raspar(page, hoje, hoje)

    folga = apos - timedelta(minutes=2)
    candidatos = []
    for r in linhas:
        if not _nomes_casam(real, _normalizar_nome(r["paciente"])):
            continue
        dt = _parse_data(r["data"])
        if dt and dt >= folga:
            candidatos.append((dt, r["numero_protocolo"]))

    if not candidatos:
        return None
    candidatos.sort()              # a guia recem-criada e' a mais recente que casa
    return candidatos[-1][1]
