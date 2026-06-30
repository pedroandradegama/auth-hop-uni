"""
adapters/sulamerica/config.py — Configuracao do adapter Sul America Saude.

Todos os "valores magicos" do portal SulAmerica vivem aqui (espelha
config.py do Unimed/Sassepe, isolado no adapter). Credenciais SEM default:
faltou env -> processo falha cedo e alto.

Engine: o portal SulAmerica e' server-rendered classico (jQuery + iframes),
validado no molde do colega sob Firefox headless — mesma engine do Unimed.
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
    "SULAMERICA_PORTAL_URL",
    "https://saude.sulamericaseguros.com.br/prestador/login/?accessError=2",
)

# ── Credenciais (env PREFIXADO) ──────────────────────────────────────────
# CODIGO e SENHA sao obrigatorios; USUARIO tem default "master" (padrao do
# molde, normalmente o login mestre do prestador).
def sa_codigo() -> str:
    return _req("SULAMERICA_CODIGO")


def sa_usuario() -> str:
    return os.environ.get("SULAMERICA_USUARIO", "master")


def sa_senha() -> str:
    return _req("SULAMERICA_SENHA")


# ── Valores FIXOS do formulario SP/SADT (nunca variam por job) ───────────
# Conselho profissional do solicitante: 06 = CRM (medico). UF: 26 = PE.
# Se um dia entrar solicitante de outro conselho/UF, virar campo do job.
CONSELHO_SOLICITANTE = "06"   # CRM
UF_CONSELHO = "26"            # PE

# CBO do solicitante (clinico/medico) — autocomplete por codigo.
CBO_SOLICITANTE = "225125"

# Selects de valor fixo (value do <option>)
CARATER_ATENDIMENTO = "1"     # 1 = Eletivo
TECNICA_UTILIZADA = "1"       # 1 = Convencional
RECEM_NATO = "false"          # Nao

# Anexo: tipo de documento sempre 16 (Autorizacao previa).
TIPO_DOC_ANEXO = "16"

# Formatos de anexo aceitos pelo portal.
ANEXO_EXTS_OK = ("jpg", "jpeg", "pdf")

# ── Browser ──────────────────────────────────────────────────────────────
BROWSER_ENGINE = os.environ.get("SULAMERICA_BROWSER_ENGINE", "firefox")
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"

# ── Diretorios ───────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "evidencias")
