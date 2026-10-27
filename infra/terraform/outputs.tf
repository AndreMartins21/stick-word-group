output "vm_name" {
  value = google_compute_instance.vm.name
}

output "github_variables" {
  description = "Variables do GitHub Actions (Settings → Secrets and variables → Actions)."
  value = {
    GCP_PROJECT_ID   = var.project_id
    GCP_WIF_PROVIDER = google_iam_workload_identity_pool_provider.github.name
  }
}

output "audio_bucket" {
  value = google_storage_bucket.audio.name
}

output "metrics_bucket" {
  value = google_storage_bucket.metrics.name
}

output "metrics_dataset" {
  value = google_bigquery_dataset.metrics.dataset_id
}
