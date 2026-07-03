"""
adapters/sassepe/demonstrativos.py — Coleta do Demonstrativo de Análise de Conta (Sassepe/Maida).

Verbo NOVO do adapter (além de submit/coletar). REUSA a sessão SSO/workspace, mas com CREDENCIAL
PRÓPRIA (perfil do demonstrativo != autorização).

Fluxo (mapeado ao vivo): Faturamento → Cobrança → Cobrança médica → mês → "Extrato de Produção" →
"Baixar XML". O SELETOR DE MÊS é um carrossel React teimoso; descobrimos que o app lê o mês
selecionado do localStorage `@cobranca-competenciaData` na carga da página. Então PRÉ-SELECIONAMOS
o mês setando essa chave + recarregando — sem tocar no carrossel.

O botão "Baixar XML" dispara um XHR autenticado (o SPA monta com token + idPrestador). Em vez de
replicar a auth, deixamos o SPA clicar e CAPTURAMOS a resposta do XHR (Playwright expect_response).
Resposta pode vir XML cru ou .zip (detecta pelo prefixo PK).

Mês (M-2): rodando dia 26, busca o mês fechado 2 meses atrás. O mês vem do job (data_ini).
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

# seta o mês selecionado no localStorage (o app lê na carga) → pré-seleciona sem carrossel
_SET_COMPETENCIA = """([month, comp]) => {
  const val = {competenciaValue:{month:month, competencia:comp, status:'FECHADO', situacao:'FECHADO'},
               expiration: new Date(Date.now()+6*3600*1000).toISOString()};
  localStorage.setItem('@cobranca-competenciaData', JSON.stringify(val));
}"""


def _mes_ano(data_ini):
    if not data_ini:
        return None, None, None
    d = datetime.strptime(data_ini[:10], "%Y-%m-%d")
    return _MESES[d.month - 1], d.year, d.strftime("%Y-%m-01")


async def coletar_demonstrativos(data_ini=None, data_fim=None) -> dict:
    evidencias: list[dict] = []
    mes, ano, competencia = _mes_ano(data_ini)
    if not mes:
        return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                "mensagem": "data_ini ausente — não dá p/ derivar o mês (competência)."}

    async with navegador() as page:
        try:
            await login(page, cred_user=config.sassepe_demo_user(), cred_senha=config.sassepe_demo_pass())
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha no login Sassepe (demonstrativo): {e}"}

        os.makedirs(_EVID_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # entra no origin, pré-seleciona o mês via localStorage e recarrega
        await page.goto(COBRANCA_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        await page.evaluate(_SET_COMPETENCIA, [mes, competencia])
        await page.goto(COBRANCA_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # espera o "Baixar XML" renderizar (só existe se o demonstrativo do mês está disponível)
        tem = False
        for _ in range(15):
            tem = await page.evaluate("()=>/baixar xml/i.test(document.body.innerText||'')")
            if tem:
                break
            await page.wait_for_timeout(1000)
        if not tem:
            shot = os.path.join(_EVID_DIR, f"{ts}_sassepe_sem_xml.png")
            try:
                await page.screenshot(path=shot, full_page=True)
            except Exception:
                shot = None
            return {"status": "sem_novidade", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Demonstrativo de {mes}/{ano} indisponível (sem 'Baixar XML'). Screenshot: {shot}"}

        # clica "Baixar XML" e CAPTURA a resposta do XHR (o SPA autentica sozinho)
        botao_xml = page.get_by_role("button", name=re.compile("Baixar XML", re.I)).first
        try:
            await botao_xml.scroll_into_view_if_needed(timeout=8000)
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
