"""
config.py — Configuracao do adapter Unimed Recife.

Todos os "valores magicos" do portal que estavam hardcoded no unimed_bot.py
original foram extraidos para ca. Quando o portal mudar, o conserto e' aqui,
nao espalhado pelo codigo de automacao.

Credenciais NAO tem default embutido (de proposito). Se faltar variavel de
ambiente, o processo falha cedo e alto, em vez de logar com credencial fixa.
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


# ── Portal ──────────────────────────────────────────────────────────────
PORTAL_URL = os.environ.get(
    "UNIMED_PORTAL_URL",
    "https://autorizador.unimedrecife.com.br/index_admin.php",
)

# ── Credenciais (SEM default — leitura preguicosa via getters) ───────────
def unimed_user() -> str:
    return _req("UNIMED_USER")


def unimed_pass() -> str:
    return _req("UNIMED_PASS")


def email_prestador() -> str:
    return _req("EMAIL_PRESTADOR")


def setor() -> str:
    return os.environ.get("SETOR", "receptivo")


# ── Callback para o HOP (Edge Function receive-autorizacao) ──────────────
def callback_url() -> str:
    return _req("HOP_CALLBACK_URL")


def callback_hmac_secret() -> str:
    return _req("HOP_CALLBACK_SECRET")


# ── POLL (worker puxa job da Edge Function proximo-job-autorizacao) ──────
def proximo_job_url() -> str:
    return _req("HOP_PROXIMO_JOB_URL")


def worker_inbound_secret() -> str:
    return _req("WORKER_INBOUND_SECRET")


# Intervalo do poll: rapido apos processar (pode haver fila), lento quando ocioso.
POLL_INTERVAL_SEG = int(os.environ.get("POLL_INTERVAL_SEG", "15"))
POLL_INTERVAL_OCIOSO_SEG = int(os.environ.get("POLL_INTERVAL_OCIOSO_SEG", "60"))


# ── Valores fixos do formulario do portal ───────────────────────────────
# Mapeamento sub-tipo de exame -> value do <select subtipotratamento>
SUBTIPO_VALUE = {
    "RM": "169",
    "TC": "170",
}

# Selects de valor fixo no fluxo "Gerar Solicitacao"
ESPECIALIDADE_VALUE = "125"     # select[name="especialidadencooperados"]
TIPO_TRATAMENTO_VALUE = "0_42"  # select[name="tipo"]
TIPO_PRESTADOR_VALUE = "NP"     # select[name="tipoprestador"]
NGL_VALUE = "N"                 # select[name="ngl"]
URGENCIA_VALUE = "N"            # #urgencia
ESTADO_LOCALIDADE_VALUE = "16"  # select[name="estadolocalidade"] (PE)
CIDADE_LOCALIDADE_VALUE = "2964"  # select[name="cidadelocalidade"]

# ── Janela da varredura ──────────────────────────────────────────────────
# A operadora leva ~8-10 dias corridos. 15 cobre com folga + resolucao tardia.
VARREDURA_JANELA_DIAS = int(os.environ.get("VARREDURA_JANELA_DIAS", "15"))

# ── Browser ──────────────────────────────────────────────────────────────
# Padronizado em firefox (alinha com o Dockerfile original). NAO usar chromium
# sem alinhar install + launch nos dois lugares.
BROWSER_ENGINE = "firefox"
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"

# ── Diretorios ───────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "Solicitacoes")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
