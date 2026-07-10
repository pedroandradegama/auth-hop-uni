# ============================================================================
# agente/pruner.py  (v0.1.0)
# Snapshot compacto da página: SÓ elementos interativos + headings + alerts.
# É a peça que protege o custo — nunca mandar DOM cru pro modelo.
# Saída alvo: 3–5K tokens. Refs estáveis (e1, e2...) mapeadas a locators no
# runtime; o modelo enxerga apenas as refs.
# Máscara de PII: CPFs/telefones fora dos dados do job são mascarados.
# ============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_ELEMENTOS = 120
MAX_TEXTO_ELEMENTO = 90
MAX_CHARS_SNAPSHOT = 16_000  # ~4K tokens

RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
RE_FONE = re.compile(r"(?:\+?55\s?)?(?:\(\d{2}\)\s?|\b\d{2}\s)?9?\d{4}[-\s]?\d{4}\b")

# JS executado na página: coleta elementos interativos e estruturais visíveis.
_JS_COLETA = """
() => {
  const visivel = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const rotulo = (el) => {
    if (el.labels && el.labels.length) return el.labels[0].innerText;
    return el.getAttribute('aria-label') || el.getAttribute('placeholder')
        || el.getAttribute('name') || el.getAttribute('title') || '';
  };
  const itens = [];
  const seletor = 'input, select, textarea, button, a[href], [role="button"], [role="tab"], [onclick]';
  document.querySelectorAll(seletor).forEach((el) => {
    if (!visivel(el)) return;
    const tag = el.tagName.toLowerCase();
    const item = {
      tag,
      tipo: el.getAttribute('type') || (el.getAttribute('role') || ''),
      rotulo: (rotulo(el) || '').trim(),
      texto: (el.innerText || '').trim(),
      valor: tag === 'input' || tag === 'textarea' ? (el.value || '') : '',
      id: el.id || '',
      name: el.getAttribute('name') || '',
      desabilitado: el.disabled === true,
      marcado: el.checked === true,
      opcoes: tag === 'select'
        ? Array.from(el.options).slice(0, 25).map(o => o.text.trim())
        : undefined,
    };
    itens.push(item);
  });
  const estrutura = [];
  document.querySelectorAll('h1, h2, h3, [role="alert"], .alert, .error, .erro, .aviso, .mensagem').forEach((el) => {
    if (!visivel(el)) return;
    const t = (el.innerText || '').trim();
    if (t) estrutura.push({ tag: el.tagName.toLowerCase(), texto: t });
  });
  const modais = [];
  document.querySelectorAll('[role="dialog"], .modal.show, .modal[style*="display: block"]').forEach((el) => {
    if (!visivel(el)) return;
    modais.push((el.innerText || '').trim().slice(0, 600));
  });
  return { itens, estrutura, modais, titulo: document.title, url: location.href };
}
"""


@dataclass
class Snapshot:
    texto: str                       # o que vai pro modelo
    refs: dict[str, dict[str, Any]] = field(default_factory=dict)  # ref -> metadados p/ localizar


def _mascarar_pii(texto: str, permitidos: set[str]) -> str:
    def _cpf(m: re.Match) -> str:
        bruto = re.sub(r"\D", "", m.group(0))
        return m.group(0) if bruto in permitidos else "XXX.XXX.XXX-XX"

    texto = RE_CPF.sub(_cpf, texto)
    # Telefones nunca são necessários no fluxo de autorização — mascara todos.
    texto = RE_FONE.sub("(XX) XXXXX-XXXX", texto)
    return texto


def _linha_elemento(ref: str, e: dict[str, Any]) -> str:
    partes = [f"[{ref}]", e["tag"] + (f"/{e['tipo']}" if e.get("tipo") else "")]
    rot = (e.get("rotulo") or e.get("texto") or "")[:MAX_TEXTO_ELEMENTO]
    if rot:
        partes.append(f'"{rot}"')
    if e.get("valor"):
        partes.append(f"valor={e['valor'][:40]!r}")
    if e.get("marcado"):
        partes.append("marcado")
    if e.get("desabilitado"):
        partes.append("DESABILITADO")
    if e.get("opcoes"):
        partes.append("opções: " + " | ".join(e["opcoes"][:15]))
    return " ".join(partes)


async def podar(page: Any, cpfs_do_job: set[str] | None = None) -> Snapshot:
    """Gera snapshot compacto da page (Playwright async). cpfs_do_job: dígitos
    puros dos CPFs legítimos do job (não serão mascarados)."""
    bruto = await page.evaluate(_JS_COLETA)
    permitidos = cpfs_do_job or set()

    linhas: list[str] = [f"URL: {bruto['url']}", f"TÍTULO: {bruto['titulo']}"]

    if bruto["modais"]:
        linhas.append("── MODAL/DIÁLOGO ABERTO ──")
        for m in bruto["modais"][:2]:
            linhas.append(m)

    if bruto["estrutura"]:
        linhas.append("── ESTRUTURA/ALERTAS ──")
        for s in bruto["estrutura"][:20]:
            linhas.append(f"{s['tag']}: {s['texto'][:150]}")

    linhas.append("── ELEMENTOS INTERATIVOS ──")
    refs: dict[str, dict[str, Any]] = {}
    for i, e in enumerate(bruto["itens"][:MAX_ELEMENTOS], start=1):
        ref = f"e{i}"
        refs[ref] = {"id": e.get("id"), "name": e.get("name"),
                     "rotulo": e.get("rotulo"), "texto": e.get("texto"),
                     "tag": e.get("tag")}
        linhas.append(_linha_elemento(ref, e))

    texto = _mascarar_pii("\n".join(linhas), permitidos)
    if len(texto) > MAX_CHARS_SNAPSHOT:
        texto = texto[:MAX_CHARS_SNAPSHOT] + "\n[snapshot truncado]"
    return Snapshot(texto=texto, refs=refs)


def localizar(page: Any, refs: dict[str, dict[str, Any]], ref: str) -> Any:
    """Resolve uma ref do snapshot para um Locator do Playwright, na ordem:
    id > name > rótulo > texto. Lança KeyError se ref desconhecida."""
    meta = refs[ref]
    if meta.get("id"):
        return page.locator(f"#{meta['id']}")
    if meta.get("name"):
        return page.locator(f"[name={meta['name']!r}]").first
    if meta.get("rotulo"):
        return page.get_by_label(meta["rotulo"], exact=False).first
    if meta.get("texto"):
        return page.get_by_text(meta["texto"], exact=False).first
    raise KeyError(f"ref {ref} sem âncora localizável")
