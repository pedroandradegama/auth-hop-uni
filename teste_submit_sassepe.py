"""
teste_submit_sassepe.py — Ensaio REAL do submit Sassepe (pagina 1 ate' Proximo).

Usa dados legitimos + arquivo local (nao baixa do HOP). O submit preenche a
pagina 1, clica 'Proximo' (reversivel) e para no gap conhecido (pos-Proximo nao
mapeado). Serve p/ (1) validar o port da pagina 1 em Playwright e (2) capturar
as evidencias que vao guiar o mapeamento das paginas seguintes.

Uso:
    set -a && source .env && set +a
    BROWSER_HEADLESS=true python teste_submit_sassepe.py
"""
import asyncio
import json
import importlib

# O __init__ do pacote faz `from .submit import executar as submit`, o que
# sombreia o atributo `submit`. importlib pega o MODULO real do sys.modules.
submit = importlib.import_module("adapters.sassepe.submit")

JOB = {
    "cpf": "64387720468",
    "medico": "25245 PRISCILLA CARDOSO LAMEIRA ANDRADE",
    "paciente_nome": "AUREA BARBOSA DA SILVA FISCHLER",
    "codigos": [{"codigo_tuss": "40808041", "sub_tipo": "RM",
                 "nome": "MAMOGRAFIA DIGITAL", "quantidade": 1}],
    "arquivos": ["/Users/pedro/Documents/MetaAds/Solicitações/Solicitacao 01.png"],
}


async def main():
    res = await submit.executar(JOB)
    print("\n=== RESULTADO ===")
    print(json.dumps({k: v for k, v in res.items() if k != "detalhe"},
                     ensure_ascii=False, indent=2))
    if res.get("evidencias"):
        print("\n=== EVIDENCIAS ===")
        for e in res["evidencias"]:
            print(f"  {e['etapa']}: {e['screenshot_path']}")


if __name__ == "__main__":
    asyncio.run(main())
