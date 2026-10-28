# A rede 'default' nasce sozinha quando a API do Compute é ativada.
data "google_compute_network" "default" {
  name = "default"

  depends_on = [google_project_service.apis]
}

# Sem porta pública: SSH só via IAP (35.235.240.0/20), só para a tag da VM.
resource "google_compute_firewall" "iap_ssh" {
  name          = "allow-iap-ssh"
  network       = data.google_compute_network.default.self_link
  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags   = [var.nome]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_instance" "vm" {
  name         = "${var.nome}-vm"
  machine_type = "e2-micro"
  tags         = [var.nome]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 30
      type  = "pd-standard"
    }
  }

  # IP externo efêmero (tier STANDARD): só para a VM SAIR para a internet; nada entra nela.
  network_interface {
    network = data.google_compute_network.default.self_link
    access_config {
      network_tier = "STANDARD"
    }
  }

  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin = "TRUE"
    startup-script = file("${path.module}/../vm/startup.sh")
  }

  allow_stopping_for_update = true

  depends_on = [google_project_iam_member.vm]

  lifecycle {
    # A imagem da família resolve para uma versão nova com o tempo; isso não deve recriar a VM
    # (e perder a sessão do WAHA, que vive no disco).
    ignore_changes = [boot_disk[0].initialize_params[0].image]
  }
}

# Backup (M53, ADR-0051): snapshot diário do disco, que guarda a sessão do WAHA. Sem ele, perder o
# disco = re-parear o QR e ficar fora do ar.
resource "google_compute_resource_policy" "snapshot_diario" {
  name        = "${var.nome}-snapshot-diario"
  region      = var.region
  description = "Snapshot diario do disco do stick-word-group (M53)"

  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = var.snapshot_hora_utc
      }
    }
    retention_policy {
      max_retention_days    = var.snapshot_retencao_dias
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_compute_disk_resource_policy_attachment" "snapshot_diario" {
  name = google_compute_resource_policy.snapshot_diario.name
  disk = google_compute_instance.vm.name # o disco de boot tem o nome da VM
}
