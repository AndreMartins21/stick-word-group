#!/usr/bin/env bash
# Provisiona o projeto do Vocabot no GCP (seção 10.2 da spec). Idempotente: pode rodar de novo.
#
#   DRY_RUN=1 bash infra/setup.sh   # só mostra o que criaria/alteraria (as leituras rodam)
#   bash infra/setup.sh             # pergunta antes de criar
#
# Custo: e2-micro + disco standard de 30 GB em us-central1 = nível gratuito. O IP externo efêmero
# NÃO é gratuito (alguns dólares por mês) e o Vertex AI é pago por uso. Firestore, Storage e
# Secret Manager ficam nas cotas gratuitas. Este script não cria Cloud NAT, balanceador nem IP
# estático.
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=infra/config.sh
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

echo "Projeto: $PROJECT_ID | conta: $(gcloud config get-value account 2>/dev/null)"
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  read -r -p "Criar/atualizar recursos neste projeto? [s/N] " resposta
  [[ "$resposta" == "s" || "$resposta" == "S" ]] || { echo "Cancelado."; exit 1; }
fi

echo "==> 1. APIs"
run gcloud services enable \
  compute.googleapis.com firestore.googleapis.com secretmanager.googleapis.com \
  storage.googleapis.com iap.googleapis.com iamcredentials.googleapis.com \
  logging.googleapis.com aiplatform.googleapis.com texttospeech.googleapis.com \
  --project "$PROJECT_ID"

echo "==> 2. Firestore (modo nativo, $REGION) e TTL de processed.expira_em"
if ! existe gcloud firestore databases describe --database='(default)' --project "$PROJECT_ID"; then
  run gcloud firestore databases create --database='(default)' --location="$REGION" \
    --type=firestore-native --project "$PROJECT_ID"
fi
if ! gcloud firestore fields describe expira_em --collection-group=processed \
  --database='(default)' --project "$PROJECT_ID" 2>/dev/null | grep -q 'ttlConfig'; then
  run gcloud firestore fields ttls update expira_em --collection-group=processed \
    --enable-ttl --async --database='(default)' --project "$PROJECT_ID"
fi

echo "==> 3. Conta de serviço $SA_NAME (uma por carga de trabalho, nunca a default da Compute)"
if ! existe gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT_ID"; then
  run gcloud iam service-accounts create "$SA_NAME" \
    --display-name="Vocabot (VM)" --project "$PROJECT_ID"
fi
# datastore.user: ler/gravar o Firestore. logWriter: logs. aiplatform.user: chamar o Gemini.
for papel in roles/datastore.user roles/logging.logWriter roles/aiplatform.user; do
  run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" --role="$papel" --condition=None --quiet --format=none
done
echo "==> 4. Bucket gs://$AUDIO_BUCKET (privado, permanente: cache dos áudios de pronúncia)"
# Sem lifecycle: o áudio é regenerável, mas gerar de novo custa cota do TTS (ADR-0024).
if ! existe gcloud storage buckets describe "gs://$AUDIO_BUCKET" --project "$PROJECT_ID"; then
  run gcloud storage buckets create "gs://$AUDIO_BUCKET" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention --project "$PROJECT_ID"
fi
run gcloud storage buckets add-iam-policy-binding "gs://$AUDIO_BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectAdmin \
  --project "$PROJECT_ID" --format=none

echo "==> 5. Segredos (valores gerados aqui e enviados por pipe: nunca aparecem na tela)"
tem_versao() {
  [[ -n "$(gcloud secrets versions list "$1" --project "$PROJECT_ID" \
    --filter='state=ENABLED' --limit=1 --format='value(name)' 2>/dev/null)" ]]
}
criar_segredo() {
  if ! existe gcloud secrets describe "$1" --project "$PROJECT_ID"; then
    run gcloud secrets create "$1" --replication-policy=automatic --project "$PROJECT_ID"
  fi
  # secretAccessor só neste segredo, não no projeto.
  run gcloud secrets add-iam-policy-binding "$1" \
    --member="serviceAccount:$SA_EMAIL" --role=roles/secretmanager.secretAccessor \
    --project "$PROJECT_ID" --format=none
}
for nome in "${SEGREDOS_GERADOS[@]}"; do
  criar_segredo "$nome"
  if tem_versao "$nome"; then
    echo "  $nome: já tem versão — mantida (rodar de novo não rotaciona)"
  elif [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "[dry-run] openssl rand -hex 24 | gcloud secrets versions add $nome --data-file=-"
  else
    openssl rand -hex 24 | gcloud secrets versions add "$nome" --data-file=- \
      --project "$PROJECT_ID" --format=none
    echo "  $nome: versão criada"
  fi
done
if [[ "$LLM_PROVIDER" == "anthropic" ]]; then
  criar_segredo ANTHROPIC_API_KEY
  echo "  ANTHROPIC_API_KEY: sem versão — quem coloca a chave é você, com infra/secrets.sh"
fi

echo "==> 6. Firewall: SSH só via IAP (35.235.240.0/20), só para a tag vocabot"
# A rede 'default' é criada sozinha quando a API do Compute é ativada, mas pode levar um minuto.
for _ in $(seq 1 12); do
  existe gcloud compute networks describe default --project "$PROJECT_ID" && break
  [[ "${DRY_RUN:-0}" == "1" ]] && { echo "  (dry-run) rede 'default' ainda não existe: seria criada com a API"; break; }
  sleep 10
done
if [[ "${DRY_RUN:-0}" != "1" ]] && ! existe gcloud compute networks describe default --project "$PROJECT_ID"; then
  echo "A rede 'default' não existe neste projeto; crie-a ou ajuste este script." >&2
  exit 1
fi
if ! existe gcloud compute firewall-rules describe allow-iap-ssh --project "$PROJECT_ID"; then
  run gcloud compute firewall-rules create allow-iap-ssh --network=default \
    --direction=INGRESS --action=allow --rules=tcp:22 \
    --source-ranges=35.235.240.0/20 --target-tags=vocabot --project "$PROJECT_ID"
fi

echo "==> 7. VM $VM_NAME (e2-micro, Debian 12, disco standard de 30 GB, IP externo efêmero)"
if ! existe gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID"; then
  run gcloud compute instances create "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
    --machine-type=e2-micro --image-family=debian-12 --image-project=debian-cloud \
    --boot-disk-size=30GB --boot-disk-type=pd-standard \
    --service-account="$SA_EMAIL" --scopes=cloud-platform --tags=vocabot \
    --network-tier=STANDARD \
    --metadata=enable-oslogin=TRUE \
    --metadata-from-file=startup-script="$INFRA_DIR/vm/startup.sh"
else
  echo "  a VM já existe; só sincronizo o startup-script"
  run gcloud compute instances add-metadata "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
    --metadata-from-file=startup-script="$INFRA_DIR/vm/startup.sh"
fi

echo
echo "Pronto. Para conferir o estado (só leitura):"
echo "  gcloud compute instances list --project $PROJECT_ID"
echo "  gcloud secrets list --project $PROJECT_ID"
echo "  gcloud storage buckets describe gs://$AUDIO_BUCKET --project $PROJECT_ID"
echo "Próximo passo: bash infra/deploy.sh   (e depois bash infra/pair.sh)"
echo "Antes do primeiro deploy, crie um alerta de orçamento em Billing → Budgets."
