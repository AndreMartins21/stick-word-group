# Alerta por e-mail quando a sessão do WhatsApp cai (M56, ADR-0054). O bot registra `waha_status`
# (WARNING) a cada mudança da sessão; banido ou deslogado aparece como FAILED, STOPPED ou
# SCAN_QR_CODE. Roteiro de resposta: docs/runbooks/banimento-do-numero.md.
locals {
  filtro_sessao_caiu = <<-EOT
    resource.type="gce_instance" AND jsonPayload.evento="waha_status" AND jsonPayload.motivo=("FAILED" OR "STOPPED" OR "SCAN_QR_CODE")
  EOT
}

resource "google_monitoring_notification_channel" "email" {
  count = var.alerta_email == "" ? 0 : 1

  display_name = "${var.nome}-alerta-email"
  type         = "email"
  labels = {
    email_address = var.alerta_email
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "sessao_caiu" {
  count = var.alerta_email == "" ? 0 : 1

  display_name          = "${var.nome}-sessao-whatsapp-caiu"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email[0].id]

  conditions {
    display_name = "Sessão do WhatsApp fora do ar (FAILED, STOPPED ou SCAN_QR_CODE)"
    condition_matched_log {
      filter = trimspace(local.filtro_sessao_caiu)
    }
  }

  alert_strategy {
    auto_close = "1800s"
    notification_rate_limit {
      period = "3600s"
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = "A sessão do WhatsApp do stick-word-group saiu de WORKING. Siga docs/runbooks/banimento-do-numero.md (sessão caída x número banido)."
  }
}

# Budget com alertas em 50/90/100% (M45, ADR-0043). SÓ ALERTA (e-mail aos administradores da conta
# de faturamento); quem corta o gasto da IA é o orçamento diário do próprio bot (ADR-0044).
resource "google_billing_budget" "mensal" {
  count = var.billing_account == "" ? 0 : 1

  billing_account = var.billing_account
  display_name    = "${var.nome}-mensal"

  budget_filter {
    projects = ["projects/${data.google_project.este.number}"] # a API só aceita o número
  }

  amount {
    specified_amount {
      currency_code = var.budget_moeda
      units         = tostring(var.orcamento_mensal)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.5, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }

  depends_on = [google_project_service.apis]
}
