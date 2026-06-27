"""
adapters/sassepe/varredura.py — Tempo 2 (VARREDURA) do adapter Sassepe.

Fonte mapeada no portal real: Solicitacoes -> Historicos -> "Historico de
solicitacoes" (/solicitacoes/historico/solicitacao). Lista de CARDS (nao tabela)
ordenados do mais recente para o mais antigo. Cada card (innerText):

  "Guia de SP/SADT - Número da guia: 1189780 Data de emissão da guia:
   26/06/2026 Prestador: IMAG Autorizada Beneficiário: AUREA ... CPF:
   643.877.204-68 Cartão do beneficiário: SASSE059837004"

Campos extraidos: numero da guia (= protocolo), status (Autorizada/Em analise/
Negada...), beneficiario, cpf, cartao, data. status_raw e' preservado (literal);
status_portal e' normalizado para o vocabulario do contrato.

Tambem expoe buscar_guia_por_cpf(): captura conservadora (I3) do protocolo
pos-envio, casando por CPF (exato) + data de hoje + maior numero (mais recente).
"""
import re
import unicodedata
from datetime import datetime, timedelta

from . import sessao

HISTORICO_URL = "https://sassepe.maida.health/solicitacoes/historico/solicitacao"

# Rotulos REAIS do Sassepe -> vocabulario normalizado do contrato.
_MAPA_STATUS = {
    "AUTORIZAD": "AUTORIZADO",          # Autorizada / Autorizado
    "LIBERAD": "AUTORIZADO",
    "DEFERID": "AUTORIZADO",
    "NEGAD": "NEGADO",                  # Negada / Negado
    "INDEFERID": "NEGADO",
    "CANCELAD": "NEGADO",
    "RECUSAD": "NEGADO",
    "EM ANALISE": "EM_ANALISE",         # "Em análise" (sem acento apos normalizar)
    "ANALISE": "EM_ANALISE",
    "PENDENTE": "EM_ANALISE",
    "AGUARDAND": "EM_ANALISE",
    "AUDITORIA": "EM_ANALISE",
}

# Tokens de status na ordem de busca (para extrair o status_raw literal).
_TOKENS_STATUS = [
    "Autorizada", "Autorizado", "Em análise", "Em analise", "Negada", "Negado",
    "Cancelada", "Indeferida", "Pendente", "Em auditoria",
]


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def _normalizar_status(texto: str) -> str:
    t = _sem_acento(texto).strip().upper()
    for chave, valor in _MAPA_STATUS.items():
        if chave in t:
            return valor
    return "DESCONHECIDO"


def _parse_card(texto: str) -> dict | None:
    """Extrai os campos de um card do historico. Retorna None se nao for card."""
    t = re.sub(r"\s+", " ", texto or "").strip()
    m_guia = re.search(r"Número da guia:\s*(\d+)", t)
    if not m_guia:
        return None
    m_data = re.search(r"Data de emissão da guia:\s*(\d{2}/\d{2}/\d{4})", t)
    m_benef = re.search(r"Beneficiário:\s*(.*?)\s*CPF:", t)
    m_cpf = re.search(r"CPF:\s*([\d.\-]+)", t)
    m_cartao = re.search(r"Cartão do beneficiário:\s*(\S+)", t)

    status_raw = ""
    for tok in _TOKENS_STATUS:
        if tok.lower() in t.lower():
            status_raw = tok
            break

    return {
        "numero_protocolo": m_guia.group(1),
        "status_portal": _normalizar_status(status_raw or t),
        "status_raw": status_raw,
        "paciente": m_benef.group(1).strip() if m_benef else "",
        "cpf": m_cpf.group(1) if m_cpf else "",
        "cartao": m_cartao.group(1) if m_cartao else "",
        "data": m_data.group(1) if m_data else "",
        "senha": None,  # nao exibida na lista; enriquecimento futuro (TODO)
        "ts": datetime.now().isoformat(),
    }


