"""
adapters/sassepe/_ui.py — Mecanica de UI do portal Sassepe (SPA React).

O Sassepe e' um SPA React. TODO dropdown e' um [role=listbox] com LAZY-LOAD:
a lista so' renderiza ~5 itens ate' um WheelEvent ser disparado DIRETAMENTE no
elemento [role=listbox]. scroll()/scrollTop NAO disparam o carregamento — esse
detalhe foi descoberto no piloto e e' o coracao de toda interacao com dropdown.

Esta mecanica foi validada no piloto (browser-harness/CDP) e aqui esta' portada
para Playwright preservando o metodo exato que funcionou:
  - geometria do label via page.evaluate (getBoundingClientRect)
  - clique no input por coordenada (label.x + largura/2, label.y + 35)
  - selecao do texto (Control+a) e digitacao via keyboard
  - WheelEvent disparado no [role=listbox] (lazy-load)
  - clique na opcao por texto dentro do listbox (exato, com fallback "includes")

Inputs React: NUNCA setar input.value via JS (nao dispara o estado). Sempre
clicar + digitar pelo teclado (page.keyboard), como aqui.
"""
import difflib
import json
import unicodedata
from dataclasses import dataclass
from enum import Enum

from . import config

# Tolerancia a erro de grafia no nome do medico (ver casa_tokens). 0.82 aceita
# letra transposta e troca de uma letra em sobrenome de tamanho normal, e recusa
# sobrenomes genuinamente diferentes:
#   CALVACANTI x CAVALCANTI = 0.90  (transposicao — aceita)
#   MACEDO     x MACHADO    = 0.77  (pessoas diferentes — recusa)
# Polls consecutivos de 'Nenhum resultado' para aceitar o vazio como
# resposta e nao como resquicio da busca anterior (~450ms).
_VAZIO_ESTAVEL = 3

LIMIAR_FUZZY = 0.82

# Abaixo disto, exigimos casamento EXATO. Token curto tem pouca informacao e
# fuzzy nele casa quase tudo ("LUZ" x "CRUZ" = 0.86).
MIN_TOKEN_FUZZY = 5


class MotivoCampo(str, Enum):
    """Por que um dropdown do formulario nao ficou preenchido.

    Ate' 29/09 tudo isso virava `False` e, no chamador, `SubmitAbortado` ->
    `ESTADO_INESPERADO` -> agente de fallback. Cinco situacoes com tratamento
    diferente recebiam a mesma resposta: o agente era acionado para casos que
    ele nao resolve (custo medido em 24h: 25 fallbacks, 192 passos, US$ 0,96),
    e o operador lia "campo nao preenchido" sem saber qual delas ocorreu.
    """
    OK = "ok"
    CAMPO_AUSENTE = "campo_ausente"              # label nao esta' na tela
    SEM_RESPOSTA = "sem_resposta"                # digitou e o portal ficou mudo
    LISTA_VAZIA = "lista_vazia"                  # respondeu "Nenhum resultado"
    RESPOSTA_INCOERENTE = "resposta_incoerente"  # respondeu outra consulta
    OPCAO_AUSENTE = "opcao_ausente"              # respondeu, e o alvo nao esta' la'
    CLIQUE_SEM_EFEITO = "clique_sem_efeito"      # alvo na lista, clique nao pegou


@dataclass(frozen=True)
class ResultadoCampo:
    motivo: MotivoCampo
    detalhe: str = ""
    opcoes: tuple = ()

    @property
    def ok(self) -> bool:
        return self.motivo is MotivoCampo.OK

    def __bool__(self) -> bool:   # `if not resultado:` continua legivel
        return self.ok


