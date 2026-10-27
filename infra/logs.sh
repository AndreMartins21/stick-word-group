#!/usr/bin/env bash
# Acompanha os logs dos containers na VM. Uso: bash infra/logs.sh [waha|bot]
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=infra/config.sh
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

case "${1:-}" in
  "" | waha | bot) servico="${1:-}" ;;
  *) echo "Uso: bash infra/logs.sh [waha|bot]" >&2; exit 1 ;;
esac

# O /opt/stick-word-group é modo 700 (só root), então o comando inteiro roda sob sudo.
exec gcloud compute ssh "$VM_NAME" "${SSH_FLAGS[@]}" --command \
  "sudo bash -c 'cd /opt/stick-word-group/app && docker compose --env-file /opt/stick-word-group/.env logs -f --tail=200 $servico'"
