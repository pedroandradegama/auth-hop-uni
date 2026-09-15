"""O agente tem que ancorar o diagnóstico no relato do robô determinístico.

Incidente (14–15/set/2026, 3 execuções): o agente concluiu que
"a rota /workspace/solicitacoes não existe ou foi alterada no portal SASSEPE",
com plano de ação mandando trocar seletores — enquanto o robô já estava em
/solicitacoes/sp-sadt, tinha preenchido CPF e cabeçalho e adicionado um exame.
O 404 que ele citava era de uma URL que ELE inventou e visitou.

O `detalhe` já ia no prompt (falha.resumo() o inclui). O que faltava era (a) a
URL viva no momento da falha, que os adapters não preenchiam, e (b) o prompt
dizer que o detalhe é autoritativo — a única explicação que ele sugeria era
"identificou a mudança do portal".
"""
import importlib

from agente import FalhaDeterministica, MotivoFalha


class TestResumoDaFalha:
    def test_resumo_leva_detalhe_e_url_ao_prompt(self):
        f = FalhaDeterministica(
            motivo=MotivoFalha.ESTADO_INESPERADO,
            etapa="submit_sassepe",
            detalhe="Exame nao adicionado: Codigo '40901360' ... listbox vazio.",
            url="https://sassepe.maida.health/solicitacoes/sp-sadt",
        )
        r = f.resumo()
        assert "40901360" in r["detalhe"]
        assert r["url"].endswith("/solicitacoes/sp-sadt")


class TestPromptDoExecutor:
    @property
    def prompt(self):
        return importlib.import_module("agente.loop").SYSTEM_EXECUTOR

    def test_declara_o_detalhe_como_autoritativo(self):
        assert "AUTORITATIVO" in self.prompt

    def test_manda_usar_a_url_da_falha(self):
        assert "O campo 'url' da falha original diz ONDE o robô estava" in self.prompt
        assert "NÃO atribua a causa a rota" in self.prompt

    def test_proibe_atribuir_causa_a_erro_do_proprio_agente(self):
        assert "NUNCA use como causa raiz um erro que VOCÊ causou" in self.prompt

    def test_patch_sugerido_exige_evidencia(self):
        assert "patch_sugerido SÓ quando houver evidência direta" in self.prompt

    def test_permite_admitir_que_nao_sabe(self):
        assert "Se você não determinou a causa" in self.prompt

    def test_nao_induz_mais_a_hipotese_de_portal_mudado(self):
        """A regra 4 antiga dizia 'se identificou a mudança do portal,
        patch_sugerido' — a única explicação que o prompt oferecia."""
        assert "se identificou a mudança do portal" not in self.prompt


class TestUrlNosAdapters:
    def test_sassepe_propaga_a_url_viva(self):
        """O browser já fechou quando o handler externo roda; a URL precisa ser
        capturada DENTRO do async with."""
        src = importlib.import_module("adapters.sassepe.submit")
        assert hasattr(src, "_UrlNaFalha")
        import inspect
        corpo = inspect.getsource(src.executar)
        assert "_UrlNaFalha(page.url)" in corpo
        assert "url=e.url" in corpo
