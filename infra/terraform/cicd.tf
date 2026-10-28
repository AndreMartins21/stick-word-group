# Deploy contínuo via GitHub Actions com Workload Identity Federation (seção 10.9, ADR-0013): sem
# chave de conta de serviço em arquivo.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.apis]
}

# A attribute_condition trava o token em repositório + main: nenhum fork, nenhuma outra branch e
# nenhum outro repositório troca o token por credencial do Google, mesmo copiando o workflow.
resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_repo}' && assertion.ref == 'refs/heads/main'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Só para o job de deploy; não é a identidade da VM e não lê segredo nenhum.
resource "google_service_account" "deploy" {
  account_id   = "${var.nome}-deploy"
  display_name = "Deploy do stick-word-group via GitHub Actions"

  depends_on = [google_project_service.apis]
}

resource "google_service_account_iam_member" "deploy_wif" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# No projeto, não por instância: o túnel IAP não aceita binding por instância, e o
# `gcloud compute scp/ssh` chama compute.projects.get, que só existe no escopo do projeto. Só há
# uma VM neste projeto, então na prática já fica restrito a ela (ADR-0013).
resource "google_project_iam_member" "deploy" {
  for_each = toset([
    "roles/iap.tunnelResourceAccessor",
    "roles/compute.viewer",
  ])

  project = var.project_id
  role    = each.value
  member  = google_service_account.deploy.member
}

# sudo via OS Login, só nesta VM.
resource "google_compute_instance_iam_member" "deploy_os_admin" {
  instance_name = google_compute_instance.vm.name
  zone          = var.zone
  role          = "roles/compute.osAdminLogin"
  member        = google_service_account.deploy.member
}

# A VM roda como a SA da VM; sem actAs sobre ela o SSH falha.
resource "google_service_account_iam_member" "deploy_act_as_vm" {
  service_account_id = google_service_account.vm.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deploy.member
}
