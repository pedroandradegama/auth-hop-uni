"""
teste_login.py (Unimed Intercambio / CONNECTA) — testa SO' o login + contexto.
Nao submete nada. Diagnostico: se o login falhar, dumpa o que a pagina REALMENTE
tem (URL, titulo, inputs/labels visiveis) — evita depurar as cegas quando o
portal muda de rotulo, cai, ou a rede da VPS falha.

Execute na VPS:
  cd /opt/imag-autorizador && set -a && source .env && set +a \
    && venv/bin/python adapters/unimed_intercambio/teste_login.py
Esperado: "LOGIN OK" + URL fora de Default.aspx/ErroLogin.
"""
import asyncio
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from adapters.unimed_intercambio import config, sessao


_JS_CAMPOS = """() => {
  const vis = (e) => { const r = e.getBoundingClientRect();
                       return r.width > 0 && r.height > 0; };
  const inputs = Array.from(document.querySelectorAll('input,select,textarea'))
    .filter(vis).slice(0, 25).map(e => ({
      tag: e.tagName, type: e.type || '', id: e.id || '', name: e.name || '',
      ph: e.placeholder || '', aria: e.getAttribute('aria-label') || '',
    }));
  const labels = Array.from(document.querySelectorAll('label')).filter(vis)
    .slice(0, 25).map(e => (e.textContent || '').replace(/\\s+/g, ' ').trim());
  return {inputs, labels, texto: (document.body.innerText || '').slice(0, 400)};
}"""


async def main():
    print(f">> CONNECTA: {config.PORTAL_URL}\n")
    async with sessao.navegador() as page:
        try:
            await sessao.login(page)
        except Exception as e:
            print(f">>> FALHOU no login/contexto: {type(e).__name__}: {e}\n")
            # diagnostico: o que a pagina tem de verdade?
            try:
                print(f"URL:    {page.url}")
                print(f"Titulo: {await page.title()}\n")
                d = await page.evaluate(_JS_CAMPOS)
                print("LABELS visiveis:", d["labels"] or "(nenhum)")
                print("\nCAMPOS visiveis:")
                for c in d["inputs"]:
                    print("  ", c)
                print("\nTEXTO (400 chars):\n", d["texto"])
                caminho = os.path.join(config.SCREENSHOTS_DIR,
                                       "teste_login_falha.png")
                os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
                await page.screenshot(path=caminho, full_page=True)
                print(f"\nScreenshot: {caminho}")
            except Exception as e2:
                print(f"(diagnostico indisponivel: {e2})")
            return

        print(f"URL apos login: {page.url}")
        print(f"Titulo: {await page.title()}\n")
        # Compara o PATH, nao substring: a area logada e' /connecta/Content/
        # Default.aspx, que CONTEM o path de login (/connecta/Default.aspx).
        def _path(u):
            return urlparse(u).path.rstrip("/").lower()

        if "errologin" in page.url.lower():
            print(">>> FALHOU: portal devolveu ErroLogin.")
        elif _path(page.url) == _path(config.PORTAL_URL):
            print(">>> ATENCAO: ainda na tela de login — FALHOU.")
        else:
            print(">>> LOGIN OK: autenticado e contexto selecionado.")


if __name__ == "__main__":
    asyncio.run(main())
