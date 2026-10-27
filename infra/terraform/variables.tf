variable "project_id" {
  description = "Projeto do Google Cloud (ex.: stick-word-group)."
  type        = string
}

variable "nome" {
  description = "Prefixo dos recursos (VM, contas de serviço, alertas)."
  type        = string
  default     = "stick-word-group"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "zone" {
  type    = string
  default = "us-central1-a"
}

variable "github_repo" {
  description = "Único repositório (owner/nome) cujo workflow, na main, pode fazer deploy (ADR-0013)."
  type        = string
  default     = "AndreMartins21/stick-word-group"
}

variable "llm_provider" {
  description = "vertex_gemini (padrão) ou anthropic; com anthropic cria o segredo ANTHROPIC_API_KEY vazio."
  type        = string
  default     = "vertex_gemini"

  validation {
    condition     = contains(["vertex_gemini", "anthropic"], var.llm_provider)
    error_message = "llm_provider precisa ser vertex_gemini ou anthropic."
  }
}

variable "versao_segredos" {
  description = "Aumente para gerar novos valores dos segredos do WAHA (rotação). O valor nunca vai para o estado."
  type        = number
  default     = 1
}

variable "alerta_email" {
  description = "E-mail que recebe o alerta de sessão do WhatsApp caída (M56). Vazio não cria o alerta."
  type        = string
  default     = ""
}

variable "billing_account" {
  description = "Conta de faturamento (XXXXXX-XXXXXX-XXXXXX) para o Budget (M45). Vazio não cria o Budget."
  type        = string
  default     = ""
}

variable "orcamento_mensal" {
  description = "Valor do Budget por mês, na moeda da conta de faturamento (só alerta, não corta)."
  type        = number
  default     = 30
}

variable "budget_moeda" {
  description = "A API recusa moeda diferente da da conta de faturamento."
  type        = string
  default     = "BRL"
}

variable "snapshot_retencao_dias" {
  type    = number
  default = 7
}

variable "snapshot_hora_utc" {
  description = "Início do snapshot diário do disco (06:00 UTC = 03:00 em Brasília, longe dos lembretes)."
  type        = string
  default     = "06:00"
}
