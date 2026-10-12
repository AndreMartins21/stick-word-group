#!/usr/bin/env bash
# Alerta por e-mail quando a sessão do WhatsApp cai (M56, ADR-0054). Idempotente, mesmo padrão de
# infra/setup.sh. O bot registra `waha_status` (WARNING) a cada mudança da sessão; um número banido ou
# deslogado aparece como FAILED, STOPPED ou SCAN_QR_CODE. Sem o alerta, o bot ficaria mudo até alguém
# reparar. Roteiro de resposta: docs/runbooks/banimento-do-numero.md.
#
#   ALERTA_EMAIL=voce@exemplo.com GCP_PROJECT_ID=anki-whatsapp DRY_RUN=1 bash infra/setup_alerta_sessao.sh
#   ALERTA_EMAIL=voce@exemplo.com GCP_PROJECT_ID=anki-whatsapp bash infra/setup_alerta_sessao.sh
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

: "${ALERTA_EMAIL:?defina ALERTA_EMAIL (o e-mail que recebe o alerta)}"
CANAL="vocabot-alerta-email"
POLITICA="vocabot-sessao-whatsapp-caiu"
FILTRO='resource.type="gce_instance" AND jsonPayload.evento="waha_status" AND jsonPayload.motivo=("FAILED" OR "STOPPED" OR "SCAN_QR_CODE")'

echo "Projeto: $PROJECT_ID | conta: $(gcloud config get-value account 2>/dev/null)"
echo "Vai criar o canal de e-mail '$CANAL' ($ALERTA_EMAIL) e o alerta '$POLITICA'."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  read -r -p "Continuar? [s/N] " resposta
  [[ "$resposta" == "s" || "$resposta" == "S" ]] || { echo "Cancelado."; exit 1; }
fi

echo "==> 1. API (monitoring)"
run gcloud services enable monitoring.googleapis.com --project "$PROJECT_ID"

echo "==> 2. Canal de notificação por e-mail"
CANAL_ID="$(gcloud beta monitoring channels list --project "$PROJECT_ID" \
  --filter="displayName=$CANAL" --format='value(name)' 2>/dev/null || true)"
if [[ -n "$CANAL_ID" ]]; then
  echo "    já existe; nada a fazer."
else
  run gcloud beta monitoring channels create --project "$PROJECT_ID" \
    --display-name "$CANAL" --type email --channel-labels "email_address=$ALERTA_EMAIL"
  CANAL_ID="$(gcloud beta monitoring channels list --project "$PROJECT_ID" \
    --filter="displayName=$CANAL" --format='value(name)' 2>/dev/null || true)"
fi
CANAL_ID="${CANAL_ID:-projects/$PROJECT_ID/notificationChannels/DRY_RUN}"

echo "==> 3. Alerta '$POLITICA'"
EXISTENTE="$(gcloud alpha monitoring policies list --project "$PROJECT_ID" \
  --filter="displayName=$POLITICA" --format='value(name)' 2>/dev/null || true)"
if [[ -n "$EXISTENTE" ]]; then
  echo "    já existe; nada a fazer."
else
  ARQUIVO="$(mktemp)"
  trap 'rm -f "$ARQUIVO"' EXIT
  cat >"$ARQUIVO" <<JSON
{
  "displayName": "$POLITICA",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Sessão do WhatsApp fora do ar (FAILED, STOPPED ou SCAN_QR_CODE)",
      "conditionMatchedLog": {
        "filter": $(printf '%s' "$FILTRO" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
      }
    }
  ],
  "alertStrategy": {
    "notificationRateLimit": { "period": "3600s" },
    "autoClose": "1800s"
  },
  "notificationChannels": ["$CANAL_ID"],
  "documentation": {
    "mimeType": "text/markdown",
    "content": "A sessão do WhatsApp do Vocabot saiu de WORKING. Siga docs/runbooks/banimento-do-numero.md (sessão caída x número banido)."
  }
}
JSON
  python3 -m json.tool "$ARQUIVO" >/dev/null # falha cedo se o JSON ficou inválido
  [[ "${DRY_RUN:-0}" != "1" ]] || cat "$ARQUIVO"
  run gcloud alpha monitoring policies create --project "$PROJECT_ID" --policy-from-file "$ARQUIVO"
fi

echo
echo "Pronto. Conferir (só leitura):"
echo "  gcloud alpha monitoring policies list --project $PROJECT_ID --format='value(displayName,enabled)'"
