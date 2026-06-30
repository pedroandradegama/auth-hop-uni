"""
adapters/sulamerica/varredura.py — Tempo 2 (VARREDURA) do adapter Sul America.

Fonte mapeada no portal real: Segurado -> Validacao de Procedimentos ->
Consulta (.../validacao-de-procedimentos/consulta/). Form de busca (jQuery,
server-rendered) com radios 'tipo-pesquisa' e uma TABELA de resultado cujas
linhas (6 celulas) sao:

  [Nº Guia, Nº Guia Prestador, Nome+Carteirinha(20 dig), Data/Hora, Tipo, Status]

- Nº Guia       = PROTOCOLO real da autorizacao.
- Nº Guia Prestador = numero que NOS geramos no submit (deterministico p/ casar).
- Nome+Carteirinha: o nome do segurado vem colado nos 20 digitos da carteira.

Duas saidas:
  - coletar(janela_dias): raspa por PERIODO e normaliza status (cron).
  - buscar_guia_por_prestador(page, guia_prestador): captura conservadora (I3)
    do protocolo pos-envio, casando pelo numero do prestador (unico).
"""
import re
import unicodedata
from datetime import datetime, timedelta

from . import sessao, config

CONSULTA_URL = (
    "https://saude.sulamericaseguros.com.br/prestador/segurado/"
    "validacao-de-procedimentos-tiss-3/validacao-de-procedimentos/consulta/"
)

# Rotulos do portal -> vocabulario normalizado do contrato.
_MAPA_STATUS = {
    "AUTORIZAD": "AUTORIZADO",          # Autorizado / Autorizado parcialmente
    "LIBERAD": "AUTORIZADO",
    "DEFERID": "AUTORIZADO",
    "APROVAD": "AUTORIZADO",
    "NEGAD": "NEGADO",
    "INDEFERID": "NEGADO",
    "CANCELAD": "NEGADO",               # Solicitacao cancelada
    "RECUSAD": "NEGADO",
    "EM ANALISE": "EM_ANALISE",
    "ANALISE": "EM_ANALISE",
    "PENDENTE": "EM_ANALISE",
    "AGUARDAND": "EM_ANALISE",          # Aguardando OPME / justificativa
    "AUDITORIA": "EM_ANALISE",
    "RASCUNHO": "DESCONHECIDO",         # Em rascunho (nao enviada de fato)
}

# JS que raspa as linhas reais da tabela de resultado (6 a 8 tds, com SP/SADT).
_JS_RASPAR = r"""(function(){
  var rows = Array.from(document.querySelectorAll("tr"));
  var out = [];
  for (const tr of rows){
    var tds = Array.from(tr.querySelectorAll("td"));
    if (tds.length < 5 || tds.length > 8) continue;
    var c = tds.map(td => td.textContent.replace(/\s+/g," ").trim());
    if (c.join(" ").indexOf("SP/SADT") >= 0) out.push(c);
  }
  // dedup (o portal as vezes duplica a 1a linha com lixo de script)
  var seen = new Set(); var uniq = [];
  for (const c of out){ var k = c.join("|"); if(!seen.has(k)){ seen.add(k); uniq.push(c); } }
  return JSON.stringify(uniq);
})()"""


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def normalizar_status(texto: str) -> str:
    t = _sem_acento(texto).strip().upper()
    for chave, valor in _MAPA_STATUS.items():
        if chave in t:
            return valor
    return "DESCONHECIDO"


def _so_digitos(s: str) -> str:
    return "".join(filter(str.isdigit, s or ""))


def _parse_linha(c: list) -> dict | None:
    """Converte uma linha (lista de celulas) num registro do contrato.
    Layout: [Nº Guia, Nº Guia Prestador, Nome+Carteira(20), Data/Hora, Tipo, Status].
    Defensivo: localiza pelos formatos (status no fim, data dd/mm/yyyy)."""
    if len(c) < 5:
        return None
    # ultima celula com status reconhecido
    status_raw = c[-1].strip()
    # celula de data/hora
    data = ""
    m = None
    for cel in c:
        m = re.search(r"\b(\d{2}/\d{2}/\d{4})", cel)
        if m:
            data = m.group(1)
            break
    # celula nome+carteira: tem LETRA seguida de 20 digitos no fim (evita casar
    # a celula do guia-prestador, que pode ser 20 zeros puros).
    nome, carteira = "", ""
    for cel in c:
        if not re.search(r"[A-Za-z]", cel):
            continue
        mc = re.search(r"(\d{20})\s*$", cel.replace(" ", ""))
        if mc:
            carteira = mc.group(1)
            nome = re.sub(r"\s*\d{20}\s*$", "", cel).strip()
            break
    guia = _so_digitos(c[0]) or None
    return {
        "numero_protocolo": guia,
        "status_portal": normalizar_status(status_raw),
        "status_raw": status_raw,
        "carteirinha": carteira,
        "paciente": nome,
        "data": data,
        "senha": None,
        "ts": datetime.now().isoformat(),
    }