def _norm(s: str) -> str:
    """Maiuscula, sem acento, espacos colapsados (para casar nomes)."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _token_casa(tok: str, registro: list[str], limiar: float) -> bool:
    """Um token do nome buscado esta' presente no registro do portal?

    Exato sempre vale. Com limiar < 1.0, aceita tambem o token mais parecido
    acima do limiar — desde que seja longo o bastante (MIN_TOKEN_FUZZY).
    """
    if tok in registro:
        return True
    if limiar >= 1.0 or len(tok) < MIN_TOKEN_FUZZY:
        return False
    return any(
        len(r) >= MIN_TOKEN_FUZZY
        and difflib.SequenceMatcher(None, tok, r).ratio() >= limiar
        for r in registro
    )


def casa_tokens(tokens: list[str], registro: list[str], limiar: float = 1.0) -> bool:
    """TODOS os tokens buscados tem que estar no registro (I3 continua valendo:
    quem decide entre homonimos e' a unicidade do candidato, nao esta funcao).

    Funcao pura — testavel sem browser (tests/test_solicitante_fuzzy.py).
    """
    return bool(tokens) and all(_token_casa(t, registro, limiar) for t in tokens)


def filtrar_candidatos(opcoes: list[str], tokens: list[str],
                       limiar: float = 1.0) -> list[str]:
    """Das opcoes do listbox ('CRM - NOME'), quais casam com os tokens buscados.
    Preserva a ordem e remove repetidas. Funcao pura."""
    achados = []
    for op in opcoes:
        parte_nome = op.split("-", 1)[1] if "-" in op else op
        if casa_tokens(tokens, _norm(parte_nome).split(), limiar):
            achados.append(op)
    return list(dict.fromkeys(achados))


def _sem_tratamento(n: str) -> str:
    """Tira 'Dr.'/'Dra.' de um nome ja' em caixa alta."""
    for p in ("DRA.", "DR.", "DRA", "DR"):
        if n == p:
            return ""
        if n.startswith(p + " "):
            return n[len(p):].strip()
    return n


def nome_para_busca(nome: str) -> str:
    """Nome COM acento, para digitar no portal.

    O portal guarda e casa acentos ('IVO ALVES DE FRANCA' aparece como 'FRANÇA',
    e ha' 'NADIA'/'NÁDIA', 'FLAVIA'/'FLÁVIA' no cadastro). Digitar a versao sem
    acento pode nao casar nada: em 30/09 (job 0d4466b9) 'ALICE LECA VITAL DO
    CARMO' e 'ALICE LECA' devolveram "Nenhum resultado", enquanto o cadastro do
    job traz 'ALICE LEÇA VITAL DO CARMO'.

    A normalizacao sem acento continua valendo para CASAR o que o portal
    devolveu — la' ela e' tolerancia, aqui era mutilacao do termo.
    """
    return _sem_tratamento(" ".join((nome or "").upper().split()))


def limpar_nome_medico(nome: str) -> str:
    """Remove prefixo de tratamento (Dr./Dra.) e normaliza SEM acento. Usado
    para casar o registro do portal, nao para buscar (ver `nome_para_busca`)."""
    return _sem_tratamento(_norm(nome))

# JS reutilizado: acha o N-esimo label pelo texto (com ou sem "*") e devolve o
# rect. `indice` resolve labels DUPLICADOS (ex.: "Código CBO" aparece nas secoes
# solicitante E executante — indice 0 e 1 respectivamente).
_JS_RECT_LABEL = """
([label_text, indice]) => {
  const labels = Array.from(document.querySelectorAll('*')).filter(e => {
    const t = e.textContent.trim();
    return (t === label_text + '*' || t === label_text)
      && e.getBoundingClientRect().width > 0;
  });
  const label = labels[indice];
  if (!label) return null;
  const r = label.getBoundingClientRect();
  return {lx: r.x, ly: r.y, lw: r.width};
}
"""

_JS_SCROLL_LABEL = """
([label_text, indice]) => {
  const labels = Array.from(document.querySelectorAll('*')).filter(e => {
    const t = e.textContent.trim();
    return (t === label_text + '*' || t === label_text)
      && e.getBoundingClientRect().width > 0;
  });
  const label = labels[indice];
  if (label) label.scrollIntoView({block: 'center'});
  return !!label;
}
"""

# WheelEvent NO PROPRIO listbox — scroll por coordenada e scrollTop nao
# disparam o handler React que carrega o lote seguinte.
#
# Tres eventos por chamada, com delta maior, e tambem no descendente que de fato
# rola: em 30/09 a lista do solicitante travou em 10 itens e `expandir_listbox`
# nao a fez crescer (`termo='ALICE' apos expandir: opcoes=10`). Um unico wheel
# de 300px nao chega ao fim de uma lista de 10 linhas, e o portal so' pede o
# proximo lote quando o scroll encosta no fim.
_JS_WHEEL_LISTBOX = """
() => {
  const lb = document.querySelector('[role=listbox]');
  if (!lb) return {encontrado: false};
  const rolavel = (el) => el.scrollHeight - el.clientHeight > 4;
  let alvo = lb;
  if (!rolavel(alvo)) {
    alvo = Array.from(lb.querySelectorAll('*')).find(rolavel) || lb;
  }
  const antes = {scrollTop: alvo.scrollTop, scrollHeight: alvo.scrollHeight,
                 clientHeight: alvo.clientHeight};
  const ev = () => new WheelEvent('wheel',
    {deltaY: 800, bubbles: true, cancelable: true, composed: true});
  const despachados = [];
  for (let i = 0; i < 3; i++) { despachados.push(alvo.dispatchEvent(ev())); }
  return {encontrado: true, tag: alvo.tagName, antes, despachados,
          depois: {scrollTop: alvo.scrollTop, scrollHeight: alvo.scrollHeight,
                   clientHeight: alvo.clientHeight}};
}
"""


# Leitura sem efeitos colaterais, feita apenas quando
# SASSEPE_TELEMETRIA_DROPDOWN=true. Ela mostra se o elemento que recebeu o
# WheelEvent realmente e' rolavel e se o browser moveu scrollTop — a distincao
# que falta para separar "portal nao carregou" de "wheel sintetico nao rolou".
_JS_METRICAS_LISTBOX = """
() => {
  const lb = document.querySelector('[role=listbox]');
  if (!lb) return {aberto: false};
  const rolavel = (el) => el.scrollHeight - el.clientHeight > 4;
  const alvo = rolavel(lb)
    ? lb
    : Array.from(lb.querySelectorAll('*')).find(rolavel) || lb;
  const medida = (el) => ({tag: el.tagName, scrollTop: el.scrollTop,
    scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,
    maxScroll: Math.max(0, el.scrollHeight - el.clientHeight)});
  return {aberto: true, listbox: medida(lb), alvo: medida(alvo)};
}
"""


# Estado do listbox, em UMA leitura. O portal renderiza DOIS placeholders como
# filhos do proprio listbox — "Nenhum resultado" (busca terminou vazia) e
# "carregando" (busca em voo) — e os dois tem texto, entao qualquer criterio por
# contagem de filhos confunde "ja' respondeu" com "ainda esta' respondendo".
# Distinguir os tres estados e' o que permite esperar o spinner e NAO esperar o
# vazio (28/09: quatro buscas de solicitante desistiram no spinner em 6s).
# ── Fonte UNICA de "o que e' opcao real" ──────────────────────────────────────
# O portal renderiza dois placeholders como filhos do listbox ("Nenhum
# resultado" e o spinner "carregando"). Tres copias divergentes deste criterio
# produziram tres defeitos em cinco dias:
#   25/09  o poll parava em `children.length > 0`    -> placeholder encerrava a espera
#   28/09  o filtro descartava so' "Nenhum resultado" -> o spinner virou opcao
#   29/09  `_JS_PRIMEIRA_OPCAO` tinha a sua propria copia -> o CBO clicou no spinner
# Agora ha' um fragmento so'. Quem precisa de coordenada usa o INDICE devolvido
# aqui, e o JS de coordenada nao tem logica de filtro nenhuma.
_JS_ELS = """
  const lb = document.querySelector('[role=listbox]');
  let els = lb ? Array.from(lb.querySelectorAll('[role=option]')) : null;
  if (els !== null && !els.length) els = Array.from(lb.children);
"""

_JS_LISTBOX_ESTADO = """
() => {
""" + _JS_ELS + """
  if (els === null) return {estado: 'fechado', opcoes: [], indices: []};
  const norm = (t) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
                       .toLowerCase().trim();
  const vazio = (t) => /^nenhum resultado/.test(t);
  const carregando = (t) => !t || /^carregando/.test(t) || /^loading/.test(t)
                            || /^buscando/.test(t);
  let viuVazio = false, viuCarregando = false;
  const seen = new Set(); const out = []; const idx = [];
  for (let i = 0; i < els.length; i++) {
    const t = (els[i].textContent || '').trim();
    const n = norm(t);
    if (vazio(n)) { viuVazio = true; continue; }
    if (carregando(n)) { viuCarregando = true; continue; }
    if (t.length > 2 && !seen.has(t)) { seen.add(t); out.push(t); idx.push(i); }
  }
  if (out.length) return {estado: 'ok', opcoes: out, indices: idx};
  if (viuCarregando) return {estado: 'carregando', opcoes: [], indices: []};
  if (viuVazio) return {estado: 'vazio', opcoes: [], indices: []};
  return {estado: 'fechado', opcoes: [], indices: []};
}
"""

# Coordenada do N-esimo elemento do listbox. SEM criterio de filtro: recebe o
# indice que `_JS_LISTBOX_ESTADO` ja' classificou como opcao real.
_JS_COORD_POR_INDICE = """
(i) => {
""" + _JS_ELS + """
  if (els === null) return null;
  const el = els[i];
  if (!el) return null;
  el.scrollIntoView({block: 'nearest'});
  const r = el.getBoundingClientRect();
  return {cx: r.x + r.width / 2, cy: r.y + r.height / 2,
          texto: (el.textContent || '').trim()};
}
"""


async def ler_listbox(page) -> dict:
    """Estado + opcoes do listbox. Nunca levanta (navegacao do SPA derruba o
    evaluate no meio); nesse caso devolve 'fechado', que o poll trata como
    "ainda nao sei"."""
    try:
        estado = await page.evaluate(_JS_LISTBOX_ESTADO)
    except Exception:
        return {"estado": "fechado", "opcoes": [], "indices": []}
    return estado or {"estado": "fechado", "opcoes": [], "indices": []}


async def opcoes_do_listbox(page) -> list:
    return (await ler_listbox(page)).get("opcoes") or []


async def diagnostico_listbox(page) -> dict:
    """Snapshot do DOM do dropdown para um canario, sem interagir com ele."""
    try:
        metricas = await page.evaluate(_JS_METRICAS_LISTBOX)
    except Exception as e:
        return {"erro": f"metricas_listbox: {type(e).__name__}: {e}"}
    leitura = await ler_listbox(page)
    return {"metricas": metricas, "estado": leitura.get("estado"),
            "qtd_opcoes": len(leitura.get("opcoes") or []),
            "amostra": (leitura.get("opcoes") or [])[:8]}


async def _telemetria_listbox(page, evento: str, **contexto) -> None:
    """Emite uma linha JSON correlacionavel; nunca altera o fluxo nem falha."""
    if not config.telemetria_dropdown_habilitada():
        return
    dado = await diagnostico_listbox(page)
    print("[sassepe.dropdown] " + json.dumps(
        {"evento": evento, **contexto, **dado}, ensure_ascii=False,
        default=str), flush=True)


def opcoes_coerentes(opcoes: list, termo: str) -> bool:
    """As opcoes correspondem AO TERMO digitado?

    Criterio mais forte que "a lista mudou": o portal filtra pelo que esta'
    visivel na opcao — busca por CRM devolve linhas prefixadas por aquele CRM,
    busca por nome devolve linhas que contem o nome. Se nenhuma opcao contem o
    primeiro token do termo, o que esta' na tela ainda e' resposta de outra
    consulta.

    Caso real (29/09, job 0d4466b9): buscas por '42085', 'ALICE LECA VITAL DO
    CARMO' e 'ALICE LECA' devolveram as MESMAS cinco linhas (RUBEM, RICARDO,
    ELAINE, DIEGO, DANIEL) — uma lista filtrada por CRM sendo entregue como se
    fosse resposta a uma busca por nome. O criterio "mudou desde antes de
    digitar" nao pega isso quando a assinatura anterior nao pode ser lida.
    """
    alvo = _norm(termo).split()
    if not alvo:
        return True
    # TODOS os tokens. Conferir so' o primeiro deixa passar a lista da consulta
    # ANTERIOR quando os dois termos comecam igual — medido em 30/09:
    #   termo='ALICE LECA VITAL DO CARMO' estado='ok' opcoes=5:
    #     ['91762 - ACSA ALICE MARTINS ARAUJO', '91370 - ADRIANA ALICE ...', ...]
    # que e' o resultado do termo anterior ('ALICE'). Uma resposta de verdade
    # conteria 'LECA' tambem. Sobrenome extra no registro continua casando
    # ('NUBIA ROSA LOPES' ⊂ 'NUBIA ROSA LOPES FREIRE').
    return any(all(t in _norm(o) for t in alvo) for o in opcoes)


async def _assinatura_listbox(page) -> str | None:
    """Impressao digital do conteudo atual do listbox (None se fechado)."""
    leitura = await ler_listbox(page)
    if leitura.get("estado") == "fechado":
        return None
    return "|".join(leitura.get("opcoes") or []) or f"<{leitura.get('estado')}>"


async def _esperar_listbox(page, timeout_ms: int, passo_ms: int = 150,
                           teto_carregando_ms: int = 12000,
                           assinatura_anterior: str | None = None,
                           termo: str | None = None) -> bool:
    """Poll ate' o listbox trazer OPCAO REAL. Tres estados, tres politicas.

    - 'ok'          -> sai na hora (e' daqui que vem o ganho de tempo de 25/09).
    - 'carregando'  -> o portal esta' respondendo: ESPERA, ate' teto_carregando_ms.
                       O spinner e' evidencia positiva de trabalho em curso; parar
                       nele e' concluir "nao existe" sem ter visto a resposta.
    - 'vazio'       -> "Nenhum resultado" e' a resposta terminal: sai cedo, mas so'
                       depois de estavel, porque o portal pinta o vazio da busca
                       ANTERIOR por alguns frames antes de trocar pelo spinner.
    - 'fechado'     -> nada ainda: espera ate' timeout_ms.

    `assinatura_anterior` e' o conteudo do listbox ANTES de digitar o termo. Com
    ele, 'ok' so' vale quando a lista MUDOU — sem isso a espera aceita a lista da
    consulta anterior, que sao opcoes reais e por isso passam por 'ok'. Medido em
    28/09: buscas por '37499', 'RODRIGO REBELLO FRANCA' e 'RODRIGO REBELLO'
    devolveram as mesmas cinco linhas da cabeca alfabetica do cadastro (AABENMA,
    AALAN, AALEC, AARAO, AARAO) — a lista sem filtro. So' o ultimo termo pegou o
    resultado certo, por acaso de tempo. Efeito pratico: a busca por CRM, a mais
    especifica e a razao de mandarmos o CRM, era descartada em toda execucao, e o
    adapter decidia sempre pelo termo mais fraco (primeiro nome sozinho).

    Historico desta funcao, que e' o proprio argumento para os tres estados:
    `eda1623` (25/09) trocou esperas fixas por poll com criterio
    `listbox.children.length > 0` — o "Nenhum resultado" conta como filho, entao
    a espera acabava em ~150ms. `0c1e59d` (28/09) passou a exigir opcao real, mas
    o filtro so' descartava "Nenhum resultado": o spinner "carregando" virou
    opcao, e a espera continuou acabando em ~150ms. Nos dois casos o adapter
    concluiu "o portal nao tem esse registro" sem nunca ter visto a resposta.
    """
    vazio_seguido = 0
    gasto = 0
    prazo = max(timeout_ms, passo_ms)
    while gasto < prazo and gasto < teto_carregando_ms:
        leitura = await ler_listbox(page)
        estado = leitura.get("estado")
        if estado == "ok":
            opcoes = leitura.get("opcoes") or []
            if termo:
                # COERENCIA BASTA. Se a lista ja' contem o que foi pedido, ela
                # responde ao termo — exigir que ela MUDE quebra os dropdowns
                # que nao filtram por digitacao.
                #
                # Regressao de a34a30b, vista em 30/09: 'Regime de Atendimento'
                # deu `sem_resposta` em 4 de 4 ciclos. E' uma lista estatica
                # curta ("01 - Ambulatorial", "02 - Hospitalar", ...) que nao
                # filtra; digitar nao muda nada, entao a espera nunca terminava.
                # O campo funcionava ate' 23/09, antes de eu exigir a mudanca.
                #
                # A protecao contra lista velha continua: em 28/09 a busca por
                # '37499' devolvia a cabeca alfabetica do cadastro, que NAO
                # contem '37499' — incoerente, rejeitada.
                aceita = opcoes_coerentes(opcoes, termo)
            else:
                # Sem termo (filtro limpo) nao ha' o que conferir; o unico sinal
                # de que o portal reagiu e' o conteudo ter mudado.
                atual = "|".join(opcoes)
                aceita = (assinatura_anterior is None
                          or atual != assinatura_anterior)
            if aceita:
                return True
            estado = "carregando"   # ainda nao e' resposta: continua esperando
        if estado == "carregando":
            vazio_seguido = 0
            # Spinner na tela renova a paciencia (nunca alem do teto absoluto):
            # portal lento nao pode virar "registro inexistente".
            prazo = min(gasto + timeout_ms, teto_carregando_ms)
        elif estado == "vazio":
            vazio_seguido += 1
            if vazio_seguido >= _VAZIO_ESTAVEL:
                return False
        else:
            vazio_seguido = 0
        await page.wait_for_timeout(passo_ms)
        gasto += passo_ms
    return False


async def abrir_dropdown(page, label_text: str, search_term: str,
                         indice: int = 0) -> bool:
    """Compatibilidade: True apenas quando o portal respondeu AO TERMO."""
    return (await abrir_dropdown_tipado(page, label_text, search_term,
                                        indice)) is MotivoCampo.OK


async def abrir_dropdown_tipado(page, label_text: str, search_term: str,
                                indice: int = 0) -> MotivoCampo:
    """Abre o N-esimo dropdown sob `label_text` (indice resolve duplicados),
    digita `search_term` e forca o lazy-load (WheelEvent).

    Distingue "o campo nem esta' na tela" de "esta', digitei, e o portal nao
    respondeu" de "respondeu com a lista de outra consulta". As tres tinham o
    mesmo retorno `False`, e o chamador as mandava todas para o agente.
    """
    achou = await page.evaluate(_JS_SCROLL_LABEL, [label_text, indice])
    if not achou:
        return MotivoCampo.CAMPO_AUSENTE
    await page.wait_for_timeout(300)
    rect = await page.evaluate(_JS_RECT_LABEL, [label_text, indice])  # rect fresco
    if not rect:
        return MotivoCampo.CAMPO_AUSENTE
    await page.mouse.click(rect["lx"] + rect["lw"] / 2, rect["ly"] + 35)
    await page.wait_for_timeout(500)
    await page.keyboard.press("Control+a")
    await page.wait_for_timeout(200)
    # O conteudo que o listbox ja' mostra ANTES de digitar e' a resposta da
    # consulta anterior (ou a lista sem filtro). Guardar a assinatura e' o que
    # permite saber que o filtro DESTE termo chegou.
    antes = await _assinatura_listbox(page)
    await _telemetria_listbox(page, "antes_busca", label=label_text,
                              termo=search_term, assinatura_anterior=antes)
    if search_term:
        await page.keyboard.type(search_term)
    else:
        # Termo vazio = SEM filtro: lista o que o portal tiver. Digitar ""
        # deixaria o texto anterior no campo e o filtro valendo.
        await page.keyboard.press("Delete")
        antes = None            # aqui a lista sem filtro E' a resposta esperada
    if not await _esperar_listbox(page, 2000, assinatura_anterior=antes,
                                  termo=search_term or None):
        # A lista pode ter ficado parada (portal mudo) ou ter vindo com conteudo
        # que nao corresponde ao termo. A leitura final diz qual dos dois.
        leitura = await ler_listbox(page)
        estado = leitura.get("estado")
        opcoes = leitura.get("opcoes") or []
        # Sem isto, "sem_resposta" cobre tanto "o dropdown nem abriu" quanto
        # "abriu e trouxe outra coisa" — foi preciso um ciclo inteiro so' para
        # distinguir os dois no caso do Regime de Atendimento (30/09).
        print(f"[campo] {label_text!r} termo={search_term!r} sem resposta: "
              f"estado={estado!r} opcoes={len(opcoes)}: {opcoes[:6]}", flush=True)
        await _telemetria_listbox(page, "sem_resposta", label=label_text,
                                  termo=search_term)
        if estado == "ok" and search_term and not opcoes_coerentes(opcoes, search_term):
            return MotivoCampo.RESPOSTA_INCOERENTE
        if estado == "vazio":
            # O portal RESPONDEU: "Nenhum resultado". Nao e' transitorio e
            # reenfileirar nao muda nada — o registro nao existe. Caso real
            # (30/09, job 0d4466b9): 'ALICE LECA VITAL DO CARMO' devolveu vazio
            # nos tres termos de nome, e o CRM 42085 trouxe cinco outras
            # pessoas. Classificar isso como falha transitoria faz o job voltar
            # a' fila e falhar para sempre, sem ninguem ser avisado.
            return MotivoCampo.LISTA_VAZIA
        return MotivoCampo.SEM_RESPOSTA
    # Um ciclo de lazy-load no caminho comum: mesmo teto do wait fixo de
    # 800ms que existia antes do poll. Quem precisa de mais (alvo fora dos
    # primeiros lotes) expande de novo, so' nesse caso.
    await _telemetria_listbox(page, "resposta_aceita", label=label_text,
                              termo=search_term)
    await expandir_listbox(page, max_ciclos=1, timeout_ms=800)
    return MotivoCampo.OK


async def expandir_listbox(page, max_ciclos: int = 4, passo_ms: int = 150,
                           timeout_ms: int = 1500) -> list:
    """Forca o lazy-load ate' a lista parar de crescer. Devolve as opcoes.

    O listbox do portal renderiza ~5 itens e so' carrega o resto quando recebe
    um WheelEvent NO PROPRIO elemento (scroll por coordenada e scrollTop nao
    disparam o handler React). Descoberta do piloto manual: buscando o
    executante fixo '21798', o registro alvo e' o 6o item — invisivel sem isso.

    Antes de `eda1623` a espera pos-wheel era um `wait_for_timeout(800)` fixo,
    que dava tempo do lote seguinte chegar. O poll que a substituiu retorna na
    hora, porque ja' existem opcoes na tela: o lazy-load deixou de ser esperado
    e a lista passou a travar nos 5 primeiros. E' a terceira manifestacao do
    mesmo commit (as outras: placeholder de vazio e spinner).
    """
    opcoes = await opcoes_do_listbox(page)
    melhor = list(opcoes)      # maior lista JA' VISTA nesta expansao
    for _ in range(max(1, max_ciclos)):
        antes = len(opcoes)
        try:
            wheel = await page.evaluate(_JS_WHEEL_LISTBOX)
        except Exception:
            break
        if config.telemetria_dropdown_habilitada():
            print("[sassepe.dropdown] " + json.dumps(
                {"evento": "wheel_despachado", "qtd_antes": antes,
                 "wheel": wheel}, ensure_ascii=False, default=str), flush=True)
        gasto = 0
        while gasto < timeout_ms:
            await page.wait_for_timeout(passo_ms)
            gasto += passo_ms
            opcoes = await opcoes_do_listbox(page)
            if len(opcoes) > antes:
                break
        if len(opcoes) > len(melhor):
            melhor = list(opcoes)
        await _telemetria_listbox(page, "apos_wheel", qtd_antes=antes,
                                  qtd_depois=len(opcoes))
        if len(opcoes) <= antes:
            break            # parou de crescer: lista completa
    # Rolar nunca pode DIMINUIR o que o portal ja' tinha oferecido. Em 30/09 o
    # log registrou `opcoes=5` e, na linha seguinte, `apos expandir: opcoes=0`:
    # o scroll derrubou a lista (re-render, ou o componente descartando o lote
    # ao pedir o proximo). Devolver o vazio faz o adapter concluir "o portal nao
    # tem" — o oposto do que ele tinha acabado de mostrar.
    if len(opcoes) < len(melhor):
        print(f"[listbox] expandir reduziu a lista ({len(melhor)} -> "
              f"{len(opcoes)}); mantendo a maior ja' vista", flush=True)
        return melhor
    return opcoes


async def _clicar_indice(page, indice: int, esperado: str | None = None,
                        espera_ms: int = 800) -> str | None:
    """Clica o elemento de `indice` do listbox. Devolve o texto clicado.

    `esperado` e' o texto que a classificacao viu naquele indice. Entre
    `ler_listbox` e a medicao da coordenada o listbox pode re-renderizar, e o
    indice passa a apontar para outro elemento — inclusive um placeholder.
    Visto em 30/09: `[cbo] indice=0: 'carregando'` num ciclo em que a leitura
    tinha classificado uma opcao real. Conferir o texto antes de clicar custa
    nada e fecha a corrida.
    """
    coord = await page.evaluate(_JS_COORD_POR_INDICE, indice)
    if not coord:
        return None
    texto = (coord.get("texto") or "").strip()
    if esperado is not None and texto != esperado.strip():
        print(f"[listbox] indice {indice} mudou entre classificar e clicar: "
              f"esperava {esperado!r}, achei {texto!r}. Nao clicado.", flush=True)
        return None
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_timeout(espera_ms)
    return texto


async def clicar_opcao_listbox(page, option_text: str) -> bool:
    """Clica a opcao cujo texto bate (exato; fallback 'contem').

    A escolha sai de `ler_listbox` — a MESMA leitura que classifica placeholder.
    A versao anterior tinha o proprio querySelector e nenhum filtro: o fallback
    'contem' podia casar um placeholder com termo curto.
    """
    leitura = await ler_listbox(page)
    opcoes = leitura.get("opcoes") or []
    indices = leitura.get("indices") or []
    alvo = (option_text or "").strip()
    escolha = next((i for i, o in enumerate(opcoes) if o.strip() == alvo), None)
    if escolha is None:
        escolha = next((i for i, o in enumerate(opcoes) if alvo and alvo in o), None)
    if escolha is None or escolha >= len(indices):
        return False
    return await _clicar_indice(page, indices[escolha],
                                esperado=opcoes[escolha]) is not None


async def clicar_primeira_opcao(page) -> str | None:
    """Clica a primeira opcao REAL. Devolve o texto, ou None se nao havia.

    E' o que o CBO precisa (o portal filtra a ocupacao pelo profissional, entao
    a lista costuma ter um item so'). Antes disso o CBO tinha `_JS_PRIMEIRA_OPCAO`,
    uma copia propria do criterio — que em 29/09 clicou no spinner e gravou
    'carregando' no campo obrigatorio.
    """
    leitura = await ler_listbox(page)
    indices = leitura.get("indices") or []
    opcoes = leitura.get("opcoes") or []
    if not indices:
        return None
    return await _clicar_indice(page, indices[0],
                                esperado=opcoes[0] if opcoes else None)


def _opcao_presente(opcoes: list, option_text: str) -> bool:
    """Mesmo criterio de `clicar_opcao_listbox`: exato, com fallback 'contem'."""
    alvo = (option_text or "").strip()
    return any(o.strip() == alvo or alvo in o for o in opcoes)


def _texto_da_opcao(opcoes: list, option_text: str) -> str:
    """Texto completo da opcao que sera' gravado pelo campo."""
    alvo = (option_text or "").strip()
    return next((o for o in opcoes if o.strip() == alvo),
                next((o for o in opcoes if alvo and alvo in o), alvo))


def _valor_confirma_opcao(valor: str | None, option_text: str) -> bool:
    """O valor visivel confirma que o clique realmente foi aceito pelo SPA.

    O portal aceita o evento de mouse antes de atualizar o input. Sem esta
    checagem, um clique ignorado parecia sucesso e o fluxo seguia com campos
    obrigatorios vazios (incidente de 07/10). O texto configurado pode ser so o
    codigo (``22`` ou ``40901122``), enquanto o campo mostra codigo + descricao.
    """
    atual = _norm(valor or "")
    alvo = _norm(option_text or "")
    return bool(atual and alvo and (atual == alvo or alvo in atual))


async def preencher_dropdown(page, label_text: str, search_term: str,
                             option_text: str) -> bool:
    """abrir_dropdown + clicar_opcao. Retorna True so' se a opcao foi clicada."""
    return bool(await preencher_dropdown_detalhado(page, label_text,
                                                   search_term, option_text))


async def preencher_dropdown_detalhado(page, label_text: str, search_term: str,
                                       option_text: str,
                                       indice: int = 0) -> ResultadoCampo:
    """Como `preencher_dropdown`, mas devolve POR QUE nao deu e o que o portal
    ofereceu (ver `MotivoCampo`).

    Ate' 29/09 a falha de campo fixo dizia apenas "Campo fixo nao preenchido:
    Regime de Atendimento" — compativel com pelo menos quatro causas diferentes
    (dropdown nao abriu, portal nao respondeu ao termo, respondeu e a opcao
    esperada nao estava na lista, ou estava e o clique nao gravou). Sem
    distinguir, cada ciclo de correcao vira mais uma hipotese; foi assim que o
    caso do solicitante consumiu tres commits antes de alguem registrar a
    resposta do portal.
    """
    motivo = await abrir_dropdown_tipado(page, label_text, search_term, indice)
    if motivo is not MotivoCampo.OK:
        print(f"[campo] {label_text!r} termo={search_term!r}: {motivo.value}",
              flush=True)
        textos = {
            MotivoCampo.CAMPO_AUSENTE:
                f"o campo {label_text!r} nao estava na tela",
            MotivoCampo.SEM_RESPOSTA:
                f"o portal nao respondeu a busca por {search_term!r} "
                f"(nem lista, nem 'Nenhum resultado')",
            MotivoCampo.LISTA_VAZIA:
                f"o portal respondeu 'Nenhum resultado' para {search_term!r}",
            MotivoCampo.RESPOSTA_INCOERENTE:
                f"o portal devolveu uma lista que nao corresponde a "
                f"{search_term!r} (resposta de outra consulta)",
        }
        return ResultadoCampo(motivo, textos.get(motivo, motivo.value))

    opcoes = await opcoes_do_listbox(page)
    if not _opcao_presente(opcoes, option_text):
        opcoes = await expandir_listbox(page, max_ciclos=6)
    print(f"[campo] {label_text!r} termo={search_term!r} alvo={option_text!r} "
          f"opcoes={len(opcoes)}: {opcoes[:8]}", flush=True)

    if not _opcao_presente(opcoes, option_text):
        return ResultadoCampo(
            MotivoCampo.OPCAO_AUSENTE,
            f"o portal ofereceu {len(opcoes)} opcao(oes) para {search_term!r} "
            f"e nenhuma e' {option_text!r}: {opcoes[:8]}",
            tuple(opcoes))

    opcao_selecionada = _texto_da_opcao(opcoes, option_text)
    if not await clicar_opcao_listbox(page, option_text):
        return ResultadoCampo(
            MotivoCampo.CLIQUE_SEM_EFEITO,
            f"{option_text!r} estava na lista mas o clique nao encontrou o "
            f"elemento (lista de {len(opcoes)})",
            tuple(opcoes))

    # O clique por coordenada pode ser engolido pelo React durante um re-render.
    # Esperar o valor evita que um input ainda contendo o termo de busca seja
    # confundido com selecao. E' deliberadamente uma confirmacao do DOM, nao
    # apenas do evento de click.
    ultimo_valor = None
    for _ in range(8):
        ultimo_valor = await valor_do_campo(page, label_text, indice)
        if _valor_confirma_opcao(ultimo_valor, opcao_selecionada):
            return ResultadoCampo(MotivoCampo.OK, "", tuple(opcoes))
        await page.wait_for_timeout(250)
    return ResultadoCampo(
        MotivoCampo.CLIQUE_SEM_EFEITO,
        f"{option_text!r} foi clicado, mas o campo permaneceu em "
        f"{ultimo_valor!r}",
        tuple(opcoes))


# JS: extrai os textos das opcoes do listbox aberto (dedup).
# Motivos em que o portal RESPONDEU. Se todos os termos terminaram assim, a
# busca foi conclusiva: o registro nao existe. Se algum termo foi transitorio
# (portal mudo, campo fora da tela, lista de outra consulta), nao da' para
# afirmar isso — e reenfileirar ainda faz sentido.
_MOTIVOS_CONCLUSIVOS = {MotivoCampo.OK, MotivoCampo.LISTA_VAZIA}

_TEXTO_MOTIVO = {
    MotivoCampo.CAMPO_AUSENTE: "o campo nao estava na tela",
    MotivoCampo.SEM_RESPOSTA: "o portal ficou mudo",
    MotivoCampo.LISTA_VAZIA: "o portal respondeu 'Nenhum resultado'",
    MotivoCampo.RESPOSTA_INCOERENTE: "o portal devolveu a lista de outra consulta",
}


async def selecionar_solicitante(page, crm: str | None, nome: str):
    """Seleciona o Profissional solicitante por CRM + nome (descoberto no portal:
    o dropdown casa por NOME e por CRM, e o prefixo exibido E' o CRM — que repete
    por UF entre estados, ex.: CRM 16188 tem 5 medicos de UFs diferentes).

    Estrategia: busca pelo CRM (narrowa a lista), e casa a opcao cujo NOME do
    registro CONTEM todos os tokens do nome buscado (tolera acento e sobrenome
    extra: 'NUBIA ROSA LOPES' ⊂ 'NUBIA ROSA LOPES FREIRE'). Sem CRM, busca pelo
    proprio nome (menos confiavel: o listbox so' carrega ~10 itens).

    Conservador (I3): so' clica com match UNICO. Retorna
    ('ok'|'nao_cadastrado'|'nenhum'|'ambiguo', X) — 'nao_cadastrado' quando o
    portal respondeu a TODOS os termos e nenhum trouxe o medico (busca esgotada,
    decisao humana); 'nenhum' quando algum termo foi transitorio e vale
    reenfileirar — o chamador aborta para captura manual se != 'ok'. X e' a
    lista de candidatos quando 'ambiguo', e o relato do que o portal respondeu
    por termo quando 'nenhum' (e' o que permite distinguir "o portal nao tem"
    de "o portal tem e nos recusamos").
    """
    nome_norm = limpar_nome_medico(nome)
    tokens = [t for t in nome_norm.split() if len(t) >= 2]

    # Termos de busca, do mais especifico ao menos. Descoberta (diag_FALHA): o
    # portal RECUSA o nome completo longo ("SANDRA PAIVA BARBOSA" -> "Nenhum
    # resultado"). Buscar por menos tokens faz a lista carregar; o token-match
    # (todos os tokens ⊂ registro) desambigua e mantem o I3 (so' match unico).
    # As variantes COM acento vao primeiro; as sem acento ficam como fallback
    # (portal que normaliza do lado dele continua atendido). Quando o nome nao
    # tem acento as duas coincidem e o dedup resolve.
    tokens_br = [t for t in nome_para_busca(nome).split() if len(t) >= 2]

    termos = []
    if crm and str(crm).strip():
        termos.append(str(crm).strip())
    for grupo in (tokens_br, tokens):
        if not grupo:
            continue
        termos.append(" ".join(grupo))             # nome completo
        if len(grupo) >= 2:
            termos.append(" ".join(grupo[:2]))     # 2 primeiros tokens
        termos.append(grupo[0])                     # 1o token
    termos = list(dict.fromkeys(termos))            # dedup, preserva ordem
    if not termos:
        return "nenhum", []

    # Registro do que o PORTAL respondeu, por termo. Sem isto a falha diz apenas
    # "nao localizado", e tres ciclos de diagnostico (25–28/09) foram gastos
    # adivinhando se o dropdown veio vazio, veio cheio e nos e' que recusamos, ou
    # nem chegou a responder. Vai para o stdout e para a mensagem do operador.
    tentativas: list[str] = []
    motivos: list = []

    for termo in termos:
        motivo = await abrir_dropdown_tipado(page, "Profissional solicitante", termo)
        motivos.append(motivo)
        if motivo is not MotivoCampo.OK:
            print(f"[solicitante] termo={termo!r}: {motivo.value}", flush=True)
            tentativas.append(f"{termo!r}: {_TEXTO_MOTIVO[motivo]}")
            continue
        leitura = await ler_listbox(page)
        opcoes = leitura.get("opcoes") or []
        print(f"[solicitante] termo={termo!r} estado={leitura.get('estado')!r} "
              f"opcoes={len(opcoes)}: {opcoes[:8]}", flush=True)
        if not opcoes:
            tentativas.append(f"{termo!r}: {leitura.get('estado')}")
            continue  # termo nao trouxe lista (ex.: nome completo) -> mais curto

        # 1a passada EXATA. Se nada casar, 2a passada tolerante a grafia: o nome
        # vem de OCR de pedido manuscrito e erra letra com frequencia. Caso real
        # (14/09, job 37e3d344): o job trazia 'Waldete calvacanti' e o portal
        # tinha '2644 - WALDETE AMARAL PEREIRA CAVALCANTI' — o portal ACHOU o
        # medico pelo CRM e nos e' que recusamos, por uma transposicao de letras.
        candidatos = filtrar_candidatos(opcoes, tokens)
        if not candidatos:
            candidatos = filtrar_candidatos(opcoes, tokens, LIMIAR_FUZZY)
        if not candidatos and len(opcoes) >= 5:
            # Lista cheia e nada casou: o alvo pode estar no lote seguinte. O
            # portal entrega ~5 por vez e so' carrega o resto sob WheelEvent.
            opcoes = await expandir_listbox(page, max_ciclos=6)
            print(f"[solicitante] termo={termo!r} apos expandir: "
                  f"opcoes={len(opcoes)}", flush=True)
            candidatos = (filtrar_candidatos(opcoes, tokens)
                          or filtrar_candidatos(opcoes, tokens, LIMIAR_FUZZY))

        if len(candidatos) == 1:
            ok = await clicar_opcao_listbox(page, candidatos[0])
            return ("ok" if ok else "nenhum"), candidatos
        if len(candidatos) > 1:
            return "ambiguo", candidatos  # I3: nao escolhe entre homonimos
        # 0 candidatos com este termo -> tenta o proximo (menos tokens)
        tentativas.append(f"{termo!r}: {len(opcoes)} opcoes, nenhuma casou "
                          f"({opcoes[:5]})")

    # Todos os termos foram respondidos pelo portal e nenhum trouxe o medico:
    # a busca esgotou, o registro nao existe. Caso real (30/09, job 0d4466b9):
    # CRM 42085 devolveu cinco outros profissionais e os tres termos de nome
    # devolveram "Nenhum resultado". Isso e' cadastro, nao falha tecnica — e
    # tratar como transitorio faz o job voltar a' fila e falhar para sempre.
    conclusivo = bool(motivos) and all(m in _MOTIVOS_CONCLUSIVOS for m in motivos)
    return ("nao_cadastrado" if conclusivo else "nenhum"), tentativas


# JS: valor do input que fica logo ABAIXO do N-esimo label com este texto.
# Serve para CONFERIR que um dropdown realmente gravou — clicar nao e' prova.
_JS_VALOR_ABAIXO_DO_LABEL = """
([label_text, indice]) => {
  const labels = Array.from(document.querySelectorAll('*')).filter(e => {
    const t = e.textContent.trim();
    return (t === label_text + '*' || t === label_text)
      && e.getBoundingClientRect().width > 0;
  });
  const label = labels[indice];
  if (!label) return null;
  const lr = label.getBoundingClientRect();
  let melhor = null, menor = 1e9;
  document.querySelectorAll('input').forEach(inp => {
    const r = inp.getBoundingClientRect();
    if (r.width <= 0) return;
    const dy = r.top - lr.top;
    if (dy < 0 || dy > 80) return;          // logo abaixo do label
    const dx = Math.abs(r.left - lr.left);
    if (dx > 300) return;                    // mesma coluna
    if (dy + dx < menor) { menor = dy + dx; melhor = inp; }
  });
  return melhor ? (melhor.value || '').trim() : null;
}
"""

# JS: 1a opcao REAL do listbox (ignora o placeholder de lista vazia).


async def valor_do_campo(page, label_text: str, indice: int = 0):
    """Valor atual do dropdown sob o N-esimo `label_text`.

    Tres retornos DISTINTOS, e a distincao importa:
      "texto"  -> campo preenchido
      ""       -> campo localizado e VAZIO
      None     -> NAO consegui ler (input nao localizado, contexto destruido)

    Confundir None com "" transforma uma limitacao da leitura em veredito de
    campo vazio — e reprova preenchimento que deu certo.
    """
    try:
        v = await page.evaluate(_JS_VALOR_ABAIXO_DO_LABEL, [label_text, indice])
    except Exception:
        return None
    return None if v is None else str(v).strip()


async def preencher_cbo(page, indice: int = 0, tentativas: int = 5,
                        espera_inicial_ms: int = 700) -> bool:
    """CBO 999999: unica opcao apos abrir; clica o 1o item do listbox.
    `indice` escolhe a secao: 0 = Contratado solicitante, 1 = executante (ha'
    DUAS labels 'Código CBO' identicas na pagina).

    Sucesso = clicou numa opcao REAL do listbox — "real" definido no MESMO lugar
    que o resto do adapter (`_JS_LISTBOX_ESTADO`), com re-tentativa enquanto a
    lista carrega; o CBO do executante so' popula depois que o profissional e'
    selecionado.

    A leitura do valor NAO decide mais o resultado. Em 17/09 ela foi promovida a
    veredito e reprovou preenchimento que tinha dado certo: dois jobs seguidos
    (18/09, 09:51 e 10:01) abortaram em "CBO (solicitante) nao preenchido" num
    campo que vinha funcionando havia meses. Localizar o input por geometria e'
    heuristica, e heuristica nao pode vetar o fluxo.

    Quem valida a pagina e' o PORTAL. Se algum obrigatorio ficar vazio, o
    'Próximo' nao avanca e _clicar_proximo le a mensagem de reprovacao dele —
    autoritativa, e ja' implementada (496b92d). A leitura aqui vira so' aviso no
    log, util para investigar sem derrubar job.
    """
    from . import config
    espera = max(100, espera_inicial_ms)
    # O CBO e' a ocupacao DAQUELE profissional no conselho, e o portal filtra a
    # lista por ele. Buscar o literal '999999' so' funciona para quem esta'
    # cadastrado como "nao informado" — foi o caso do executante fixo no piloto,
    # e virou premissa. Em 22/09 (job c51dbc9d) a solicitante tinha CBO real e o
    # filtro devolveu "Nenhum resultado" em todas as tentativas.
    # Ordem: termo configurado primeiro (preserva o comportamento que funciona),
    # depois SEM filtro, aceitando a ocupacao que o portal oferecer.
    termos = [config.CBO_SEARCH, ""]
    for _ in range(max(1, tentativas)):
        texto = None
        for termo in termos:
            if not await abrir_dropdown(page, "Código CBO", termo, indice=indice):
                continue   # label ainda nao renderizou / portal nao respondeu
            # MESMA leitura que classifica placeholder — o CBO nao tem mais
            # caminho proprio. Em 29/09 a copia local do criterio clicou no
            # spinner e gravou 'carregando' no campo obrigatorio.
            texto = await clicar_primeira_opcao(page)
            if texto:
                break
        if texto:
            print(f"[cbo] indice={indice}: {texto!r}", flush=True)
            valor = await valor_do_campo(page, "Código CBO", indice)
            if valor == "":
                # Sinal, nao veredito: pode ser o campo vazio de verdade OU a
                # geometria tendo achado outro input. O portal decide no Proximo.
                print(f"[aviso] CBO indice={indice}: clicou em {texto!r} mas a "
                      f"leitura do campo veio vazia. Seguindo — quem valida e' "
                      f"o portal.", flush=True)
            return True
        # Backoff: a lista do CBO so' popula depois que o profissional carrega, e
        # o portal varia muito nesse tempo. Espera fixa de 700ms x3 (a versao
        # anterior) dava ~13s de janela total e nao bastou em 21/09 — o job
        # c51dbc9d abortou em "CBO (solicitante) nao preenchido" tendo CRM e
        # solicitante corretos. Com 5 tentativas e dobra, a janela vai a ~40s,
        # gasta SO' quando esta' falhando.
        await page.wait_for_timeout(espera)
        espera *= 2
    return False


async def esperar_formulario(page, labels: tuple = (), timeout_ms: int = 15000,
                            passo_ms: int = 300) -> bool:
    """Espera o formulario SP/SADT renderizar de fato, por PRESENCA DE LABEL.

    Selecionar o beneficiario nao significa que o formulario ja' existe: o SPA
    monta a tela depois, e o adapter comecava a preencher antes disso. Medido em
    30/09 (18:10 e 18:31), dois jobs deram `campo_ausente` nos QUATRO termos do
    solicitante — nao era o medico nem o portal, era a tela ainda vazia.

    Falhar aqui e' melhor que falhar em cada campo: o motivo fica certo (tela
    nao renderizou, transitorio, seguro reenfileirar) em vez de virar quatro
    "campo ausente" que parecem problema de cadastro.
    """
    alvos = labels or ("Profissional solicitante", "Profissional executante")
    gasto = 0
    while gasto < max(timeout_ms, passo_ms):
        for label in alvos:
            try:
                if await page.evaluate(_JS_SCROLL_LABEL, [label, 0]):
                    return True
            except Exception:
                pass      # navegacao do SPA derrubou o evaluate: segue o poll
        await page.wait_for_timeout(passo_ms)
        gasto += passo_ms
    return False


async def marcar_paciente_no_local(page) -> bool:
    """Marca o checkbox 'Paciente no local' se ainda nao estiver marcado."""
    estado = await page.evaluate(
        """() => {
          const cb = Array.from(document.querySelectorAll('input[type=checkbox]'))
            .find(e => {
              const p = e.closest('label') || e.parentElement;
              return p && p.textContent.includes('Paciente no local');
            });
          if (!cb) return 'nao_achou';
          return cb.checked ? 'marcado' : 'desmarcado';
        }"""
    )
    if estado == "marcado":
        return True
    if estado == "nao_achou":
        return False
    coord = await page.evaluate(
        """() => {
          const el = Array.from(document.querySelectorAll('*')).find(e =>
            e.textContent.trim() === 'Paciente no local'
            && e.getBoundingClientRect().width > 0);
          if (!el) return null;
          el.scrollIntoView({block: 'center'});
          const r = el.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not coord:
        return False
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_timeout(500)
    return True
