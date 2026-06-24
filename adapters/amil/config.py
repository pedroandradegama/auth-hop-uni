"""
adapters/amil/config.py
Seletores 100% confirmados via inspeção do portal credenciado.amil.com.br (22/06/2026).
Portal Angular — usa formcontrolname e seletores estruturais estáveis.
"""
import os

# ---------------------------------------------------------------------------
# Credenciais — env prefixado, sem default (I6)
# ---------------------------------------------------------------------------
AMIL_USER = os.environ["AMIL_USER"]
AMIL_PASS = os.environ["AMIL_PASS"]

# ---------------------------------------------------------------------------
# URLs confirmadas
# ---------------------------------------------------------------------------
URL_LOGIN       = "https://credenciado.amil.com.br/login"
URL_AUTORIZACAO = "https://credenciado.amil.com.br/pedidos-autorizacao"
URL_CONSULTA    = "https://credenciado.amil.com.br/pedidos-autorizacao"

# ---------------------------------------------------------------------------
# MENU LATERAL
# ---------------------------------------------------------------------------
TEXTO_MENU_AUTORIZACAO = "Autorização prévia"

# ---------------------------------------------------------------------------
# LOGIN (portal pode usar SSO — seletores a confirmar se necessário)
# ---------------------------------------------------------------------------
SEL_LOGIN_USUARIO = "input[type='email'], input[name='username']"
SEL_LOGIN_SENHA   = "input[type='password']"
SEL_LOGIN_BTN     = "button[type='submit']"
SEL_LOGIN_ERRO    = ".alertas.error p, [role='alert'].error"

# ---------------------------------------------------------------------------
# BUSCA DO BENEFICIÁRIO
# Campo: as-elegibilidade → input[type='text'] (id="NaN" — bug Angular)
# ---------------------------------------------------------------------------
SEL_CAMPO_BENEFICIARIO = "as-elegibilidade input[type='text']"
SEL_BTN_CONSULTAR_PAC  = "as-elegibilidade button"
SEL_ERRO_BENEFICIARIO  = "as-elegibilidade .alertas p, as-message .alertas p"

# Select de beneficiário quando há dependentes na família
# Opções: "082803746 | MOISES", "082852173 | ANA BEATRIZ", "082852174 | MAYARA", ...
SEL_SELECT_BENEFICIARIO = "select#beneficiario"

# ---------------------------------------------------------------------------
# FORMULÁRIO DE NOVA AUTORIZAÇÃO — seletores por formcontrolname (estáveis)
# ---------------------------------------------------------------------------

# Tipo de atendimento (autocomplete — digitado e selecionado do dropdown)
SEL_TIPO_ATENDIMENTO   = "as-tipo-pedido-autocomplete input[role='combobox']"
VALOR_TIPO_ATENDIMENTO = "CONSULTA SP/SADT"

# Contato do beneficiário/profissional
SEL_TELEFONE_FIXO = "input[formcontrolname='telefone']"
SEL_TELEFONE_CEL  = "input[formcontrolname='celular']"
SEL_EMAIL         = "input[formcontrolname='email']"

# Informações do pedido
SEL_DATA_PEDIDO_MEDICO = "input#data-pedido-medico"          # obrigatório — dd/mm/aaaa
SEL_RN_NAO             = "input#rn-nao"                      # Atendimento RN = Não (padrão)
SEL_CARATER_ELETIVO    = "input#carater-eletivo"             # Caráter = Eletivo (padrão)
SEL_INDICACAO_CLINICA  = "textarea#indicacao-clinica"        # obrigatório

# Executante (prestador que realizará o exame)
SEL_EXEC_PRESTADOR     = "input#executor-prestador"          # radio "Prestador"
SEL_NOME_EXECUTANTE    = "input#nome-prestador-executante"   # nome/código do prestador
SEL_ENDERECO           = "select#endereco"                   # endereço de atendimento

# Profissional solicitante
SEL_CAMPO_MEDICO = "input[id='nome,-código-do-prestador,-cpf-ou-conselho']"
SEL_CAMPO_CBO_S  = "input#cbo-s"                            # obrigatório

# Valores FIXOS de preenchimento (decisao IMAG, nao vem do HITL)
INDICACAO_CLINICA_PADRAO = "Médico solicitou"
# CBO-S: PLACEHOLDER — Pedro confirma o valor correto (24/06). O portal exige.
# Trocar pelo CBO real antes do primeiro submit em producao.
CBO_S_PADRAO = "225320"  # <<< PLACEHOLDER — CONFIRMAR (ex.: 225320 = medico radiologista)

