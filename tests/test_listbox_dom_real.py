"""O critério de "opção real" executado contra um DOM de verdade.

Crítica da revisão externa (29/09): os testes do placeholder confirmavam que o
JS *contém* certas palavras — não que ele se comporta. Isso não é teste, é
lembrete; um erro de regex ou de ordem passaria batido.

Aqui o JS roda num Chromium real, sobre HTML que reproduz os estados observados
no portal SASSEPE. Sem rede: `set_content` monta a página em memória.

Pula quando não há browser instalado (máquina de desenvolvimento). Roda na VPS,
que é onde o pytest é executado antes de cada deploy.
"""
import asyncio
import contextlib
import importlib

import pytest

_ui = importlib.import_module("adapters.sassepe._ui")


# Teto duro. Um pytest que trava e' pior que um teste que falta: a suite e' o
# portao de deploy da VPS, e em 29/09 uma fixture `scope="module"` assincrona
# com Playwright travou exatamente ali.
TIMEOUT_S = 25

# A VPS roda como root; sem --no-sandbox o Chromium nao sobe (e, dependendo do
# ambiente, fica pendurado em vez de erro).
ARGS_CHROMIUM = ["--no-sandbox", "--disable-dev-shm-usage"]


@contextlib.asynccontextmanager
async def _pagina_em_branco():
    """Chromium efemero, por teste. Sem fixture de modulo: fixture assincrona
    de escopo largo e' justamente o que travou. Pula (nao falha) quando nao ha'
    browser — maquina de desenvolvimento sem `playwright install`."""
    api = pytest.importorskip("playwright.async_api")
    try:
        gerenciador = api.async_playwright()
        pw = await asyncio.wait_for(gerenciador.__aenter__(), TIMEOUT_S)
    except Exception as e:
        pytest.skip(f"playwright indisponivel: {e}")
    browser = None
    try:
        try:
            browser = await asyncio.wait_for(
                pw.chromium.launch(args=ARGS_CHROMIUM), TIMEOUT_S)
        except asyncio.TimeoutError:
            pytest.skip(f"chromium nao subiu em {TIMEOUT_S}s neste ambiente")
        except Exception as e:
            pytest.skip(f"chromium indisponivel: {e}")
        page = await browser.new_page()
        # Nenhuma operacao de pagina pode ficar pendurada: o conteudo e' local
        # (set_content), entao 5s ja' e' folga grande.
        page.set_default_timeout(5000)
        try:
            yield page
        finally:
            await page.close()
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            await gerenciador.__aexit__(None, None, None)


def _pagina(corpo: str) -> str:
    """O listbox do portal: um container [role=listbox] com filhos de texto."""
    return f"<body style='margin:0'><div role='listbox'>{corpo}</div></body>"


VAZIO = "<div>Nenhum resultado</div>"
SPINNER = "<div><span>carregando</span></div>"
OPCAO = "<div>37499 - RODRIGO REBELLO FRANÇA</div>"
OUTRA = "<div>37499 - ROSALI JACOME MIRANDA COSTA</div>"


@pytest.mark.asyncio
async def test_estados_reais_do_portal():
    async with _pagina_em_branco() as page:
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


@pytest.mark.asyncio
async def test_sem_listbox_e_fechado():
    async with _pagina_em_branco() as page:
        await page.set_content("<body><p>sem dropdown aberto</p></body>")
        estado = await page.evaluate(_ui._JS_LISTBOX_ESTADO)
        assert estado["estado"] == "fechado"


@pytest.mark.asyncio
async def test_indice_aponta_para_a_opcao_e_nao_para_o_placeholder():
    """O bug de 29/09 em uma linha: com o spinner em children[0], a coordenada
    tem que sair do índice 1."""
    async with _pagina_em_branco() as page:
        await page.set_content(_pagina(SPINNER + OPCAO))
        estado = await page.evaluate(_ui._JS_LISTBOX_ESTADO)
        assert estado["indices"] == [1]
        coord = await page.evaluate(_ui._JS_COORD_POR_INDICE, estado["indices"][0])
        assert "RODRIGO" in coord["texto"]
        assert "carregando" not in coord["texto"].lower()
        assert coord["cx"] > 0 and coord["cy"] > 0


@pytest.mark.asyncio
async def test_acento_e_role_option():
    """O portal às vezes marca [role=option]; o texto vem com acento."""
    async with _pagina_em_branco() as page:
        await page.set_content(_pagina(
            "<div role='option'>carregando</div>"
            "<div role='option'>22523 - JUSSANA ELLEN ALVES DE ARRUDA RANGEL</div>"))
        estado = await page.evaluate(_ui._JS_LISTBOX_ESTADO)
        assert estado["estado"] == "ok"
        assert estado["opcoes"] == ["22523 - JUSSANA ELLEN ALVES DE ARRUDA RANGEL"]
        assert estado["indices"] == [1]
