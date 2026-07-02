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
            await login(page)
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha no login Sassepe: {e}"}

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

        # seleciona o mês (M-2). Playwright rola o carrossel + clica.
        try:
            botao_mes = page.get_by_role("button", name=re.compile(rf"^{mes}\b", re.I)).first
            await botao_mes.scroll_into_view_if_needed(timeout=8000)
            await botao_mes.click(timeout=8000)
        except Exception:
            # fallback: clique via JS no botão do mês
            ok = await page.evaluate(
                """(mes)=>{const el=[...document.querySelectorAll('button,[role=button]')]
                    .find(e=>new RegExp('^'+mes,'i').test((e.textContent||'').trim()));
                    if(el){el.click();return true;}return false;}""", mes)
            if not ok:
                return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                        "mensagem": f"Mês {mes}/{ano} não encontrado no carrossel."}
        await page.wait_for_timeout(2500)

        # localiza o botão "Baixar XML" (seção Extrato de Produção)
        botao_xml = page.get_by_role("button", name=re.compile("Baixar XML", re.I)).first
        try:
            await botao_xml.scroll_into_view_if_needed(timeout=8000)
        except Exception:
            shot = os.path.join(_EVID_DIR, f"{ts}_sassepe_sem_xml.png")
            try:
                await page.screenshot(path=shot, full_page=True)
            except Exception:
                shot = None
            return {"status": "sem_novidade", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Sem 'Baixar XML' em {mes}/{ano} (demonstrativo não disponível?). Screenshot: {shot}"}

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
