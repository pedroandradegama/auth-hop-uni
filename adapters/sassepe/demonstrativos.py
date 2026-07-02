"""
adapters/sassepe/demonstrativos.py — Coleta do Demonstrativo de Análise de Conta (Sassepe/Maida).

Verbo NOVO do adapter (além de submit/coletar). REUSA o login SSO/workspace. Fluxo mapeado ao vivo:
  Faturamento → Cobrança → Cobrança médica → seleciona o mês (M-2) →
  seção "Extrato de Produção" → botão "Baixar XML".

O botão dispara um XHR autenticado (o SPA monta com token + idPrestador). Em vez de replicar a
auth, DEIXAMOS o SPA clicar e CAPTURAMOS a resposta do XHR (Playwright expect_response) — pega os
bytes do XML direto. Resposta pode vir como XML cru ou .zip (detecta pelo prefixo PK).

Racional do mês (M-2): rodando dia 26, busca o mês fechado 2 meses atrás. O mês vem do job (data_ini).
"""
import base64
import hashlib
import io
import os
import re
import zipfile
from datetime import datetime

from .sessao import navegador, login
from . import config

_MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
_EVID_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "evidencias_demonstrativo")
COBRANCA_URL = "https://sassepe.maida.health/faturamento/prestador/medico/cobranca"
_DOWNLOAD_MARK = "demonstrativo-analise-contas/download"


def _mes_ano(data_ini: str | None):
    """data_ini 'YYYY-MM-01' → (label PT ex 'MAI', ano ex 2026, competencia 'YYYY-MM-01')."""
    if not data_ini:
        return None, None, None
    d = datetime.strptime(data_ini[:10], "%Y-%m-%d")
    return _MESES[d.month - 1], d.year, d.strftime("%Y-%m-01")


