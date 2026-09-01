.DEFAULT_GOAL := help

PYTHON ?= python3
PNPM ?= pnpm
UV ?= uv

.PHONY: help setup dev dev-backend dev-frontend format lint typecheck test security check data validate-data train predict index retrieve evaluate-retrieval evaluate-tot evaluate-guardrails assess scan e2e screenshots phase0-verify docker-up docker-down

help:
	@awk 'BEGIN {FS = ":.*## "; print "Meridian development commands:"} /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create the Python environment and install backend/frontend dependencies.
	$(UV) sync --locked --extra dev
	$(PNPM) install --frozen-lockfile

dev: ## Run the API and UI together; stop with Ctrl-C.
	./scripts/dev.sh

dev-backend: ## Run only the FastAPI service.
	.venv/bin/uvicorn meridian.api.main:app --app-dir backend/src --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Run only the Vite UI.
	$(PNPM) --dir frontend dev

format: ## Format Python and frontend source.
	.venv/bin/ruff format backend
	$(PNPM) --dir frontend format

lint: ## Run Python and frontend linters.
	.venv/bin/ruff check backend
	$(PNPM) --dir frontend lint

typecheck: ## Run strict Python and TypeScript type checks.
	.venv/bin/mypy
	$(PNPM) --dir frontend typecheck

test: ## Run backend and frontend tests.
	.venv/bin/pytest
	$(PNPM) --dir frontend test

security: ## Scan source for common secrets and machine-specific paths.
	$(PYTHON) scripts/check_repository.py

data: ## Build sanitized runtime tables, the dataset manifest, and the account split.
	./scripts/python_in_docker.sh python scripts/build_data.py

validate-data: ## Run the complete data-safety gate, including generator reproducibility.
	MERIDIAN_REQUIRE_DATASET=1 ./scripts/python_in_docker.sh pytest -q

train: ## Train, calibrate, and persist the forecaster (Docker).
	./scripts/python_in_docker.sh python scripts/train_model.py

predict: ## Forecast one account, e.g. make predict ACCOUNT=ACC-1042 (Docker).
	./scripts/python_in_docker.sh python scripts/predict_account.py $(ACCOUNT)

index: ## Build the FAISS retrieval index from sanitized documents (Docker).
	./scripts/python_in_docker.sh python scripts/build_index.py

retrieve: ## Retrieve evidence, e.g. make retrieve ACCOUNT=ACC-1089 QUERY="renewal risk".
	./scripts/python_in_docker.sh python scripts/retrieve.py "$(ACCOUNT)" "$(QUERY)"

evaluate-retrieval: ## Run the retrieval benchmark and chunking ablation (Docker).
	./scripts/python_in_docker.sh python scripts/evaluate_retrieval.py

evaluate-tot: ## Compare linear adjudication with conflict-gated ToT (Docker).
	./scripts/python_in_docker.sh python scripts/evaluate_tot.py $(if $(ACCOUNTS),--accounts $(ACCOUNTS),) $(if $(LIMIT),--limit $(LIMIT),)

evaluate-guardrails: ## Run the 36 packaged guardrail cases and write the safety report (Docker).
	./scripts/python_in_docker.sh python scripts/evaluate_guardrails.py $(if $(LIMIT),--limit $(LIMIT),) $(if $(REGRESSIONS),--file-regressions,)

scan: ## Run one bounded portfolio scan, e.g. make scan LIMIT=10 [CONCURRENCY=4] (Docker).
	./scripts/python_in_docker.sh python scripts/scan_portfolio.py $(if $(LIMIT),--limit $(LIMIT),) $(if $(CONCURRENCY),--concurrency $(CONCURRENCY),) $(if $(HORIZON),--horizon-days $(HORIZON),)

e2e: ## Run the Playwright journeys against the real stack (Docker).
	./scripts/run_e2e.sh

screenshots: ## Capture the README screenshots from the running UI (Docker).
	PLAYWRIGHT_SCREENSHOTS=1 ./scripts/run_e2e.sh

assess: ## Assess one account end to end, e.g. make assess ACCOUNT=ACC-1042 [OFFLINE=1].
	./scripts/python_in_docker.sh python scripts/assess_account.py $(ACCOUNT) $(if $(QUESTION),"$(QUESTION)",) $(if $(OFFLINE),--offline,)

check: lint typecheck test security ## Run every local quality gate.

phase0-verify: ## Generate locks and run the complete Phase 0 gate through Docker.
	./scripts/complete_phase0.sh

docker-up: ## Build and run the stack with Docker Compose.
	docker compose up --build

docker-down: ## Stop the Docker Compose stack.
	docker compose down
