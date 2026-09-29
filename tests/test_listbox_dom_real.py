"""O critério de "opção real" executado contra um DOM de verdade.

Crítica da revisão externa (29/09): os testes do placeholder confirmavam que o
JS *contém* certas palavras — não que ele se comporta. Isso não é teste, é
lembrete; um erro de regex ou de ordem passaria batido.

Aqui o JS roda num Chromium real, sobre HTML que reproduz os estados observados
no portal SASSEPE. Sem rede: `set_content` monta a página em memória.

Pula quando não há browser instalado (máquina de desenvolvimento). Roda na VPS,
que é onde o pytest é executado antes de cada deploy.
"""
import importlib

import pytest

_ui = importlib.import_module("adapters.sassepe._ui")


@pytest.fixture(scope="module")
async def _navegador():
    playwright = pytest.importorskip("playwright.async_api")
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception as e:
                pytest.skip(f"chromium nao instalado neste ambiente: {e}")
            yield browser
            await browser.close()
    except Exception as e:                       # driver ausente
        pytest.skip(f"playwright indisponivel: {e}")


def _pagina(corpo: str) -> str:
    """O listbox do portal: um container [role=listbox] com filhos de texto."""
    return f"<body style='margin:0'><div role='listbox'>{corpo}</div></body>"


VAZIO = "<div>Nenhum resultado</div>"
SPINNER = "<div><span>carregando</span></div>"
OPCAO = "<div>37499 - RODRIGO REBELLO FRANÇA</div>"
OUTRA = "<div>37499 - ROSALI JACOME MIRANDA COSTA</div>"


@pytest.mark.asyncio
async def test_estados_reais_do_portal(_navegador):
    page = await _navegador.new_page()
    try:
        casos = [
            ("<div></div>",            "carregando", 0),   # container vazio
            (VAZIO,                    "vazio",      0),
            (SPINNER,                  "carregando", 0),
            (OPCAO,                    "ok",         1),
            (SPINNER + OPCAO,          "ok",         1),   # 29/09: CBO clicou no spinner
            (VAZIO + OPCAO,            "ok",         1),
            (OUTRA + OPCAO,            "ok",         2),
        ]
        for corpo, esperado, n in casos:
            await page.set_content(_pagina(corpo))
            estado = await page.evaluate(_ui._JS_LISTBOX_ESTADO)
            assert estado["estado"] == esperado, (corpo, estado)
            assert len(estado["opcoes"]) == n, (corpo, estado)
    finally:
        await page.close()


@pytest.mark.asyncio
async def test_sem_listbox_e_fechado(_navegador):
    page = await _navegador.new_page()
    try:
        await page.set_content("<body><p>sem dropdown aberto</p></body>")
        estado = await page.evaluate(_ui._JS_LISTBOX_ESTADO)
        assert estado["estado"] == "fechado"
    finally:
        await page.close()


@pytest.mark.asyncio
async def test_indice_aponta_para_a_opcao_e_nao_para_o_placeholder(_navegador):
    """O bug de 29/09 em uma linha: com o spinner em children[0], a coordenada
    tem que sair do índice 1."""
    page = await _navegador.new_page()
    try:
        await page.set_content(_pagina(SPINNER + OPCAO))
        estado = await page.evaluate(_ui._JS_LISTBOX_ESTADO)
        assert estado["indices"] == [1]
        coord = await page.evaluate(_ui._JS_COORD_POR_INDICE, estado["indices"][0])
        assert "RODRIGO" in coord["texto"]
        assert "carregando" not in coord["texto"].lower()
        assert coord["cx"] > 0 and coord["cy"] > 0
    finally:
        await page.close()


@pytest.mark.asyncio
async def test_acento_e_role_option(_navegador):
    """O portal às vezes marca [role=option]; o texto vem com acento."""
    page = await _navegador.new_page()
    try:
        await page.set_content(_pagina(
            "<div role='option'>carregando</div>"
            "<div role='option'>22523 - JUSSANA ELLEN ALVES DE ARRUDA RANGEL</div>"))
        estado = await page.evaluate(_ui._JS_LISTBOX_ESTADO)
        assert estado["estado"] == "ok"
        assert estado["opcoes"] == ["22523 - JUSSANA ELLEN ALVES DE ARRUDA RANGEL"]
        assert estado["indices"] == [1]
    finally:
        await page.close()