# ---------------------------------------------------------------------------
# PROCEDIMENTOS / SERVIÇOS
# Autocomplete: digitar → aguardar dropdown (#results) → clicar opção → Incluir
# O mesmo botão "Incluir" (button.incluir) serve para adicionar proc E enviar pedido
# ---------------------------------------------------------------------------
SEL_CAMPO_PROC_BUSCA = ".procedimentos-servicos input[role='combobox']"
SEL_PROC_DROPDOWN    = "#results"                           # ul com resultados
SEL_PROC_OPCAO       = "#results li[role='option']"        # primeira opção
SEL_LISTA_PROCS      = ".procedimentos-servicos .procedimento-adicionado, .procedimentos-servicos ul.adicionados li"

# ---------------------------------------------------------------------------
# BOTÕES DE AÇÃO DO FORMULÁRIO (confirmados)
# button.incluir[value="incluir"] serve para:
#   - adicionar procedimento (quando campo proc está preenchido)
#   - enviar o pedido inteiro (botão final no .container-botao[touranchor='tour4Concluir'])
# ---------------------------------------------------------------------------
SEL_BTN_INCLUIR          = "button.incluir[value='incluir']"
SEL_BTN_INCLUIR_FINAL    = ".container-botao[touranchor='tour4Concluir'] button.incluir"
SEL_BTN_CANCELAR         = "button.voltar"
SEL_BTN_CONFIRMAR_MODAL  = ".container-botao button.incluir, button[value='confirmar']"

# ---------------------------------------------------------------------------
# ANEXOS
# input#simple-upload (file) — aceita .PDF, .JPG, .TIF, .JPEG
# ---------------------------------------------------------------------------
SEL_INPUT_ANEXO  = "input#simple-upload"
SEL_LISTA_ANEXOS = ".anexos-relacionados li, .arquivo-adicionado, [class*='lista-anexo'] li"

# ---------------------------------------------------------------------------
# PROTOCOLO pós-gravar (I3 — conservador)
# ---------------------------------------------------------------------------
SEL_NUMERO_PROTOCOLO = "[class*='protocolo'], [class*='numero-pedido'], .numero-pedido"
SEL_PROTOCOLO_TOAST  = ".alertas.success, .toast-success, as-toast"

# ---------------------------------------------------------------------------
# VARREDURA — CONSULTA DE PEDIDOS (todos confirmados)
# ---------------------------------------------------------------------------
SEL_RADIO_PERSONALIZADO  = "input#PERSONALIZADO"
SEL_RADIO_MENSAL         = "input#MENSAL"
SEL_DATA_INICIAL         = "input#dataInicial"
SEL_DATA_FINAL           = "input#dataFinal"
TEXTO_BTN_PESQUISAR      = "Pesquisar"

# Filtros de status (IDs confirmados via inspeção)
SEL_CHK_AUTORIZADO    = "input#AUTORIZADO"
SEL_CHK_EM_ANALISE    = "input#EM_ANALISE"
SEL_CHK_NEGADO        = "input#NEGADO"
SEL_CHK_PENDENTE_DOC  = "input#PENDENTE_DOCUMENTACAO"
SEL_CHK_CANCELADO     = "input#CANCELADO"

# Tabela de resultados
SEL_TABELA_LINHAS = "table tbody tr"

# Índices de colunas (1-based, confirmados via aria-label)
COL_DATA_SOLICITACAO = 1   # "Data solicitação"
COL_PROTOCOLO_ANS    = 2   # "Protocolo ANS"
COL_PEDIDO           = 3   # "Pedido"       ← identificador principal
COL_SENHA            = 4   # "Senha"        ← CO2026...
COL_CARTEIRINHA      = 5   # "N° da carteirinha"
COL_DATA_AUTORIZACAO = 6   # "Data"
COL_SITUACAO         = 7   # "Situação"
COL_BENEFICIARIO     = 8   # "Beneficiário"

# ---------------------------------------------------------------------------
# MAPA DE STATUS — rótulos reais → vocabulário normalizado
# Confirmados: Validado(53), Em análise, Não validado, Cancelado, Pendente docs
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "validado":                  "AUTORIZADO",
    "não validado":              "NEGADO",
    "nao validado":              "NEGADO",
    "cancelado":                 "NEGADO",
    "em análise":                "EM_ANALISE",
    "em analise":                "EM_ANALISE",
    "pendente de documentação":  "EM_ANALISE",
    "pendente de documentacao":  "EM_ANALISE",
}

# ---------------------------------------------------------------------------
# TIMEOUTS (ms para Playwright)
# ---------------------------------------------------------------------------
TIMEOUT_NAVEGACAO    = 30_000
TIMEOUT_ELEMENTO     = 15_000
TIMEOUT_UPLOAD       = 60_000
TIMEOUT_ANGULAR      = 2_000
TIMEOUT_AUTOCOMPLETE = 3_000
