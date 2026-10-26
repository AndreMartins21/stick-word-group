#!/usr/bin/env bash
# Provisiona o deploy contínuo via GitHub Actions (seção 10.9 da spec, ADR-0013). Idempotente.
#
#   DRY_RUN=1 bash infra/setup_cicd.sh   # só mostra o que criaria/alteraria (as leituras rodam)
#   bash infra/setup_cicd.sh             # pergunta antes de criar
#
# Não mexe em segredo nenhum: a vocabot-deploy só recebe acesso a SSH/IAP na VM. Quem lê o Secret
# Manager continua sendo a própria VM, com a identidade vocabot-vm (ver infra/setup.sh).
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=infra/config.sh
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

echo "Projeto: $PROJECT_ID | repo: $GITHUB_REPO | conta: $(gcloud config get-value account 2>/dev/null)"
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  read -r -p "Criar/atualizar recursos de CI/CD neste projeto? [s/N] " resposta
  [[ "$resposta" == "s" || "$resposta" == "S" ]] || { echo "Cancelado."; exit 1; }
fi

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

echo "==> 1. API do IAM Credentials (troca de token OIDC por credencial do Google)"
run gcloud services enable iamcredentials.googleapis.com --project "$PROJECT_ID"

echo "==> 2. Workload Identity Pool $WIF_POOL"
if ! existe gcloud iam workload-identity-pools describe "$WIF_POOL" \
  --project "$PROJECT_ID" --location=global; then
  run gcloud iam workload-identity-pools create "$WIF_POOL" \
    --project "$PROJECT_ID" --location=global --display-name="GitHub Actions"
fi

echo "==> 3. Provider OIDC $WIF_PROVIDER (só aceita token do repo/branch main deste projeto)"
# attribute-condition trava o token em assertion.repository + assertion.ref: nenhum fork, nenhuma
# outra branch e nenhum outro repositório consegue trocar o token por credencial do Google, mesmo
# copiando o workflow.
if ! existe gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" \
  --project "$PROJECT_ID" --location=global --workload-identity-pool="$WIF_POOL"; then
  run gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
    --project "$PROJECT_ID" --location=global --workload-identity-pool="$WIF_POOL" \
    --display-name="GitHub" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}' && assertion.ref == 'refs/heads/main'"
fi

echo "==> 4. Conta de serviço $DEPLOY_SA_NAME (só para o job de deploy, não é a identidade da VM)"
if ! existe gcloud iam service-accounts describe "$DEPLOY_SA_EMAIL" --project "$PROJECT_ID"; then
  run gcloud iam service-accounts create "$DEPLOY_SA_NAME" \
    --display-name="Deploy do vocabot via GitHub Actions" --project "$PROJECT_ID"
fi

echo "==> 5. Permitir que o provider represente a vocabot-deploy (workloadIdentityUser)"
run gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA_EMAIL" \
  --project "$PROJECT_ID" --role=roles/iam.workloadIdentityUser --format=none \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository/${GITHUB_REPO}"

echo "==> 6a. iap.tunnelResourceAccessor e compute.viewer, no projeto (não por instância)"
echo "     iap.tunnelResourceAccessor: o recurso 'túnel IAP' não aceita binding por instância via"
echo "     gcloud. compute.viewer: 'gcloud compute scp/ssh' chama compute.projects.get antes de"
echo "     conectar, e essa permissão só existe no escopo do projeto (confirmado: um binding só na"
echo "     instância falha com 'Required compute.projects.get permission'). Só há uma VM neste"
echo "     projeto e a spec proíbe criar outra (10.8), então na prática já fica restrito a ela —"
echo "     ver ADR-0013."
for papel in roles/iap.tunnelResourceAccessor roles/compute.viewer; do
  run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOY_SA_EMAIL}" --role="$papel" \
    --condition=None --quiet --format=none
done

echo "==> 6b. osAdminLogin (sudo via OS Login), só na instância $VM_NAME"
run gcloud compute instances add-iam-policy-binding "$VM_NAME" \
  --zone "$ZONE" --project "$PROJECT_ID" --format=none \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" --role=roles/compute.osAdminLogin

echo "==> 6c. serviceAccountUser só sobre a $SA_NAME (a VM roda como ela; sem isso o SSH falha com actAs)"
run gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --project "$PROJECT_ID" --format=none \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" --role=roles/iam.serviceAccountUser

WIF_PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER}"

echo
echo "Pronto. Para conferir o estado (só leitura):"
echo "  gcloud iam workload-identity-pools providers describe $WIF_PROVIDER \\"
echo "    --project $PROJECT_ID --location=global --workload-identity-pool=$WIF_POOL"
echo "  gcloud compute instances get-iam-policy $VM_NAME --zone $ZONE --project $PROJECT_ID"
echo
echo "Configure no GitHub (Settings → Secrets and variables → Actions):"
echo "  Variables: GCP_PROJECT_ID=$PROJECT_ID"
echo "             GCP_WIF_PROVIDER=$WIF_PROVIDER_RESOURCE"
echo "             LLM_PROVIDER, GEMINI_MODEL, GEMINI_MODEL_EVAL, USER_LEVEL, TIMEZONE"
echo "             opcionais (M15-M17): MAX_GROUPS, GROUP_PREFIX, LIMITE_POR_SESSAO_GRUPO, TIMEOUT_MARCACAO_HORAS (públicos)"
echo "  Secrets:   ALLOWED_NUMBER, BOT_NUMBER (telefone real — nunca em Variables)"
echo "             opcionais (M14): ALLOWED_GROUPS, OWNER_NUMBER (telefones e ids reais)"
echo "Depois, ative a branch protection da main (PR + checks obrigatórios) nas configurações do repo."
