# Segredos internos do WAHA. O valor é gerado por um recurso EFÊMERO e gravado com um argumento
# write-only: não aparece na tela, no plano nem no estado do Terraform. Para rotacionar, aumente
# var.versao_segredos (cria uma versão nova; a VM pega a "latest" no próximo deploy).
locals {
  segredos_gerados = toset(["WAHA_API_KEY", "WAHA_DASHBOARD_PASSWORD", "WAHA_HOOK_HMAC_KEY"])
  segredos = setunion(
    local.segredos_gerados,
    var.llm_provider == "anthropic" ? toset(["ANTHROPIC_API_KEY"]) : toset([]),
  )
}

resource "google_secret_manager_secret" "s" {
  for_each = local.segredos

  secret_id = each.value
  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# secretAccessor só em cada segredo, não no projeto (ADR-0007).
resource "google_secret_manager_secret_iam_member" "vm" {
  for_each = local.segredos

  secret_id = google_secret_manager_secret.s[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.vm.member
}

ephemeral "random_password" "s" {
  for_each = local.segredos_gerados

  length  = 48
  special = false # vai para um .env e para cabeçalhos HTTP
}

resource "google_secret_manager_secret_version" "s" {
  for_each = local.segredos_gerados

  secret                 = google_secret_manager_secret.s[each.key].id
  secret_data_wo         = ephemeral.random_password.s[each.key].result
  secret_data_wo_version = var.versao_segredos
}

# ANTHROPIC_API_KEY (só com llm_provider = "anthropic") nasce sem versão: quem coloca a chave é
# você, com infra/secrets.sh, em outro terminal.
