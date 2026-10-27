#!/usr/bin/env bash
# Configuração comum dos scripts de operação (deploy, pair, logs, ssh, smoke): é "sourced" pelos
# outros, não executa nada sozinho. Quem cria os recursos é o Terraform (infra/terraform, ADR-0063).
# Valores não secretos vêm de infra/.env.infra (não versionado; modelo em .env.infra.example).
# shellcheck shell=bash
# shellcheck disable=SC2034  # as variáveis são usadas pelos scripts que fazem `source` deste arquivo

INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ_DIR="$(dirname "$INFRA_DIR")"

if [[ -f "$INFRA_DIR/.env.infra" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$INFRA_DIR/.env.infra"
  set +a
fi

# Sem prompts do gcloud: um "ativar a API? (y/N)" numa leitura nunca deve ativar nada por acidente.
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

PROJECT_ID="${GCP_PROJECT_ID:-}"
if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -z "$PROJECT_ID" ]]; then
  echo "Defina GCP_PROJECT_ID em infra/.env.infra (ou 'gcloud config set project ...')." >&2
  exit 1
fi

# Nomes dos recursos: precisam bater com os de infra/terraform.
ZONE="us-central1-a"
VM_NAME="stick-word-group-vm"
AUDIO_BUCKET="${AUDIO_BUCKET:-${PROJECT_ID}-audio}"
METRICS_BUCKET="${METRICS_BUCKET:-${PROJECT_ID}-metrics}"
TTS_VOICE="${TTS_VOICE:-en-US-Neural2-F}"
LLM_PROVIDER="${LLM_PROVIDER:-vertex_gemini}"

SSH_FLAGS=(--zone "$ZONE" --project "$PROJECT_ID" --tunnel-through-iap)

# Verdadeiro se o comando (de leitura) termina com sucesso.
existe() {
  "$@" &>/dev/null
}
