"""
adapters/unimed_recife/verificar.py — Ação `verificar` (Camada 3 do gate).

Dada uma SENHA de autorização já emitida, consulta o portal e devolve o estado
atual dela. Rota de CONSULTA — nunca cria/altera nada.

Tela mapeada ao vivo (Autorizador Web): menu Autorizações -> "VALIDAR SENHA" =
"CONSULTAR AUTORIZAÇÃO". Form: input[name="numero"] (senha) + botão
input[name="buscar"] (onclick ValidaAutorizacao) -> painel "Resultado da Busca".

Resultado de senha AUTORIZADA (linhas td|td no cabeçalho + tabela de Itens):
  Carteira, Cod. Executante, Executante, Guia Prestador, Beneficiário,
  Autorização(=senha), Status(=Autorizado), Cod. Unimed
  Itens: "N. Item - CODIGO - MODALIDADE - descrição" | Status | Qtd Solic | Qtd Aut
Senha inexistente -> painel mostra "Senha Inválida".

⚠️ O portal NÃO expõe validade (início/fim) nesta tela -> `validade` = null.
No Unimed a senha só existe quando autorizado; o identificador sempre-presente
(mesmo p/ negada) é o PROTOCOLO, capturado pela varredura (`coletar`).

Contrato (payload do callback):
  {status_portal: autorizada|cancelada|vencida|nao_encontrada|erro,
   validade: null, qtd_autorizada: int|null, classe_erro: estrutural|transitorio|null,
   evidencia_b64: <PNG base64 ≤300KB>|null, detalhe: str|null, itens?: [...]}
"""
import asyncio
import base64
import re

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from . import sessao

VALIDAR_TIMEOUT_S = 90        # timeout interno da ação (spec)
_MAX_EVID_B64 = 300 * 1024    # limite do evidencia_b64

# JS: pares chave->valor do cabeçalho (linhas com exatamente 2 células).
_JS_PARES = r"""() => {
  const out = {};
  document.querySelectorAll('table tr').forEach(tr => {
    const td = tr.querySelectorAll('td');
    if (td.length === 2) {
      const k = (td[0].textContent || '').replace(/\s+/g,' ').trim();
      const v = (td[1].textContent || '').replace(/\s+/g,' ').trim();
      if (k) out[k] = v;
    }
  });
  return out;
}"""

# JS: linhas da tabela de Itens (>=4 células, com "Item - <codigo> - <mod> -").
_JS_ITENS = r"""() => {
  const out = [];
  document.querySelectorAll('table tr').forEach(tr => {
    const td = Array.from(tr.querySelectorAll('td'));
    if (td.length >= 4) {
      const c = td.map(t => (t.textContent||'').replace(/\s+/g,' ').trim());
      if (/Item\s*-\s*\d+/.test(c[0])) out.push(c);
    }
  });
  return out;
}"""


def _erro(classe: str, detalhe: str) -> dict:
    return {"status_portal": "erro", "classe_erro": classe, "validade": None,
            "qtd_autorizada": None, "evidencia_b64": None, "detalhe": detalhe[:400]}


def _norm_status(txt: str) -> str:
    """Rótulo do portal -> enum do contrato. Só os estados que uma SENHA pode
    assumir (senha só existe quando houve autorização)."""
    t = (txt or "").strip().lower()
    if "autorizad" in t:
        return "autorizada"
    if "cancelad" in t:
        return "cancelada"
    if "vencid" in t or "expirad" in t:
        return "vencida"
    if "inválid" in t or "invalid" in t or "não encontrad" in t or "nao encontrad" in t:
        return "nao_encontrada"
    return ""  # desconhecido -> chamador trata


def _parse_item(item_str: str):
    """'1. Item - 41001036 - TC - Face ou seios da face' ->
    {codigo_tuss, modalidade, descricao}."""
    m = re.search(r"Item\s*-\s*(\d+)\s*-\s*([A-Za-z]+)\s*-\s*(.+)$", item_str or "")
    if not m:
        return {"codigo_tuss": None, "modalidade": None, "descricao": item_str}
    return {"codigo_tuss": m.group(1), "modalidade": m.group(2).upper(),
            "descricao": m.group(3).strip()}


