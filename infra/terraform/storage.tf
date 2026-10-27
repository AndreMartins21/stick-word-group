# Cache dos áudios de pronúncia (M23). Sem lifecycle: o áudio é regenerável, mas gerar de novo
# custa cota do TTS (ADR-0024).
resource "google_storage_bucket" "audio" {
  name                        = "${var.project_id}-audio"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "audio_vm" {
  bucket = google_storage_bucket.audio.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.vm.member
}

# Snapshot diário de métricas em NDJSON (M28, ADR-0029): termos/ expira em 30 dias, o resto em 400.
resource "google_storage_bucket" "metrics" {
  name                        = "${var.project_id}-metrics"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age            = 30
      matches_prefix = ["snapshot/termos/"]
    }
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 400
    }
  }

  depends_on = [google_project_service.apis]
}

# A VM só ESCREVE aqui, sem ler nem acessar o BigQuery: quem lê é a SA do painel (ADR-0029).
resource "google_storage_bucket_iam_member" "metrics_vm" {
  bucket = google_storage_bucket.metrics.name
  role   = "roles/storage.objectCreator"
  member = google_service_account.vm.member
}

# Dataset em US (multi-região): junta com o export do Billing (também US) numa mesma consulta. As
# tabelas externas e as views ficam de fora, de propósito: precisam de um snapshot já gravado
# (spec/plano-dashboard.md, seção 3.6).
resource "google_bigquery_dataset" "metrics" {
  dataset_id  = replace("${var.nome}_metrics", "-", "_")
  location    = "US"
  description = "Snapshot diário de métricas do stick-word-group (M28, ADR-0029)"

  depends_on = [google_project_service.apis]
}
