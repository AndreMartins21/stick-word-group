# Infraestrutura do stick-word-group na GCP (seção 10 da spec, ADR-0063).
#
# Custo: e2-micro + disco standard de 30 GB em us-central1 = nível gratuito. O IP externo efêmero
# NÃO é gratuito (alguns dólares por mês) e o Vertex AI é pago por uso. Firestore, Storage, Secret
# Manager e BigQuery ficam nas cotas gratuitas. Nada de Cloud NAT, balanceador nem IP estático.

data "google_project" "este" {
  project_id = var.project_id
}

locals {
  apis = [
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "compute.googleapis.com",
    "iap.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "aiplatform.googleapis.com",
    "texttospeech.googleapis.com",
    "bigquery.googleapis.com",
    "billingbudgets.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service            = each.value
  disable_on_destroy = false
}

# --- Firestore (modo nativo, perto da VM) ------------------------------------------------------

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  # Backup (M53, ADR-0051): restaura de qualquer instante dos últimos 7 dias.
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"
  deletion_policy                   = "ABANDON"

  depends_on = [google_project_service.apis]

  lifecycle {
    prevent_destroy = true
  }
}

# A deduplicação de mensagens (processed) expira sozinha: sem TTL, pagaria armazenamento eterno.
resource "google_firestore_field" "processed_ttl" {
  database   = google_firestore_database.default.name
  collection = "processed"
  field      = "expira_em"

  ttl_config {}
}