async def _ir_para_historico(page):
    """Abre a tela de Historico de solicitacoes (sessao ja' logada)."""
    await page.goto(HISTORICO_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(3500)


async def _raspar_pagina(page) -> list[dict]:
    """Raspa os cards da pagina atual do historico. Card = menor elemento que
    contem 'Número da guia' + 'Beneficiário' (independe de classe)."""
    textos = await page.evaluate(
        """() => {
          const all = Array.from(document.querySelectorAll('*'));
          const cand = all.filter(e => {
            const t = e.textContent || '';
            const r = e.getBoundingClientRect();
            return t.includes('Número da guia') && t.includes('Beneficiário')
              && r.width > 0 && r.height > 40 && r.height < 300;
          });
          cand.sort((a, b) =>
            a.getBoundingClientRect().height - b.getBoundingClientRect().height);
          const seen = new Set(); const out = [];
          for (const e of cand) {
            const t = e.textContent.replace(/\\s+/g, ' ').trim();
            const m = t.match(/Número da guia:\\s*(\\d+)/);
            if (!m || seen.has(m[1])) continue;
            seen.add(m[1]); out.push(t);
          }
          return out;
        }"""
    )
    return [c for c in (_parse_card(x) for x in textos) if c]


def _parse_data(s: str):
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y")
    except ValueError:
        return None


async def coletar(janela_dias: int | None = None) -> list[dict]:
    """Login -> Historico de solicitacoes -> raspa as guias da janela.

    A lista vem ordenada do mais recente para o mais antigo. Pagina enquanto a
    data dos cards estiver dentro da janela (para na 1a pagina toda fora dela).
    Retorna [{numero_protocolo, status_portal, status_raw, paciente, cpf,
              cartao, data, senha?, ts}].
    """
    janela_dias = janela_dias or 15
    corte = datetime.now() - timedelta(days=janela_dias)

    async with sessao.navegador() as page:
        await sessao.login(page)
        await _ir_para_historico(page)

        guias: list[dict] = []
        for _ in range(50):  # teto de paginas (seguranca)
            cards = await _raspar_pagina(page)
            if not cards:
                break
            dentro = [c for c in cards if (_parse_data(c["data"]) or datetime.now()) >= corte]
            guias.extend(dentro)
            # se algum card desta pagina ja' caiu fora da janela, encerramos.
            if any((_parse_data(c["data"]) or datetime.now()) < corte for c in cards):
                break
            if not await _proxima_pagina(page):
                break

        # dedup por numero (paginacao pode repetir borda)
        vistos, unicas = set(), []
        for g in guias:
            if g["numero_protocolo"] in vistos:
                continue
            vistos.add(g["numero_protocolo"])
            unicas.append(g)
        return unicas


async def _proxima_pagina(page) -> bool:
    """Clica 'Próxima' na paginacao do historico. False se nao houver/ultima."""
    try:
        botao = page.get_by_text("Próxima", exact=False).first
        if await botao.count() == 0:
            return False
        await botao.click(timeout=5000)
        await page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


# ── Captura conservadora do protocolo pos-envio (I3) ─────────────────────────
def _so_digitos(s: str) -> str:
    return "".join(filter(str.isdigit, s or ""))


async def buscar_guia_por_cpf(page, cpf: str, data_hoje: str) -> str | None:
    """Acha o numero da guia recem-criada no historico, casando por CPF (exato)
    + data de hoje. Conservador (I3): se houver ambiguidade impossivel de
    resolver, retorna o MAIOR numero (mais recente) entre os que casam; se
    nenhum casar, retorna None (-> requer_captura_manual).

    Opera na mesma sessao ja' logada (chamado logo apos o envio)."""
    alvo = _so_digitos(cpf)
    if len(alvo) != 11:
        return None
    await _ir_para_historico(page)
    cards = await _raspar_pagina(page)
    casam = [
        c for c in cards
        if _so_digitos(c["cpf"]) == alvo and c["data"] == data_hoje
        and c["numero_protocolo"].isdigit()
    ]
    if not casam:
        return None
    casam.sort(key=lambda c: int(c["numero_protocolo"]))
    return casam[-1]["numero_protocolo"]  # mais recente