async def coletar_demonstrativos(data_ini: str | None = None, data_fim: str | None = None) -> dict:
    evidencias: list[dict] = []
    mes, ano, competencia = _mes_ano(data_ini)
    if not mes:
        return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                "mensagem": "data_ini ausente — não dá p/ derivar o mês (competência)."}

    async with navegador() as page:
        try:
            # perfil do DEMONSTRATIVO (distinto do de autorização)
            await login(page, cred_user=config.sassepe_demo_user(), cred_senha=config.sassepe_demo_pass())
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha no login Sassepe (demonstrativo): {e}"}

        os.makedirs(_EVID_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # navega até Cobrança médica (por texto; fallback goto direto)
        try:
            await page.goto("https://sassepe.maida.health/workspace/home", wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            await page.get_by_text("Faturamento", exact=False).first.click(timeout=15000)
            await page.wait_for_timeout(1500)
            await page.get_by_text("Cobrança", exact=False).first.click(timeout=15000)
            await page.wait_for_url("**/cobranca**", timeout=20000)
        except Exception:
            await page.goto(COBRANCA_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # seleciona o ano, se diferente do exibido (dropdown)
        try:
            atual = await page.evaluate("() => (document.body.innerText.match(/20\\d\\d/)||[])[0]")
            if ano and str(ano) != str(atual):
                await page.get_by_text(str(atual), exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(600)
                await page.get_by_text(str(ano), exact=True).first.click(timeout=5000)
                await page.wait_for_timeout(1500)
        except Exception:
            pass

        # seleciona o mês (M-2). As tiles de mês são DIVs (não <button>): acha por texto + tamanho,
        # traz p/ a janela via seta '<' se preciso, e clica com POINTER REAL (mouse.click) — SPA React.
        async def _tiles():
            return await page.evaluate(
                """()=>{const out=[];document.querySelectorAll('*').forEach(function(e){
                    const t=(e.textContent||'').trim();const b=e.getBoundingClientRect();
                    if(/^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/.test(t)&&t.length<16
                       &&b.width>110&&b.width<270&&b.height>20&&b.height<130)
                      out.push({t:t.slice(0,14),x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});});
                    return out;}"""
            )
        # zona limpa (fora do overlay dropdown-de-ano + seta) começa ~x=190
        CLARO = 190
        vw = 1920
        # dump das setas p/ diagnóstico (pequenos clicáveis na linha do strip)
        setas = await page.evaluate(
            """()=>{const out=[];document.querySelectorAll('button,[role=button],svg,path,div').forEach(function(e){
                const b=e.getBoundingClientRect();if(b.width>8&&b.width<70&&b.height>8&&b.height<70&&b.y>230&&b.y<330)
                  out.push({tag:e.tagName,x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)});});
                return out.slice(0,20);}"""
        )
        print(f"[setas] {setas}", flush=True)
        tiles = await _tiles()
        alvo = next((c for c in tiles if c["t"].upper().startswith(mes)), None)
        if alvo is None:
            shot = os.path.join(_EVID_DIR, f"{ts}_sassepe_mes.png")
            try: await page.screenshot(path=shot, full_page=True)
            except Exception: shot = None
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Mês {mes}/{ano} não encontrado. setas={setas} tiles={tiles}. Screenshot: {shot}"}

        # a tile está sob o overlay à esquerda (x<190) → rola o carrossel p/ centralizá-la
        # (scrollIntoView nativo no container de overflow-x). Depois reposiciona.
        rolou = await page.evaluate(
            """(mes)=>{const tile=[...document.querySelectorAll('*')].find(function(e){
                    const t=(e.textContent||'').trim();const b=e.getBoundingClientRect();
                    return new RegExp('^'+mes).test(t)&&t.length<16&&b.width>110&&b.width<270&&b.height>20&&b.height<130;});
                if(!tile) return false;
                tile.scrollIntoView({inline:'center',block:'nearest',behavior:'instant'});
                return true;}""", mes
        )
        await page.wait_for_timeout(1200)
        tiles = await _tiles()
        alvo = next((c for c in tiles if c["t"].upper().startswith(mes)), alvo)
        cx = alvo["x"] if alvo["x"] >= CLARO else max(alvo["x"], CLARO)
        print(f"[mes] alvo={mes}/{ano} rolou={rolou} pos={alvo} click_x={cx}", flush=True)
        await page.mouse.click(cx, alvo["y"])
        await page.wait_for_timeout(3000)

        # diagnóstico pós-clique: mês selecionado? extrato/baixar presentes?
        diag = await page.evaluate(
            """()=>{const b=document.body.innerText||'';
                const sel=[...document.querySelectorAll('*')].find(e=>{const s=getComputedStyle(e);
                  return /^(JAN|FEV|MAR|ABR|MAI|JUN)/.test((e.textContent||'').trim())
                    && (e.textContent||'').trim().length<16
                    && (s.backgroundColor.includes('rgb(')&&s.backgroundColor!=='rgba(0, 0, 0, 0)');});
                return {tem_extrato:/extrato de produç/i.test(b), tem_baixar:/baixar xml/i.test(b),
                        selecionado: sel?(sel.textContent||'').trim().slice(0,14):null};}"""
        )
        print(f"[pos-clique] {diag}", flush=True)
        shot = os.path.join(_EVID_DIR, f"{ts}_sassepe_posmes.png")
        try: await page.screenshot(path=shot, full_page=True)
        except Exception: shot = None

        # espera o "Baixar XML" renderizar (async após trocar o mês)
        for _ in range(12):
            if await page.evaluate("()=>/baixar xml/i.test((document.body.innerText||''))"):
                break
            await page.wait_for_timeout(1000)

        # localiza o botão "Baixar XML" (seção Extrato de Produção)
        botao_xml = page.get_by_role("button", name=re.compile("Baixar XML", re.I)).first
        try:
            await botao_xml.scroll_into_view_if_needed(timeout=8000)
        except Exception:
            return {"status": "sem_novidade", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Sem 'Baixar XML' em {mes}/{ano}. diag={diag}. Screenshot: {shot}"}

        # clica e CAPTURA a resposta do XHR de download (o SPA autentica sozinho)
        try:
            async with page.expect_response(
                lambda r: _DOWNLOAD_MARK in r.url and "XML" in r.url, timeout=60000
            ) as ri:
                await botao_xml.click(timeout=8000)
            resp = await ri.value
            if not resp.ok:
                return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                        "mensagem": f"Download retornou HTTP {resp.status}."}
            conteudo = await resp.body()
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha ao capturar o XML: {e}"}

        # zip ou XML cru
        if conteudo[:2] == b"PK":
            zf = zipfile.ZipFile(io.BytesIO(conteudo))
            nome_xml = next((n for n in zf.namelist() if n.upper().endswith(".XML")), None)
            if not nome_xml:
                return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                        "mensagem": "Zip sem .XML dentro."}
            conteudo = zf.read(nome_xml)
            nome = nome_xml.split("/")[-1]
        else:
            nome = f"sassepe_demonstrativo_{competencia}.xml"

        texto = conteudo.decode("iso-8859-1", errors="ignore")
        if "DEMONSTRATIVO_ANALISE_CONTA" not in texto:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Conteúdo não é DEMONSTRATIVO_ANALISE_CONTA (competência {competencia})."}

        return {"status": "coletado", "competencia": competencia[:7],
                "arquivos": [{
                    "nome": nome,
                    "xml_base64": base64.b64encode(conteudo).decode("ascii"),
                    "sha256": hashlib.sha256(conteudo).hexdigest(),
                    "data_pagamento": None,
                }],
                "evidencias": evidencias,
                "mensagem": f"Demonstrativo {mes}/{ano} coletado."}
