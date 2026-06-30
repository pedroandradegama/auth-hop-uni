"""
adapters/sulamerica/_ui.py — Mecanica de UI e helpers do portal SulAmerica.

O portal e' server-rendered (jQuery) e o formulario SP/SADT vive dentro de um
IFRAME. Os helpers aqui resolvem: achar o frame certo, tirar evidencia (I4),
quebrar carteirinha/medico e validar anexos. Portados do molde do colega,
preservando os seletores reais ja' validados no portal.
"""
import os
import re
import shutil
from datetime import datetime

from . import config


# ── Evidencia (I4) ────────────────────────────────────────────────────────
async def snap(page, etapa: str, evidencias: list) -> str:
    """Screenshot full-page; registra o caminho em `evidencias` (contrato)."""
    os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(config.SCREENSHOTS_DIR, f"sulamerica_{etapa}_{ts}.png")
    try:
        await page.screenshot(path=caminho, full_page=True)
        evidencias.append({"ts": datetime.now().isoformat(), "etapa": etapa,
                           "screenshot_path": caminho})
    except Exception:
        pass
    return caminho


# ── Frame finder ──────────────────────────────────────────────────────────
async def achar_frame(page, seletor: str, tentativas: int = 5, espera_ms: int = 2000):
    """Acha o frame (ou a propria page) que contem `seletor`. O SP/SADT do
    SulAmerica fica em iframe — esta busca evita depender da URL do frame."""
    for _ in range(tentativas):
        for frame in [page] + page.frames:
            try:
                if await frame.query_selector(seletor):
                    return frame
            except Exception:
                continue
        await page.wait_for_timeout(espera_ms)
    return None


# ── Carteirinha ────────────────────────────────────────────────────────────
def split_carteirinha(carteirinha: str):
    """Quebra a carteirinha SulAmerica (20 digitos) no formato 3-5-4-4-4.
    Hard stop (I1): identificador invalido aborta antes de abrir browser."""
    digitos = "".join(filter(str.isdigit, carteirinha or ""))
    if len(digitos) != 20:
        raise ValueError(
            f"Carteirinha SulAmerica invalida: '{carteirinha}' tem "
            f"{len(digitos)} digito(s); exige 20 (formato 3-5-4-4-4)."
        )
    return digitos[0:3], digitos[3:8], digitos[8:12], digitos[12:16], digitos[16:20]


# ── Medico (CRM + nome) ─────────────────────────────────────────────────────
def split_medico(medico: str):
    """Quebra o `medico` do job em (crm, nome). O portal preenche o NOME num
    campo e o numero do CONSELHO (CRM) noutro — por isso precisamos dos dois.

    Formatos aceitos (HOP):
      "16188 NUBIA ROSA LOPES"   -> ("16188", "NUBIA ROSA LOPES")
      "16188 - NUBIA ROSA LOPES" -> ("16188", "NUBIA ROSA LOPES")
      "NUBIA ROSA LOPES"         -> (None, "NUBIA ROSA LOPES")
    """
    t = (medico or "").strip()
    m = re.match(r"^\s*(\d+)\s*-?\s*(.*)$", t)
    if m and m.group(1):
        return m.group(1), m.group(2).strip().upper()
    return None, t.upper()


# ── Anexo ────────────────────────────────────────────────────────────────────
def validar_arquivo(caminho: str):
    """Portal exige extensao jpg/jpeg/pdf e nome sem caracteres especiais.
    Retorna (caminho_valido_ou_None, motivo_erro_ou_None). Se o nome tiver
    caractere especial, copia para um nome limpo."""
    nome = os.path.basename(caminho)
    nome_base, ext = os.path.splitext(nome)
    ext = ext.lower().lstrip(".")

    if ext not in config.ANEXO_EXTS_OK:
        return None, f"Formato '.{ext}' nao aceito (use {', '.join(config.ANEXO_EXTS_OK)})"

    nome_limpo = re.sub(r"[^a-zA-Z0-9 _\-]", "", nome_base)
    if nome_limpo != nome_base:
        novo = os.path.join(os.path.dirname(caminho), f"{nome_limpo}.{ext}")
        try:
            shutil.copy(caminho, novo)
            return novo, None
        except Exception as e:
            return None, f"Falha ao renomear arquivo: {e}"
    return caminho, None
