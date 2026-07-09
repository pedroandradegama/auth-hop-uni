"""
teste_verificar.py (Unimed) — testa a ação `verificar` com uma senha real.
Read-only (só consulta). Execute com o .env carregado:
  set -a && source .env && set +a && python adapters/unimed_recife/teste_verificar.py 191866912
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapters.unimed_recife import verificar


async def main():
    senha = sys.argv[1] if len(sys.argv) > 1 else "191866912"
    print(f">> verificar(senha={senha}) — consulta read-only\n")
    r = await verificar(senha)
    # não despeja o base64 inteiro no terminal
    ev = r.get("evidencia_b64")
    r_print = {**r, "evidencia_b64": (f"<{len(ev)} chars>" if ev else None)}
    print(json.dumps(r_print, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
