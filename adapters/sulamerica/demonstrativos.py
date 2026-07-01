"""
adapters/sulamerica/demonstrativos.py — Coleta do Demonstrativo de Análise de Conta (XML de retorno).

Verbo NOVO do adapter (além de submit/coletar). REUSA o login/sessão da autorização
(mesmo portal, mesmo prestador). Receita validada ao vivo (handoff Apêndice A, 2026-07-01):

  1. navega à tela do Demonstrativo de Pagamento
  2. fecha o popup de pesquisa NPS (Escape)
  3. filtra o período (setar value + eventos jQuery; digitar char-a-char quebra) + #btnPesquisar
  4. intercepta window.open (o clique no 'xml' abre uma URL PRÉ-ASSINADA do GCS)
  5. clica o links[3] (xml de Análise de Conta Médica) de cada linha
  6. baixa cada URL com httpx puro (assinada → SEM cookie), descompacta o .zip, extrai o .XML
  7. valida (tipoTransacao=DEMONSTRATIVO_ANALISE_CONTA), hash, base64 → contrato de retorno

SulAmérica guarda ~3 meses de histórico → coletar por mês fechado.
"""
import base64
import hashlib
import io
import zipfile
from datetime import datetime

import httpx

from .sessao import navegador, login


def _br(data_iso: str | None) -> str | None:
    """yyyy-mm-dd → dd/mm/yyyy (formato do portal)."""
    if not data_iso:
        return None
    try:
        return datetime.strptime(data_iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return None


def _data_pagamento_do_nome(nome: str) -> str | None:
    """DC_000043_20260610_100000014967_001.XML → 2026-06-10 (o 2º bloco AAAAMMDD)."""
    partes = nome.split("_")
    for p in partes:
        if len(p) == 8 and p.isdigit():
            try:
                return datetime.strptime(p, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


# JS: intercepta window.open guardando as URLs (não abre aba/download nativo)
_HOOK_OPEN = """
window.__urls = [];
const _o = window.open;
window.open = function(u){ try { window.__urls.push('' + u); } catch(e){} return null; };
"""

# JS: seta o período (value + eventos) e dispara a pesquisa.
# Forma arrow recebendo o arg do Playwright (evaluate injeta 1 parâmetro, não `arguments`).
_SET_PERIODO = """
([ini, fim]) => {
  function setv(id, v){ var e = document.getElementById(id); if(!e) return;
    e.value = v; e.dispatchEvent(new Event('input', {bubbles:true}));
    e.dispatchEvent(new Event('change', {bubbles:true})); }
  setv('data-inicial', ini); setv('data-final', fim);
  var b = document.getElementById('btnPesquisar'); if(b) b.click();
}
"""

# JS: clica o link 'xml' de Análise de Conta Médica (links[3]) de cada linha da tabela.
# Filtro de linha: tr com 6-8 td e uma data dd/mm/yyyy; os <a> cujo texto é pdf|xml|csv.
# Retorna quantos cliques disparou.
_CLICAR_XMLS = """
(function(){
  var n = 0;
  var trs = Array.prototype.slice.call(document.querySelectorAll('tr'));
  trs.forEach(function(tr){
    var tds = tr.querySelectorAll('td');
    if (tds.length < 6 || tds.length > 9) return;
    if (!/\\d{2}\\/\\d{2}\\/\\d{4}/.test(tr.textContent)) return;
    var links = Array.prototype.slice.call(tr.querySelectorAll('a')).filter(function(a){
      var t = (a.textContent || '').trim().toLowerCase();
      return t === 'pdf' || t === 'xml' || t === 'csv';
    });
    // ordem por linha: [pdf, xml, pdf, xml, csv] → índice 3 = xml Análise de Conta Médica
    if (links.length >= 4) { links[3].click(); n++; }
  });
  return n;
})();
"""

DEMO_URL = (
    "https://saude.sulamericaseguros.com.br/prestador/servicos-medicos/"
    "demonstrativos-tiss-3/demonstrativo-de-pagamento/"
)


async def coletar_demonstrativos(data_ini: str | None = None, data_fim: str | None = None) -> dict:
    """Coleta os XML de Análise de Conta do período. Retorno estruturado (contrato da coleta)."""
    evidencias: list[dict] = []
    ini_br, fim_br = _br(data_ini), _br(data_fim)

    async with navegador() as page:
        try:
            await login(page)
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha no login: {e}"}

        await page.goto(DEMO_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        # fecha o popup NPS (best-effort)
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        except Exception:
            pass

        await page.evaluate(_HOOK_OPEN)

        if ini_br and fim_br:
            await page.evaluate(_SET_PERIODO, [ini_br, fim_br])
            await page.wait_for_timeout(4000)  # portal TISS é lento

        try:
            cliques = await page.evaluate(_CLICAR_XMLS)
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha ao localizar/clicar os XML: {e}"}
        await page.wait_for_timeout(1500)

        urls: list[str] = await page.evaluate("window.__urls || []")
        urls = [u for u in urls if u and u.lower().endswith(".zip")]

        if not urls:
            return {"status": "sem_novidade", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Nenhum XML de análise de conta no período ({cliques} linha(s) varrida(s))."}

        # baixa as URLs assinadas (SEM cookies), descompacta, extrai o XML
        arquivos: list[dict] = []
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as cli:
            for u in urls:
                try:
                    r = await cli.get(u)
                    r.raise_for_status()
                    zf = zipfile.ZipFile(io.BytesIO(r.content))
                    nome_xml = next((n for n in zf.namelist() if n.upper().endswith(".XML")), None)
                    if not nome_xml:
                        continue
                    conteudo = zf.read(nome_xml)  # bytes ISO-8859-1
                    # valida: é um demonstrativo de análise de conta?
                    texto = conteudo.decode("iso-8859-1", errors="ignore")
                    if "DEMONSTRATIVO_ANALISE_CONTA" not in texto:
                        continue
                    arquivos.append({
                        "nome": nome_xml.split("/")[-1],
                        "xml_base64": base64.b64encode(conteudo).decode("ascii"),
                        "sha256": hashlib.sha256(conteudo).hexdigest(),
                        "data_pagamento": _data_pagamento_do_nome(nome_xml),
                    })
                except Exception as e:
                    evidencias.append({"etapa": "download", "erro": str(e), "url": u[:120]})

        if not arquivos:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": "URLs capturadas mas nenhum XML de análise de conta válido extraído."}

        return {"status": "coletado", "arquivos": arquivos, "evidencias": evidencias,
                "mensagem": f"{len(arquivos)} demonstrativo(s) coletado(s)."}
