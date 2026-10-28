#!/usr/bin/env bash
# Só é necessário com LLM_PROVIDER=anthropic. Quem roda é VOCÊ, em outro terminal: a chave é
# digitada sem eco e vai por pipe direto para o Secret Manager.
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=infra/config.sh
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

SEGREDO="ANTHROPIC_API_KEY"

if ! existe gcloud secrets describe "$SEGREDO" --project "$PROJECT_ID"; then
  echo "O segredo $SEGREDO não existe; crie-o antes com llm_provider = 'anthropic' no infra/terraform" >&2
  exit 1
fi

if [[ -n "$(gcloud secrets versions list "$SEGREDO" --project "$PROJECT_ID" \
  --filter='state=ENABLED' --limit=1 --format='value(name)' 2>/dev/null)" ]]; then
  read -r -p "$SEGREDO já tem uma versão. Pular? [S/n] " resposta
  if [[ "$resposta" != "n" && "$resposta" != "N" ]]; then
    echo "Nada alterado."
    exit 0
  fi
fi

read -r -s -p "Cole a $SEGREDO (não aparece na tela): " valor
echo
[[ -n "$valor" ]] || { echo "Valor vazio; nada alterado." >&2; exit 1; }
printf '%s' "$valor" | gcloud secrets versions add "$SEGREDO" --data-file=- --project "$PROJECT_ID" >/dev/null
unset valor
echo "Nova versão de $SEGREDO criada."
