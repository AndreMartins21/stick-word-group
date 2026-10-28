# Uma conta de serviço por carga de trabalho, nunca a default da Compute.
resource "google_service_account" "vm" {
  account_id   = "${var.nome}-vm"
  display_name = "stick-word-group (VM)"

  depends_on = [google_project_service.apis]
}

# datastore.user: ler/gravar o Firestore. logWriter: logs. aiplatform.user: chamar o Gemini.
# O secretAccessor é por segredo (secrets.tf) e o acesso aos buckets é por bucket (storage.tf).
resource "google_project_iam_member" "vm" {
  for_each = toset([
    "roles/datastore.user",
    "roles/logging.logWriter",
    "roles/aiplatform.user",
  ])

  project = var.project_id
  role    = each.value
  member  = google_service_account.vm.member
}
