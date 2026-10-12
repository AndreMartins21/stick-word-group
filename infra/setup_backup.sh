#!/usr/bin/env bash
# Backups do Vocabot (M53, ADR-0051). Idempotente, mesmo padrão de infra/setup.sh:
#   1. snapshot diário do disco da VM (guarda a sessão do WAHA: sem ele, perder o disco = re-parear
#      o QR e ficar fora do ar) com retenção de 7 dias;
#   2. Point-in-Time Recovery do Firestore (restaura o caderno de qualquer instante dos últimos 7 dias).
#
#   DRY_RUN=1 bash infra/setup_backup.sh   # só mostra o que faria
#   bash infra/setup_backup.sh             # pergunta antes de alterar
#
# Passe o projeto explicitamente: GCP_PROJECT_ID=anki-whatsapp bash infra/setup_backup.sh
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

POLITICA="vocabot-snapshot-diario"
RETENCAO_DIAS="${RETENCAO_DIAS:-7}"
HORA_UTC="${HORA_UTC:-06:00}" # 03:00 em Brasília, longe do horário dos lembretes
BANCO="${FIRESTORE_DATABASE:-(default)}"

if ! [[ "$RETENCAO_DIAS" =~ ^[0-9]+$ ]]; then
  echo "RETENCAO_DIAS precisa ser um inteiro." >&2
  exit 1
fi

echo "Projeto: $PROJECT_ID | conta: $(gcloud config get-value account 2>/dev/null)"
echo "Vai: snapshot diário (${HORA_UTC} UTC, ${RETENCAO_DIAS} dias) do disco de $VM_NAME e PITR no Firestore."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  read -r -p "Continuar? [s/N] " resposta
  [[ "$resposta" == "s" || "$resposta" == "S" ]] || { echo "Cancelado."; exit 1; }
fi

echo "==> 1. Política de snapshot '$POLITICA' (leitura antes de criar)"
if gcloud compute resource-policies describe "$POLITICA" --region "$REGION" \
  --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "    já existe; nada a fazer."
else
  run gcloud compute resource-policies create snapshot-schedule "$POLITICA" \
    --project "$PROJECT_ID" --region "$REGION" \
    --daily-schedule --start-time "$HORA_UTC" \
    --max-retention-days "$RETENCAO_DIAS" \
    --on-source-disk-delete keep-auto-snapshots \
    --description "Snapshot diario do disco do Vocabot (M53)"
fi

echo "==> 2. Anexar a política ao disco de $VM_NAME"
ANEXADAS="$(gcloud compute disks describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
  --format='value(resourcePolicies)' 2>/dev/null || true)"
if [[ "$ANEXADAS" == *"$POLITICA"* ]]; then
  echo "    já anexada; nada a fazer."
else
  run gcloud compute disks add-resource-policies "$VM_NAME" \
    --resource-policies "$POLITICA" --zone "$ZONE" --project "$PROJECT_ID"
fi

echo "==> 3. Point-in-Time Recovery do Firestore ($BANCO)"
PITR="$(gcloud firestore databases describe --database "$BANCO" --project "$PROJECT_ID" \
  --format='value(pointInTimeRecoveryEnablement)' 2>/dev/null || true)"
if [[ "$PITR" == "POINT_IN_TIME_RECOVERY_ENABLED" ]]; then
  echo "    já habilitado; nada a fazer."
else
  run gcloud firestore databases update --database "$BANCO" --enable-pitr --project "$PROJECT_ID"
fi

echo
echo "Pronto. Conferir (só leitura):"
echo "  gcloud compute disks describe $VM_NAME --zone $ZONE --project $PROJECT_ID --format='value(resourcePolicies)'"
echo "  gcloud firestore databases describe --database='$BANCO' --project $PROJECT_ID --format='value(pointInTimeRecoveryEnablement)'"
echo "Restaurar o Firestore: gcloud firestore databases clone / import a partir de um instante (ver docs/adr/0051)."
