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
import unicodedata
from dataclasses import dataclass
from enum import Enum

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
    SEM_RESPOSTA = "sem_resposta"                # digitou e o portal nao respondeu
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


def limpar_nome_medico(nome: str) -> str:
    """Remove prefixo de tratamento (Dr./Dra.) e normaliza. O pedido medico
    costuma trazer 'Dra. Nubia Rosa Lopes'; o registro do portal nao tem o
    prefixo (e pode ter sobrenome extra)."""
    n = _norm(nome)
    for p in ("DRA.", "DR.", "DRA", "DR"):
        if n == p:
            return ""
        if n.startswith(p + " "):
            return n[len(p):].strip()
    return n

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

_JS_WHEEL_LISTBOX = """
() => {
  const lb = document.querySelector('[role=listbox]');
  if (lb) lb.dispatchEvent(new WheelEvent('wheel',
    {deltaY: 300, bubbles: true, cancelable: true, composed: true}));
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
    return any(alvo[0] in _norm(o) for o in opcoes)


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
            atual = "|".join(opcoes)
            mudou = assinatura_anterior is None or atual != assinatura_anterior
            cabe = termo is None or opcoes_coerentes(opcoes, termo)
            if mudou and cabe:
                return True
            # Lista igual a de antes, ou incompativel com o termo: o filtro
            # ainda nao chegou. Tratar como 'carregando' e continuar esperando.
            estado = "carregando"
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
        if (leitura.get("estado") == "ok" and search_term
                and not opcoes_coerentes(leitura.get("opcoes") or [], search_term)):
            return MotivoCampo.RESPOSTA_INCOERENTE
        return MotivoCampo.SEM_RESPOSTA
    # Um ciclo de lazy-load no caminho comum: mesmo teto do wait fixo de
    # 800ms que existia antes do poll. Quem precisa de mais (alvo fora dos
    # primeiros lotes) expande de novo, so' nesse caso.
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
    for _ in range(max(1, max_ciclos)):
        antes = len(opcoes)
        try:
            await page.evaluate(_JS_WHEEL_LISTBOX)
        except Exception:
            break
        gasto = 0
        while gasto < timeout_ms:
            await page.wait_for_timeout(passo_ms)
            gasto += passo_ms
            opcoes = await opcoes_do_listbox(page)
            if len(opcoes) > antes:
                break
        if len(opcoes) <= antes:
            break            # parou de crescer: lista completa
    return opcoes


async def _clicar_indice(page, indice: int, espera_ms: int = 800) -> str | None:
    """Clica o elemento de `indice` do listbox. Devolve o texto clicado."""
    coord = await page.evaluate(_JS_COORD_POR_INDICE, indice)
    if not coord:
        return None
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_timeout(espera_ms)
    return coord.get("texto")


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
    return await _clicar_indice(page, indices[escolha]) is not None


async def clicar_primeira_opcao(page) -> str | None:
    """Clica a primeira opcao REAL. Devolve o texto, ou None se nao havia.

    E' o que o CBO precisa (o portal filtra a ocupacao pelo profissional, entao
    a lista costuma ter um item so'). Antes disso o CBO tinha `_JS_PRIMEIRA_OPCAO`,
    uma copia propria do criterio — que em 29/09 clicou no spinner e gravou
    'carregando' no campo obrigatorio.
    """
    leitura = await ler_listbox(page)
    indices = leitura.get("indices") or []
    if not indices:
        return None
    return await _clicar_indice(page, indices[0])


def _opcao_presente(opcoes: list, option_text: str) -> bool:
    """Mesmo criterio de `clicar_opcao_listbox`: exato, com fallback 'contem'."""
    alvo = (option_text or "").strip()
    return any(o.strip() == alvo or alvo in o for o in opcoes)


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
                f"o portal nao respondeu a busca por {search_term!r}",
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

    if not await clicar_opcao_listbox(page, option_text):
        return ResultadoCampo(
            MotivoCampo.CLIQUE_SEM_EFEITO,
            f"{option_text!r} estava na lista mas o clique nao encontrou o "
            f"elemento (lista de {len(opcoes)})",
            tuple(opcoes))
    return ResultadoCampo(MotivoCampo.OK, "", tuple(opcoes))


# JS: extrai os textos das opcoes do listbox aberto (dedup).
async def selecionar_solicitante(page, crm: str | None, nome: str):
    """Seleciona o Profissional solicitante por CRM + nome (descoberto no portal:
    o dropdown casa por NOME e por CRM, e o prefixo exibido E' o CRM — que repete
    por UF entre estados, ex.: CRM 16188 tem 5 medicos de UFs diferentes).

    Estrategia: busca pelo CRM (narrowa a lista), e casa a opcao cujo NOME do
    registro CONTEM todos os tokens do nome buscado (tolera acento e sobrenome
    extra: 'NUBIA ROSA LOPES' ⊂ 'NUBIA ROSA LOPES FREIRE'). Sem CRM, busca pelo
    proprio nome (menos confiavel: o listbox so' carrega ~10 itens).

    Conservador (I3): so' clica com match UNICO. Retorna ('ok'|'nenhum'|
    'ambiguo', X) — o chamador aborta para captura manual se != 'ok'. X e' a
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
    termos = []
    if crm and str(crm).strip():
        termos.append(str(crm).strip())
    if tokens:
        termos.append(" ".join(tokens))            # nome completo
        if len(tokens) >= 2:
            termos.append(" ".join(tokens[:2]))    # 2 primeiros tokens
        termos.append(tokens[0])                    # 1o token
    termos = list(dict.fromkeys(termos))            # dedup, preserva ordem
    if not termos:
        return "nenhum", []

    # Registro do que o PORTAL respondeu, por termo. Sem isto a falha diz apenas
    # "nao localizado", e tres ciclos de diagnostico (25–28/09) foram gastos
    # adivinhando se o dropdown veio vazio, veio cheio e nos e' que recusamos, ou
    # nem chegou a responder. Vai para o stdout e para a mensagem do operador.
    tentativas: list[str] = []

    for termo in termos:
        if not await abrir_dropdown(page, "Profissional solicitante", termo):
            print(f"[solicitante] termo={termo!r}: portal nao respondeu "
                  f"(lista inalterada, incompativel com o termo, ou campo "
                  f"ausente)", flush=True)
            tentativas.append(f"{termo!r}: portal nao respondeu ao termo "
                              f"(lista inalterada ou campo ausente)")
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

    return "nenhum", tentativas


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
