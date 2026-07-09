"""
adapters/unimed_recife/guia.py — Download + parse da GUIA de autorização (PDF).

Mapeado ao vivo (2026-07-03). A guia de autorização (documento TISS SP/SADT,
nativamente digital) tem TODOS os campos: senha, DATA DE VALIDADE DA SENHA,
carteira, beneficiário, procedimento(s) autorizado(s) com TUSS e quantidade,
solicitante/CRM. É a fonte da `validade` (que o CONSULTAR por senha NÃO expõe)
e o insumo do auto-preenchimento do pedido no HOP.

Caminho (a partir da SENHA):
  Acompanhar Solicitação -> filtra por senha -> linha traz o ícone "A" com
  onclick MostrarAcompanhar(<protocolo>,<carteira>,<usuario>,<cod>) (base64)
  -> listaguia.php lista 2 anexos; o "Impressão de Guia" (.pdf) é a guia,
     via onclick MostrarPopoupPrestador(<codanexos>,<nome.pdf>,<protocolo>,...)
  -> mudareditorimagem.php?codanexos=..&nome=..&protocolo=.. serve o PDF.

⚠️ O arquivo direto (solicitacao/files/.../<n>.pdf) dá 401 (basic-auth na pasta).
O download tem que passar pelo VIEWER `mudareditorimagem.php`, de dentro da
sessão logada — usar `page.request.get` (carrega os cookies do contexto).
"""
import base64
import io
import re

BASE = "https://autorizador.unimedrecife.com.br/"
_ACOMPANHAR = (BASE + "usuario.php?id=MzY=&ativa=MA==&area=Mw=="
               "&flag=MQ==&parametro=MA==&gerar=MA==")


# ── Parse do PDF (TISS SP/SADT) ──────────────────────────────────────────────
def _linhas(pdf_bytes: bytes) -> list[str]:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(pdf_bytes))
    t = "\n".join((p.extract_text() or "") for p in r.pages)
    return [l.strip() for l in t.splitlines() if l.strip()]


def _idx(lines, label_rx):
    rx = re.compile(label_rx)
    for i, l in enumerate(lines):
        if rx.search(l):
            return i
    return None


def _vizinho(lines, label_rx, valor_rx, prefer="antes"):
    """Valor ADJACENTE ao rótulo (o form TISS extrai em 2 colunas: valor ora
    antes, ora depois). Testa os dois vizinhos e retorna o que casa o padrão."""
    i = _idx(lines, label_rx)
    if i is None:
        return None
    cand = []
    if i + 1 < len(lines):
        cand.append(lines[i + 1])
    if i - 1 >= 0:
        cand.append(lines[i - 1])
    if prefer == "antes":
        cand.reverse()
    for v in cand:
        m = re.search(valor_rx, v)
        if m:
            return m.group(0)
    return None


def _procedimentos(lines) -> list[dict]:
    i = _idx(lines, r"25 - C.digo do Procedimento")
    if i is None:
        return []
    procs = []
    j = i
    while j < len(lines):
        if re.fullmatch(r"\d{2}-", lines[j]):        # seq "01-"
            bloco = lines[j:j + 6]
            m = re.search(r"\b(\d{8})\b", " ".join(bloco))   # código TUSS 8 díg
            if m:
                descr = next((b for b in bloco if re.search(r"[A-Za-zÀ-ÿ]", b)), "")
                qts = [b for b in bloco if re.fullmatch(r"\d{1,3}", b)]
                procs.append({
                    "codigo_tuss": m.group(1),
                    "descricao": descr,
                    "modalidade": (descr.split(" - ")[0].strip()
                                   if " - " in descr else None),
                    "qtd_solicitada": qts[-2] if len(qts) >= 2 else None,
                    "qtd_autorizada": qts[-1] if len(qts) >= 1 else None,
                })
            break
        j += 1
    return procs


