"""codigos.py — Resolucao de codigo p/ o CONNECTA. Identidade (o portal aceita
o proprio TUSS no autocomplete), igual ao unimed_recife. CSV = validacao leve."""
import csv
import os

_CACHE: dict | None = None
_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "codigos_unimed_intercambio.csv")


def _carregar() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        with open(_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cod = (row.get("codigo") or "").strip()
                if cod:
                    _CACHE[cod] = {"nome": (row.get("nome") or "").strip()}
    return _CACHE


def resolver_codigo_portal(codigo_tuss: str) -> str:
    """Identidade: o codigo que vai no autocomplete e' o proprio TUSS."""
    return (codigo_tuss or "").strip()


def conhecido(codigo_tuss: str) -> bool:
    return (codigo_tuss or "").strip() in _carregar()