async def _evidencia_b64(page) -> str | None:
    try:
        png = await page.screenshot()          # viewport (pequeno)
        b64 = base64.b64encode(png).decode()
        return b64 if len(b64) <= _MAX_EVID_B64 else None
    except Exception:
        return None


async def _fluxo(page, senha: str, numero_carteira: str | None) -> dict:
    await sessao.login(page)

    # Menu Autorizações -> VALIDAR SENHA (tela CONSULTAR AUTORIZAÇÃO).
    try:
        await page.get_by_role(
            "link", name=re.compile("VALIDAR SENHA", re.I)).first.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
    except Exception as e:
        return _erro("estrutural", f"menu 'VALIDAR SENHA' não encontrado: {e}")

    campo = page.locator('input[name="numero"]')
    try:
        await campo.wait_for(timeout=8000)
    except Exception:
        return _erro("estrutural", "campo de senha (input[name=numero]) ausente")

    await campo.fill(str(senha).strip())
    await page.click('input[name="buscar"]')

    # Espera o painel popular: ou "Senha Inválida" ou uma linha de Item.
    try:
        await page.wait_for_function(
            """() => { const t = document.body.innerText;
                 return /Senha\\s*Inv[aá]lid/i.test(t) || /Item\\s*-\\s*\\d+/.test(t); }""",
            timeout=30000,
        )
    except PlaywrightTimeoutError:
        return _erro("transitorio", "portal não retornou resultado (timeout na busca)")
    await page.wait_for_timeout(600)

    evid = await _evidencia_b64(page)
    corpo = await page.inner_text("body")

    if re.search(r"senha\s*inv[aá]lid", corpo, re.I):
        return {"status_portal": "nao_encontrada", "validade": None,
                "qtd_autorizada": None, "classe_erro": None,
                "evidencia_b64": evid, "detalhe": "Senha Inválida", "itens": []}

    pares = await page.evaluate(_JS_PARES)
    itens_raw = await page.evaluate(_JS_ITENS)
    status_txt = pares.get("Status", "")
    status = _norm_status(status_txt)

    itens = []
    qtd_aut_total = 0
    for row in itens_raw:
        info = _parse_item(row[0])
        qsol = row[2] if len(row) > 2 else None
        qaut = row[3] if len(row) > 3 else None
        try:
            if qaut is not None:
                qtd_aut_total += int(re.sub(r"\D", "", qaut) or 0)
        except Exception:
            pass
        itens.append({**info, "status": row[1] if len(row) > 1 else None,
                      "qtd_solicitada": qsol, "qtd_autorizada": qaut})

    if not status:
        # painel renderizou mas Status não reconhecido -> devolve p/ humano ver
        return {"status_portal": "erro", "classe_erro": "transitorio",
                "validade": None, "qtd_autorizada": qtd_aut_total or None,
                "evidencia_b64": evid,
                "detalhe": f"status_portal desconhecido: {status_txt!r}",
                "itens": itens}

    return {
        "status_portal": status,
        "validade": None,                     # Unimed não expõe validade nesta tela
        "qtd_autorizada": qtd_aut_total or None,
        "classe_erro": None,
        "evidencia_b64": evid,
        "detalhe": f"Status: {status_txt}; carteira: {pares.get('Carteira')}; "
                   f"guia_prestador: {pares.get('Guia Prestador')}; {len(itens)} item(ns)",
        "itens": itens,                       # bônus p/ Fase 2 (TUSS/modalidade/qtd)
    }


async def verificar(senha: str, numero_carteira: str | None = None) -> dict:
    """Ponto de entrada da ação. Timeout interno 90s -> erro/transitorio.
    Toda exceção vira erro/transitorio (conservador: na dúvida, o HOP re-tenta)."""
    if not (senha or "").strip():
        return _erro("estrutural", "senha vazia")

    async def _run():
        async with sessao.navegador() as page:
            return await _fluxo(page, senha, numero_carteira)

    try:
        return await asyncio.wait_for(_run(), timeout=VALIDAR_TIMEOUT_S)
    except asyncio.TimeoutError:
        return _erro("transitorio", f"timeout interno (>{VALIDAR_TIMEOUT_S}s)")
    except Exception as e:
        return _erro("transitorio", f"falha inesperada: {e}")
