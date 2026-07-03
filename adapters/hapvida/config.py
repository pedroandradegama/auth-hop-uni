"""adapters/hapvida/config.py — Config do adapter Hapvida (Portal do Prestador). SPA React → chromium."""
import os


def _req(nome: str) -> str:
    v = os.environ.get(nome)
    if not v:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {nome}. Configure o .env.")
    return v


PORTAL_URL = os.environ.get("HAPVIDA_PORTAL_URL", "https://portalprestador.hapvida.com.br/login")
BROWSER_ENGINE = os.environ.get("HAPVIDA_BROWSER_ENGINE", "chromium")
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() != "false"


def hapvida_user() -> str:
    return _req("HAPVIDA_USER")


def hapvida_pass() -> str:
    return _req("HAPVIDA_PASS")
