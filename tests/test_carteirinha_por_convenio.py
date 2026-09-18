"""Carteirinha inválida num convênio que não usa carteirinha não pode derrubar job.

Caso (17–18/set/2026): o HOP mandava o CPF do paciente no campo `carteirinha`
para o Sassepe, que identifica por CPF e cujo adapter sequer lê esse campo.
O gate genérico (>=15 dígitos) era um field_validator — roda antes de o modelo
saber o convênio — e reprovava o job inteiro.

Em 17/09 isso virava reserva órfã (o worker logava e seguia; o watchdog escalava
40 min depois, em branco). Depois de 8e0a754 o job passou a ser devolvido com a
mensagem certa — mas ainda reprovado, por um campo que ninguém ia ler.
"""
import importlib

import pytest

schemas = importlib.import_module("schemas")
JobPreAutorizacao = schemas.JobPreAutorizacao


def _job(**over):
    base = {
        "job_id": "j1", "idempotency_key": "k1", "org_id": "o1",
        "convenio": "sassepe", "cpf": "40224490478",
        "medico": "NAYARA ROCHA", "crm": "23607",
        "codigos": [{"codigo_tuss": "40901122"}],
        "anexos": [{"url": "https://x/y.jpg", "nome": "y.jpg"}],
    }
    base.update(over)
    return base


class TestConvenioSemCarteirinha:
    def test_o_caso_real_passa(self):
        """CPF no campo carteirinha: ruído do HOP, não defeito do job."""
        j = JobPreAutorizacao(**_job(carteirinha="402.244.904-78"))
        assert j.cpf == "40224490478"
        assert j.carteirinha is None      # descartada, não propagada ao adapter

    def test_sem_carteirinha_continua_normal(self):
        assert JobPreAutorizacao(**_job()).carteirinha is None

    def test_so_carteirinha_e_sem_cpf_ainda_reprova(self):
        """Sem CPF não há como identificar o beneficiário no Sassepe."""
        with pytest.raises(Exception) as ei:
            JobPreAutorizacao(**_job(cpf=None, carteirinha="402.244.904-78"))
        assert "CPF" in str(ei.value) or "identificador" in str(ei.value)


class TestConvenioComCarteirinha:
    def test_gate_de_15_digitos_segue_valendo(self):
        with pytest.raises(Exception) as ei:
            JobPreAutorizacao(**_job(
                convenio="unimed_intercambio", cpf=None,
                carteirinha="402.244.904-78",
                codigos=[{"codigo_tuss": "40901122"}], anexos=[]))
        assert "minimo 15" in str(ei.value)

    def test_carteirinha_valida_passa(self):
        j = JobPreAutorizacao(**_job(
            convenio="unimed_intercambio", cpf=None,
            carteirinha="8650001868350308", anexos=[]))
        assert j.carteirinha == "8650001868350308"

    def test_sulamerica_de_20_digitos_passa(self):
        j = JobPreAutorizacao(**_job(
            convenio="sulamerica", cpf=None,
            carteirinha="01234567890123456789"))
        assert j.carteirinha == "01234567890123456789"