def parse_guia(pdf_bytes: bytes) -> dict:
    """Extrai os campos TISS da guia. Validado contra guia real do portal."""
    L = _linhas(pdf_bytes)
    i_senha = _idx(L, r"^5 - Senha$")
    senha = None
    if i_senha is not None and i_senha + 1 < len(L) and re.fullmatch(r"\d+", L[i_senha + 1]):
        senha = L[i_senha + 1]
    return {
        "senha": senha,
        "validade_senha": _vizinho(L, r"6 - Data de Validade da Senha", r"\d{2}/\d{2}/\d{4}"),
        "data_autorizacao": _vizinho(L, r"^4 - Data da Autoriza", r"\d{2}/\d{2}/\d{4}"),
        "numero_carteira": _vizinho(L, r"8 - N.mero da Carteira", r"\d{10,20}"),
        "beneficiario": _vizinho(L, r"^10 - Nome$", r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .]{5,}"),
        "solicitante_nome": _vizinho(L, r"15 - Nome do Profissional Solicitante",
                                     r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .]{5,}"),
        "solicitante_conselho_numero": _vizinho(L, r"17 - N.mero no Conselho", r"\d{3,7}"),
        "solicitante_uf": _vizinho(L, r"^18 - UF$", r"^[A-Z]{2}$"),
        "procedimentos": _procedimentos(L),
    }


# ── Download (via sessão logada) ─────────────────────────────────────────────
async def _args_acompanhar_por_senha(page, senha: str):
    """Filtra Acompanhar por senha e extrai os args (base64) do ícone 'A'
    (MostrarAcompanhar) da 1a linha."""
    await page.goto(_ACOMPANHAR, wait_until="domcontentloaded")
    await page.wait_for_timeout(1500)
    try:
        await page.fill('input[name="senha"]', str(senha).strip())
    except Exception:
        return None
    # dispatch_event evita o hang do page.click (ver verificar.py).
    await page.dispatch_event('input[name="buscar"]', "click")
    await page.wait_for_timeout(3000)
    return await page.evaluate(
        r"""() => {
          const el = Array.from(document.querySelectorAll('img,a'))
            .find(x => /MostrarAcompanhar/.test(x.getAttribute('onclick') || ''));
          if (!el) return null;
          const m = (el.getAttribute('onclick') || '')
            .match(/MostrarAcompanhar\('([^']*)','([^']*)','([^']*)','([^']*)'/);
          return m ? {protocolo:m[1], carteira:m[2], usuario:m[3], cod:m[4]} : null;
        }"""
    )


async def baixar_guia_por_senha(page, senha: str) -> dict | None:
    """Baixa a guia PDF a partir da senha e devolve {pdf_b64, campos}.
    None se não achar a guia (degrada com segurança). Reusa a sessão logada."""
    args = await _args_acompanhar_por_senha(page, senha)
    if not args:
        return None

    lista_url = (BASE + "auditoria/acompanhar/listaguia.php"
                 f"?protocolo={args['protocolo']}&carteira={args['carteira']}"
                 f"&usuario={args['usuario']}&codsolicitacao={args['cod']}")
    r = await page.request.get(lista_url)
    if not r.ok:
        return None
    html = await r.text()
    # "Impressão de Guia" = anexo .pdf via MostrarPopoupPrestador(<cod>,<nome>,<prot>,..)
    m = re.search(r"MostrarPopoupPrestador\('([^']+)','([^']+\.pdf)','([^']+)'",
                  html, re.I)
    if not m:
        return None
    codanexos, nome, protocolo = m.group(1), m.group(2), m.group(3)

    viewer = (BASE + "auditoria/acompanhar/mudareditorimagem.php"
              f"?codanexos={codanexos}&nome={nome}&protocolo={protocolo}")
    rp = await page.request.get(viewer, headers={"Referer": lista_url})
    if not rp.ok:
        return None
    pdf = await rp.body()
    if not pdf or pdf[:4] != b"%PDF":
        return None

    return {"pdf_b64": base64.b64encode(pdf).decode(), "campos": parse_guia(pdf)}
