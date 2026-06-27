"""
adapters/sassepe/_ui.py — Mecanica de UI do portal Sassepe (SPA React).

O Sassepe e' um SPA React. TODO dropdown e' um [role=listbox] com LAZY-LOAD:
a lista so' renderiza ~5 itens ate' um WheelEvent ser disparado DIRETAMENTE no
elemento [role=listbox]. scroll()/scrollTop NAO disparam o carregamento — esse
detalhe foi descoberto no piloto e e' o coracao de toda interacao com dropdown.

Esta mecanica foi validada no piloto (browser-harness/CDP) e aqui esta' portada
para Playwright preservando o metodo exato que funcionou:
  - geometria do label via page.evaluate (getBoundingClientRect)
  - clique no input por coordenada (label.x + largura/2, label.y + 35)
  - selecao do texto (Control+a) e digitacao via keyboard
  - WheelEvent disparado no [role=listbox] (lazy-load)
  - clique na opcao por texto dentro do listbox (exato, com fallback "includes")

Inputs React: NUNCA setar input.value via JS (nao dispara o estado). Sempre
clicar + digitar pelo teclado (page.keyboard), como aqui.
"""

# JS reutilizado: acha o N-esimo label pelo texto (com ou sem "*") e devolve o
# rect. `indice` resolve labels DUPLICADOS (ex.: "Código CBO" aparece nas secoes
# solicitante E executante — indice 0 e 1 respectivamente).
_JS_RECT_LABEL = """
([label_text, indice]) => {
  const labels = Array.from(document.querySelectorAll('*')).filter(e => {
    const t = e.textContent.trim();
    return (t === label_text + '*' || t === label_text)
      && e.getBoundingClientRect().width > 0;
  });
  const label = labels[indice];
  if (!label) return null;
  const r = label.getBoundingClientRect();
  return {lx: r.x, ly: r.y, lw: r.width};
}
"""

_JS_SCROLL_LABEL = """
([label_text, indice]) => {
  const labels = Array.from(document.querySelectorAll('*')).filter(e => {
    const t = e.textContent.trim();
    return (t === label_text + '*' || t === label_text)
      && e.getBoundingClientRect().width > 0;
  });
  const label = labels[indice];
  if (label) label.scrollIntoView({block: 'center'});
  return !!label;
}
"""

_JS_WHEEL_LISTBOX = """
() => {
  const lb = document.querySelector('[role=listbox]');
  if (lb) lb.dispatchEvent(new WheelEvent('wheel',
    {deltaY: 300, bubbles: true, cancelable: true, composed: true}));
}
"""


async def abrir_dropdown(page, label_text: str, search_term: str,
                         indice: int = 0) -> bool:
    """Abre o N-esimo dropdown sob `label_text` (indice resolve duplicados),
    digita `search_term` e forca o lazy-load (WheelEvent). Retorna False se o
    label nao existe na tela."""
    achou = await page.evaluate(_JS_SCROLL_LABEL, [label_text, indice])
    if not achou:
        return False
    await page.wait_for_timeout(300)
    rect = await page.evaluate(_JS_RECT_LABEL, [label_text, indice])  # rect fresco
    if not rect:
        return False
    await page.mouse.click(rect["lx"] + rect["lw"] / 2, rect["ly"] + 35)
    await page.wait_for_timeout(500)
    await page.keyboard.press("Control+a")
    await page.wait_for_timeout(200)
    await page.keyboard.type(search_term)
    await page.wait_for_timeout(2000)
    await page.evaluate(_JS_WHEEL_LISTBOX)  # REQUERIDO p/ lazy-load
    await page.wait_for_timeout(800)
    return True


async def clicar_opcao_listbox(page, option_text: str) -> bool:
    """Clica a opcao do listbox cujo texto bate (exato; fallback 'includes')."""
    coord = await page.evaluate(
        """(opt) => {
          let el = Array.from(
              document.querySelectorAll('[role=listbox] > *, [role=option]'))
            .find(e => e.textContent.trim() === opt);
          if (!el) el = Array.from(document.querySelectorAll('[role=listbox] > *'))
            .find(e => e.textContent.trim().includes(opt));
          if (!el) return null;
          el.scrollIntoView({block: 'nearest'});
          const r = el.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }""",
        option_text,
    )
    if not coord:
        return False
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_timeout(800)
    return True


async def preencher_dropdown(page, label_text: str, search_term: str,
                             option_text: str) -> bool:
    """abrir_dropdown + clicar_opcao. Retorna True so' se a opcao foi clicada."""
    if not await abrir_dropdown(page, label_text, search_term):
        return False
    return await clicar_opcao_listbox(page, option_text)


async def preencher_cbo(page, indice: int = 0) -> bool:
    """CBO 999999: unica opcao apos abrir; clica o 1o item do listbox.
    `indice` escolhe a secao: 0 = Contratado solicitante, 1 = executante (ha'
    DUAS labels 'Código CBO' identicas na pagina)."""
    from . import config
    if not await abrir_dropdown(page, "Código CBO", config.CBO_SEARCH, indice=indice):
        return False
    coord = await page.evaluate(
        """() => {
          const lb = document.querySelector('[role=listbox]');
          if (!lb || !lb.children.length) return null;
          const el = lb.children[0];
          el.scrollIntoView({block: 'nearest'});
          const r = el.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not coord:
        return False
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_timeout(800)
    return True


async def marcar_paciente_no_local(page) -> bool:
    """Marca o checkbox 'Paciente no local' se ainda nao estiver marcado."""
    estado = await page.evaluate(
        """() => {
          const cb = Array.from(document.querySelectorAll('input[type=checkbox]'))
            .find(e => {
              const p = e.closest('label') || e.parentElement;
              return p && p.textContent.includes('Paciente no local');
            });
          if (!cb) return 'nao_achou';
          return cb.checked ? 'marcado' : 'desmarcado';
        }"""
    )
    if estado == "marcado":
        return True
    if estado == "nao_achou":
        return False
    coord = await page.evaluate(
        """() => {
          const el = Array.from(document.querySelectorAll('*')).find(e =>
            e.textContent.trim() === 'Paciente no local'
            && e.getBoundingClientRect().width > 0);
          if (!el) return null;
          el.scrollIntoView({block: 'center'});
          const r = el.getBoundingClientRect();
          return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
        }"""
    )
    if not coord:
        return False
    await page.mouse.click(coord["cx"], coord["cy"])
    await page.wait_for_timeout(500)
    return True
