#!/usr/bin/env bash
# Cria o Budget da GCP com alertas de gasto (M45, ADR-0043). Idempotente, mesmo padrão de
# infra/setup.sh. O Budget SÓ ALERTA (e-mail aos administradores da conta de faturamento); quem corta
# o gasto da IA é o orçamento diário do próprio bot (ADR-0044).
#
#   DRY_RUN=1 bash infra/setup_orcamento.sh   # só mostra o que criaria
#   bash infra/setup_orcamento.sh             # pergunta antes de criar
#
# ORCAMENTO_MENSAL (padrão 30) e BUDGET_MOEDA (padrão BRL, a moeda da conta) definem o Budget por mês. Alertas em 50%, 90% e
# 100% do valor gasto (o Budget cobre o projeto inteiro: VM, IP, Firestore, Vertex AI, TTS).
set -Eeuo pipefail
IFS=$'\n\t'

# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

# A API recusa um Budget em moeda diferente da da conta de faturamento (a desta conta é BRL):
# ORCAMENTO_MENSAL é o valor, BUDGET_MOEDA a moeda da conta.
ORCAMENTO_MENSAL="${ORCAMENTO_MENSAL:-${ORCAMENTO_MENSAL_USD:-30}}"
BUDGET_MOEDA="${BUDGET_MOEDA:-BRL}"
NOME_DO_BUDGET="anki-bot-mensal"

if ! [[ "$ORCAMENTO_MENSAL" =~ ^[0-9]+$ ]]; then
  echo "ORCAMENTO_MENSAL precisa ser um inteiro." >&2
  exit 1
fi

echo "Projeto: $PROJECT_ID | conta: $(gcloud config get-value account 2>/dev/null)"
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  read -r -p "Criar o Budget '$NOME_DO_BUDGET' de $BUDGET_MOEDA $ORCAMENTO_MENSAL/mês? [s/N] " resposta
  [[ "$resposta" == "s" || "$resposta" == "S" ]] || { echo "Cancelado."; exit 1; }
fi

echo "==> 1. API (billingbudgets)"
run gcloud services enable billingbudgets.googleapis.com --project "$PROJECT_ID"

echo "==> 2. Conta de faturamento do projeto (leitura)"
CONTA="$(gcloud billing projects describe "$PROJECT_ID" \
  --format='value(billingAccountName)' 2>/dev/null || true)"
CONTA="${CONTA#billingAccounts/}"
if [[ -z "$CONTA" ]]; then
  echo "O projeto $PROJECT_ID não tem conta de faturamento vinculada (ou falta permissão)." >&2
  exit 1
fi

# A API de Budgets só aceita o NÚMERO do projeto no filtro (`projects/123...`), não o id.
NUMERO="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null || true)"
if [[ -z "$NUMERO" ]]; then
  echo "Não consegui ler o número do projeto $PROJECT_ID." >&2
  exit 1
fi

echo "==> 3. Budget $NOME_DO_BUDGET ($BUDGET_MOEDA $ORCAMENTO_MENSAL/mês, alertas 50/90/100%)"
EXISTENTE="$(gcloud billing budgets list --billing-account="$CONTA" \
  --filter="displayName=$NOME_DO_BUDGET" --format='value(name)' 2>/dev/null || true)"
if [[ -n "$EXISTENTE" ]]; then
  echo "    já existe; nada a fazer."
else
  run gcloud billing budgets create --billing-account="$CONTA" \
    --display-name="$NOME_DO_BUDGET" \
    --budget-amount="${ORCAMENTO_MENSAL}${BUDGET_MOEDA}" \
    --calendar-period=month \
    --filter-projects="projects/$NUMERO" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --threshold-rule=percent=1.0
fi

echo
echo "Pronto. Conferir (só leitura): gcloud billing budgets list --billing-account=$CONTA"
