# Atalhos do projeto. Requer `uv` (https://docs.astral.sh/uv/).
.DEFAULT_GOAL := help
.PHONY: help setup fmt lint type test test-emulador evals cov check hooks run sim clean \
	tf-bootstrap tf-init tf-plan tf-apply

help: ## Mostra os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Cria o venv (Python 3.12), instala dependências e os hooks de pre-commit
	uv sync --group dev
	uv run pre-commit install
	@test -f .env || cp .env.example .env
	@echo "Pronto. Edite o .env com valores locais (falsos)."

fmt: ## Formata o código
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Verifica lint e formatação (sem alterar arquivos)
	uv run ruff check .
	uv run ruff format --check .

type: ## Checagem de tipos
	uv run mypy

test: ## Roda os testes
	uv run pytest

test-emulador: ## Roda o teste de contrato do Repository também contra o emulador do Firestore (Docker)
	docker run -d --rm --name stick-word-group-firestore-emu -p 127.0.0.1:8686:8686 \
		gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators \
		gcloud emulators firestore start --host-port=0.0.0.0:8686
	@until curl -s http://127.0.0.1:8686 >/dev/null; do sleep 1; done
	FIRESTORE_EMULATOR_HOST=127.0.0.1:8686 uv run pytest tests/test_repository.py; \
		status=$$?; docker stop stick-word-group-firestore-emu >/dev/null; exit $$status

evals: ## Mede a avaliação de frases contra a API real (custa centavos). Ex.: make evals ARGS="--provider anthropic"
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run $(ARGS)

cov: ## Roda os testes com relatório de cobertura
	uv run pytest --cov --cov-report=term-missing

check: lint type test ## Tudo que a CI roda

hooks: ## Roda todos os hooks de pre-commit no repositório inteiro
	uv run pre-commit run --all-files

run: ## Sobe a API local (recarrega ao salvar)
	uv run uvicorn app.main:app --reload --port 8000

sim: ## Simulador de terminal, sem WhatsApp. Com a IA de verdade: make sim ARGS=--real-llm
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m sim $(ARGS)

clean: ## Remove caches de ferramentas
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +

# --- Infra (Terraform, ADR-0063). O projeto vem do terraform.tfvars; o estado, do bucket
# <projeto>-tfstate (criado uma vez pelo tf-bootstrap, versionado para desfazer um estado ruim).
TF := terraform -chdir=infra/terraform
TF_PROJETO = $(shell sed -nE 's/^project_id *= *"([^"]+)".*/\1/p' infra/terraform/terraform.tfvars 2>/dev/null)

tf-bootstrap: ## Cria o bucket do estado do Terraform (<projeto>-tfstate), se faltar
	@test -n "$(TF_PROJETO)" || { echo "Defina project_id em infra/terraform/terraform.tfvars"; exit 1; }
	gcloud storage buckets describe gs://$(TF_PROJETO)-tfstate --project $(TF_PROJETO) >/dev/null 2>&1 || \
		gcloud storage buckets create gs://$(TF_PROJETO)-tfstate --project $(TF_PROJETO) \
		--location=us-central1 --uniform-bucket-level-access --public-access-prevention
	gcloud storage buckets update gs://$(TF_PROJETO)-tfstate --versioning --project $(TF_PROJETO)

tf-init: ## terraform init com o estado em gs://<projeto>-tfstate
	$(TF) init -input=false -reconfigure -backend-config=bucket=$(TF_PROJETO)-tfstate

tf-plan: ## Mostra o que o Terraform criaria/alteraria (só leitura)
	$(TF) plan -input=false

tf-apply: ## Aplica a infra (pergunta antes)
	$(TF) apply -input=false
