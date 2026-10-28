#!/usr/bin/env bash
# Roda NA VM (chamado pelo infra/deploy.sh): extrai o código, renderiza o .env a partir do
# Secret Manager e sobe o compose. Uso: sudo bash render_e_subir.sh PROJECT_ID LLM_PROVIDER
# Os valores dos segredos vão direto do gcloud para o arquivo: nunca passam pela tela.
set -Eeuo pipefail
umask 077

PROJECT_ID="${1:?PROJECT_ID}"
LLM_PROVIDER="${2:?LLM_PROVIDER}"
RAIZ=/opt/stick-word-group

mkdir -p "$RAIZ/app"
tar xzf /tmp/stick-word-group.tgz -C "$RAIZ/app"

segredos=(WAHA_API_KEY WAHA_DASHBOARD_PASSWORD WAHA_HOOK_HMAC_KEY)
if [[ "$LLM_PROVIDER" == "anthropic" ]]; then
  segredos+=(ANTHROPIC_API_KEY)
fi

{
  cat /tmp/stick-word-group.env.base
  for nome in "${segredos[@]}"; do
    printf '%s=%s\n' "$nome" "$(gcloud secrets versions access latest --secret="$nome" --project="$PROJECT_ID")"
  done
} > "$RAIZ/.env.novo"
chmod 600 "$RAIZ/.env.novo"
mv "$RAIZ/.env.novo" "$RAIZ/.env"
rm -f /tmp/stick-word-group.tgz /tmp/stick-word-group.env.base

cd "$RAIZ/app"
docker compose --env-file "$RAIZ/.env" up -d --build
docker compose --env-file "$RAIZ/.env" ps
docker compose --env-file "$RAIZ/.env" logs --tail=20
