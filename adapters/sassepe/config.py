"""
adapters/sassepe/config.py — Configuracao do adapter Sassepe (Maida Health).

Todos os "valores magicos" do portal Sassepe vivem aqui (espelha
config.py do Unimed, mas isolado no adapter). Credenciais SEM default:
faltou env -> processo falha cedo e alto.

Diferenca de engine: o Sassepe e' um SPA React e foi validado no piloto sob
Chromium (cliques por coordenada + WheelEvent no [role=listbox]). Por isso o
adapter usa Chromium por padrao, independente do BROWSER_ENGINE global (firefox,
usado pelo Unimed). set_input_files (anexo) funciona em qualquer engine.
"""
import os


def _req(nome: str) -> str:
    """Le variavel de ambiente obrigatoria. Falha cedo se ausente."""
    valor = os.environ.get(nome)
    if not valor:
        raise RuntimeError(
            f"Variavel de ambiente obrigatoria ausente: {nome}. "
            "Configure o .env antes de subir o worker."
        )
    return valor


# ── Portal ───────────────────────────────────────────────────────────────
PORTAL_URL = os.environ.get(
    "SASSEPE_PORTAL_URL",
    "https://sassepe.maida.health/sso/login",
)

# ── Credenciais (env PREFIXADO, sem default) ─────────────────────────────
def sassepe_user() -> str:
    return _req("SASSEPE_USER")


def sassepe_pass() -> str:
    return _req("SASSEPE_PASS")


# ── Workspace (perfil escolhido apos login) ──────────────────────────────
# O card do workspace e' identificado por conter estes dois textos.
WORKSPACE_MARCADORES = ("Workspace", "prestadores")

# ── Valores FIXOS do formulario SP/SADT (nunca variam por job) ───────────
# Profissional EXECUTANTE: sempre o mesmo (responsavel tecnico da IMAg).
PROF_EXECUTANTE_NUM = "21798"
PROF_EXECUTANTE_NOME = "21798 - PEDRO ANDRADE GAMA DE OLIVEIRA"

# CBO unico do portal — preenchido DUAS vezes (secao solicitante E executante).
CBO_SEARCH = "999999"          # termo de busca no dropdown de CBO
CBO_OPCAO = "999999 - null"    # rotulo (informativo; clicamos o 1o item)

# Selects de valor fixo (rotulo da opcao no [role=listbox])
REGIME_BUSCA, REGIME_OPCAO = "ambulatorial", "01 - Ambulatorial"
ESPECIALIDADE_BUSCA, ESPECIALIDADE_OPCAO = "clinica medica", "CLINICA MEDICA"
CARATER_BUSCA, CARATER_OPCAO = "eletivo", "1 - Eletivo"
TIPO_ATEND_BUSCA, TIPO_ATEND_OPCAO = "exame", "23 - Exame"

# Procedimentos: a Tabela e' SEMPRE 22 (Procedimentos e eventos em saude).
# Busca e match pelo numero para evitar problema com acento ("saude"/"saúde").
TABELA_NUM = "22"

# Anexo: tipo de documento sempre 03 (Pedido do profissional de saude).
TIPO_DOC_BUSCA, TIPO_DOC_OPCAO = "03", "03"

# ── Browser ──────────────────────────────────────────────────────────────
# Chromium por padrao (SPA React validado nele). Sobrescrever so' com cuidado.
BROWSER_ENGINE = os.environ.get("SASSEPE_BROWSER_ENGINE", "chromium")
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"

# ── Diretorios ───────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Evidencias do Sassepe ficam separadas das do Unimed.
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "evidencias")