async def _selecionar_radio(page, radio_id: str):
    await page.evaluate(
        "(id) => { const r = document.getElementById(id); if (r) r.click(); }",
        radio_id,
    )
    await page.wait_for_timeout(600)


async def _set_campo(page, campo_id: str, valor: str):
    """Seta valor num input jQuery (value direto + eventos) — fill char-a-char
    quebra por causa da mascara do portal."""
    await page.evaluate(
        """([id, v]) => {
          const e = document.getElementById(id);
          if (!e) return;
          e.value = v;
          e.dispatchEvent(new Event('input', {bubbles: true}));
          e.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        [campo_id, valor],
    )
    await page.wait_for_timeout(300)


async def _pesquisar(page):
    await page.evaluate(
        "() => { const b = document.getElementById('btn-pesquisar-solicitacao'); "
        "if (b) b.click(); }"
    )
    await page.wait_for_timeout(4000)


async def _ir_para_consulta(page):
    await page.goto(CONSULTA_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)


async def buscar_guia_por_prestador(page, guia_prestador: str) -> str | None:
    """Captura conservadora (I3) do protocolo pos-envio: busca a Consulta pelo
    'Número Guia Prestador' (o numero que geramos) e devolve o 'Nº Guia' (=
    protocolo). Retorna None se nao casar EXATAMENTE 1 linha (-> captura manual).

    Opera na mesma sessao ja' logada (chamado logo apos o Confirmar)."""
    alvo = _so_digitos(guia_prestador)
    if not alvo:
        return None
    await _ir_para_consulta(page)
    await _selecionar_radio(page, "protocolo-prestador")
    await _set_campo(page, "busca-numero-guia-prestador", alvo)
    await _pesquisar(page)

    import json
    linhas = json.loads(await page.evaluate(_JS_RASPAR))
    casam = []
    for c in linhas:
        # acha a celula do prestador (== alvo) e pega a Nº Guia imediatamente antes
        idx = next((i for i, cel in enumerate(c) if _so_digitos(cel) == alvo), None)
        if idx is None or idx == 0:
            continue
        guia = _so_digitos(c[idx - 1])
        if guia and guia != alvo:
            casam.append(guia)
    casam = list(dict.fromkeys(casam))
    return casam[0] if len(casam) == 1 else None


def _parse_data(s: str):
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y")
    except ValueError:
        return None


async def coletar(janela_dias: int | None = None) -> list[dict]:
    """Login -> Consulta -> busca por PERIODO (janela) -> raspa e normaliza.
    Retorna [{numero_protocolo, status_portal, status_raw, carteirinha,
              paciente, data, senha?, ts}]."""
    janela_dias = janela_dias or 15
    hoje = datetime.now()
    ini = (hoje - timedelta(days=janela_dias)).strftime("%d/%m/%Y")
    fim = hoje.strftime("%d/%m/%Y")

    async with sessao.navegador() as page:
        await sessao.login(page)
        await _ir_para_consulta(page)
        await _selecionar_radio(page, "periodo")
        await _set_campo(page, "data-inicial", ini)
        await _set_campo(page, "data-final", fim)
        await _pesquisar(page)

        import json
        linhas = json.loads(await page.evaluate(_JS_RASPAR))
        registros = [r for r in (_parse_linha(c) for c in linhas) if r and r["numero_protocolo"]]

        # dedup por numero de guia
        vistos, unicos = set(), []
        for r in registros:
            if r["numero_protocolo"] in vistos:
                continue
            vistos.add(r["numero_protocolo"])
            unicos.append(r)
        return unicos
