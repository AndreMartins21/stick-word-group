terraform {
  required_version = ">= 1.11" # write-only (secret_data_wo) + recurso efêmero (ADR-0063)

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.46"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }

  # Estado remoto num bucket do próprio projeto. O nome vem do `make tf-init`
  # (-backend-config=bucket=<projeto>-tfstate), para o mesmo código servir a outro projeto.
  backend "gcs" {
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone

  # Com credencial de usuário (ADC), APIs como a de Budgets exigem um projeto de cota.
  billing_project       = var.project_id
  user_project_override = true
}
