"""
teste_varredura.py — Valida a varredura no portal real (Acompanhar Solicitacoes).

Faz tres coisas, com o Firefox VISIVEL:
  1. navega ate Acompanhar Solicitacoes;
  2. DESPEJA todos os campos do formulario (name/id/type) — assim fixamos de vez
     o seletor real das datas Periodo/Ate e do Status, sem adivinhar;
  3. roda a coleta e imprime as guias raspadas.

Uso (venv ativo):
    set -a && source .env && set +a
    BROWSER_HEADLESS=false python teste_varredura.py
"""
import re
import asyncio

import config
from portal import sessao, varredura


async def _dump_campos(page):
    print("\n--- CAMPOS DO FORMULARIO (para fixar seletores) ---")
    controles = await page.evaluate("""
        () => Array.from(document.querySelectorAll('input,select,button'))
            .map(e => ({
                tag: e.tagName.toLowerCase(),
                type: e.type || '',
                name: e.name || '',
                id: e.id || '',
                value: (e.value || '').slice(0, 20)
            }))
    """)
    for c in controles:
        if c["tag"] == "input" and c["type"] in ("hidden",):
            continue
        print(f"  {c['tag']:7} type={c['type']:10} name={c['name']:22} "
              f"id={c['id']:18} value={c['value']}")
    print("--- fim dos campos ---\n")


async def main():
    print(">> abrindo portal e indo para Acompanhar Solicitacoes...\n")
    async with sessao.navegador() as page:
        await sessao.login(page)

        try:
            await page.get_by_role(
                "link", name=re.compile("ACOMPANHAR", re.I)
            ).first.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1500)
            print(f"URL da tela de consulta: {page.url}")
        except Exception as e:
            print(f">>> ERRO ao abrir Acompanhar Solicitacoes: {e}")
            await page.wait_for_timeout(3000)
            return

        # 1) Dump dos campos — confirma os seletores das datas/status
        await _dump_campos(page)

        # 2) Coleta de verdade (reusa a logica de varredura.py via funcoes internas)
        from datetime import datetime, timedelta
        di = (datetime.now() - timedelta(days=config.VARREDURA_JANELA_DIAS)).strftime("%d/%m/%Y")
        df = datetime.now().strftime("%d/%m/%Y")
        print(f">> filtrando periodo {di} a {df}...")
        ok_periodo = await varredura._preencher_periodo(page, di, df)
        print(f"   preencheu periodo? {ok_periodo} "
              f"(se False, use o dump acima p/ achar o name real)")
        await varredura._clicar_buscar(page)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2500)

        guias = await varredura._raspar_tabela(page)
        print(f"\n>> {len(guias)} guia(s) raspada(s):")
        for g in guias[:15]:
            print(f"   prot={g['numero_protocolo']:>9}  "
                  f"status={g['status_portal']:<12} ({g['status_raw']})  "
                  f"{g['data']}  {g['paciente'][:30]}")
        if len(guias) > 15:
            print(f"   ... +{len(guias)-15} linhas")

        if not guias:
            print("   (nenhuma — confira o filtro de periodo ou se a busca rodou)")

        await page.wait_for_timeout(5000)


if __name__ == "__main__":
    asyncio.run(main())
