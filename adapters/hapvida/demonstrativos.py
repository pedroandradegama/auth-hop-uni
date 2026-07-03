"""
adapters/hapvida/demonstrativos.py — Coleta do Demonstrativo de Análise de Conta (Hapvida).

Fluxo (mapeado ao vivo): login → /medical-production → filtra Mês de produção (M-2) → Buscar →
lista de lotes. Cada lote CONCLUÍDO tem link /statement-payment/<uuid> (ícone carteira, col.
Demonstrativo). Na página do statement, "Gerar XML" dispara geração ASSÍNCRONA (export-report).
Quando pronta, aparece no sino "Alerta" uma notificação "Demonstrativo de Pagamento (XML) —
Concluído — (Download)". O (Download) faz GET em
  api.hapvida.com.br/.../reports/download?fileName=DemonstrativoPagamento-<processo>-0.xml&reportType=2
que retorna o XML. Capturamos a resposta desse XHR (o SPA autentica sozinho).

Múltiplos lotes por mês → múltiplos XMLs. Cron dia 01, competência M-2.
"""
import base64
import hashlib
import os
import re
from datetime import datetime

from .sessao import navegador, login
from . import config

_EVID_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "evidencias_demonstrativo")
MEDICAL_URL = "https://portalprestador.hapvida.com.br/medical-production"
_DL_MARK = "reports/download"

# lê os lotes CONCLUÍDO da tabela: {uuid do statement, processo (10 díg)}
_LER_LOTES = """
() => {
  const out=[];
  document.querySelectorAll('a[href^="/statement-payment/"]').forEach(function(a){
    const tr=a.closest('tr'); const txt=tr?(tr.textContent||''):'';
    if(!/Conclu/i.test(txt)) return;
    const proc=(txt.match(/\\b(\\d{10})\\b/)||[])[1] || null;
    out.push({uuid:a.getAttribute('href').split('/').pop(), processo:proc});
  });
  // dedup por uuid
  const seen={}; return out.filter(function(o){if(seen[o.uuid])return false;seen[o.uuid]=1;return true;});
}
"""

# no sino aberto: botões (Download) de "Demonstrativo de Pagamento (XML)" Concluído + o processo
_LER_DOWNLOADS = """
() => {
  const out=[];
  document.querySelectorAll('button').forEach(function(b){
    if(!/download/i.test(b.textContent||'')) return;
    let blk=b; for(let i=0;i<5&&blk.parentElement;i++){ if(/Demonstrativo de Pagamento/i.test(blk.textContent||'')) break; blk=blk.parentElement; }
    const txt=blk.textContent||'';
    if(!/Demonstrativo de Pagamento/i.test(txt) || !/Conclu/i.test(txt)) return;
    const proc=(txt.match(/\\b(\\d{10})\\b/)||[])[1] || null;
    const r=b.getBoundingClientRect();
    out.push({processo:proc, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
  });
  return out;
}
"""


