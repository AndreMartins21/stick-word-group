#!/usr/bin/env bash
# Confere, pela VM, que o bot responde no /health e que a sessão do WAHA está WORKING. Quem faz a
# checagem (e espera o bot e o WAHA subirem depois de um deploy) é o infra/vm/smoke_remoto.sh.
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=infra/config.sh
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

# O script remoto roda inteiro como root (o /opt/stick-word-group é modo 700) e lê a API key do .env da VM
# sem nunca imprimi-la. O sucesso só vale se ele chegou ao fim e imprimiu o marcador SMOKE_OK (um
# exit 0 sozinho não prova nada).
saida="$(gcloud compute ssh "$VM_NAME" "${SSH_FLAGS[@]}" --command "sudo bash -s" \
  <"$INFRA_DIR/vm/smoke_remoto.sh" 2>&1)" || true
printf '%s\n' "$saida" | grep -v -e NumPy -e 'please see' -e '^WARNING:' -e '^$'
if grep -q '^SMOKE_OK$' <<<"$saida"; then
  echo "Smoke test ok."
else
  echo "Smoke test FALHOU (o bot, a sessão do WAHA ou ambos não estão prontos)." >&2
  exit 1
fi
