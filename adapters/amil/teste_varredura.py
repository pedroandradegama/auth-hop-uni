"""
teste_varredura_amil.py
Testa apenas a varredura/consulta no portal Amil. Só leitura — seguro.
Execute com: set -a && source .env && set +a && python teste_varredura_amil.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapters.amil.varredura import coletar


async def main():
    janela = int(os.getenv("VARREDURA_JANELA_DIAS", "30"))
    print(f"Amil: iniciando varredura (janela={janela} dias)...")

    guias = await coletar(janela_dias=janela)
    print(f"Amil: {len(guias)} guia(s) encontrada(s)")
    print(json.dumps(guias, ensure_ascii=False, indent=2))

    # Verificação do mapa de status
    status_encontrados = {g["status_raw"] for g in guias}
    status_norm        = {g["status_portal"] for g in guias}
    print(f"\nStatus raw encontrados:       {status_encontrados}")
    print(f"Status normalizados:           {status_norm}")

    if "DESCONHECIDO" in status_norm:
        print("AVISO: há status não mapeados — ajuste config.STATUS_MAP.")


if __name__ == "__main__":
    asyncio.run(main())