async def coletar_demonstrativos(data_ini=None, data_fim=None) -> dict:
    evidencias = []
    if not data_ini:
        return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                "mensagem": "data_ini ausente — sem competência."}
    d = datetime.strptime(data_ini[:10], "%Y-%m-%d")
    mes_ano = d.strftime("%m/%Y")  # filtro "mm/aaaa"

    async with navegador() as page:
        try:
            await login(page)
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha no login Hapvida: {e}"}

        os.makedirs(_EVID_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        await page.goto(MEDICAL_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # filtra o mês de produção + Buscar
        try:
            campo = page.locator('input[placeholder="mm/aaaa"]').first
            await campo.fill(mes_ano)
            await page.wait_for_timeout(400)
            # Buscar: botão de lupa (mais à direita da linha de filtros); fallback Enter
            clicou = await page.evaluate(
                """()=>{const bs=[...document.querySelectorAll('button')].filter(function(e){const b=e.getBoundingClientRect();
                    return b.y>150&&b.y<300&&b.width>20&&b.width<80&&e.querySelector('svg');});
                    bs.sort((a,b)=>b.getBoundingClientRect().x-a.getBoundingClientRect().x);
                    if(bs[0]){bs[0].click();return true;}return false;}"""
            )
            if not clicou:
                await campo.press("Enter")
        except Exception as e:
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Falha no filtro de mês: {e}"}
        await page.wait_for_timeout(4000)

        alvos = await page.evaluate(_LER_LOTES)
        print(f"[hapvida] mes={mes_ano} lotes_concluido={alvos}", flush=True)
        if not alvos:
            shot = os.path.join(_EVID_DIR, f"{ts}_hapvida_lista.png")
            try: await page.screenshot(path=shot, full_page=True)
            except Exception: shot = None
            return {"status": "sem_novidade", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Nenhum lote Concluído em {mes_ano}. Screenshot: {shot}"}
        # dispara "Gerar XML" de cada lote (geração assíncrona)
        for a in alvos:
            try:
                await page.goto(f"https://portalprestador.hapvida.com.br/statement-payment/{a['uuid']}",
                                wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                btn = page.get_by_role("button", name=re.compile("Gerar XML", re.I)).first
                await btn.scroll_into_view_if_needed(timeout=8000)
                await btn.click(timeout=8000)
                await page.wait_for_timeout(1500)
            except Exception as e:
                evidencias.append({"etapa": "gerar", "uuid": a["uuid"], "erro": str(e)})

        # volta à lista, abre o sino e espera as gerações concluírem
        await page.goto(MEDICAL_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        arquivos = []
        vistos = set()  # fileNames já capturados (dedup — o processo vem null da UI)
        alvo_n = len(alvos)
        for tentativa in range(8):
            try:
                await page.get_by_text("Alerta", exact=False).first.click(timeout=8000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            downloads = await page.evaluate(_LER_DOWNLOADS)
            print(f"[hapvida] tentativa={tentativa} downloads={len(downloads)} capturados={len(arquivos)}", flush=True)
            # clica cada (Download) de Demonstrativo Pagamento Concluído; dedup pelo fileName da resposta
            for dl in downloads:
                try:
                    async with page.expect_response(lambda r: _DL_MARK in r.url, timeout=30000) as ri:
                        await page.mouse.click(dl["x"], dl["y"])
                    resp = await ri.value
                    fn = (re.search(r"fileName=([^&]+)", resp.url) or [None, None])[1] or f"hapvida_{len(arquivos)}.xml"
                    if fn in vistos:
                        continue
                    body = await resp.body()
                    if "DEMONSTRATIVO_ANALISE_CONTA" not in body.decode("iso-8859-1", errors="ignore"):
                        continue
                    vistos.add(fn)
                    arquivos.append({
                        "nome": fn, "xml_base64": base64.b64encode(body).decode("ascii"),
                        "sha256": hashlib.sha256(body).hexdigest(), "data_pagamento": None,
                    })
                except Exception as e:
                    evidencias.append({"etapa": "download", "erro": str(e)})
                await page.wait_for_timeout(500)
            if len(arquivos) >= alvo_n:
                break
            await page.wait_for_timeout(4000)  # espera mais gerações concluírem

        if not arquivos:
            shot = os.path.join(_EVID_DIR, f"{ts}_hapvida_sino.png")
            try: await page.screenshot(path=shot, full_page=True)
            except Exception: shot = None
            return {"status": "erro_coleta", "arquivos": [], "evidencias": evidencias,
                    "mensagem": f"Gerou mas não capturou XML no sino ({alvo_n} lote(s)). Screenshot: {shot}"}

        return {"status": "coletado", "competencia": mes_ano, "arquivos": arquivos,
                "evidencias": evidencias,
                "mensagem": f"{len(arquivos)}/{alvo_n} demonstrativo(s) coletado(s) de {mes_ano}."}
