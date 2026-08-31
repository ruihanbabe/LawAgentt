# LawAgent standardized developer commands.
# Keep targets thin: reusable implementation belongs in bin/ or scripts/.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON ?= /root/miniconda3/envs/agent/bin/python
HOST ?= 127.0.0.1
PORT ?= 8000
QDRANT_URL ?= http://127.0.0.1:6333
DOCKER_HOST ?= unix:///tmp/lawagent-docker.sock
REPORT_DIR ?= data/reports

.PHONY: help setup status run health compile test test-e2e lint check verify \
	services-up services-status services-smoke services-down \
	qdrant-up qdrant-status qdrant-down model-smoke clean

help: ## Show available standardized commands
	@awk 'BEGIN {FS = ":.*## "; printf "LawAgent developer commands\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Check the local runtime and create .env from the safe template if absent
	@test -x "$(PYTHON)" || { echo "BLOCKED: Python not executable: $(PYTHON)"; exit 1; }
	@test -f .env || cp .env.example .env
	@chmod 600 .env
	@LAWAGENT_PYTHON="$(PYTHON)" QDRANT_URL="$(QDRANT_URL)" bin/project_status

status: ## Report five-question files and external dependency readiness
	@LAWAGENT_PYTHON="$(PYTHON)" QDRANT_URL="$(QDRANT_URL)" bin/project_status

run: ## Start the Web/API server (override HOST= and PORT=)
	@LAWAGENT_PYTHON="$(PYTHON)" LAWAGENT_HOST="$(HOST)" LAWAGENT_PORT="$(PORT)" bin/run_app

health: ## Check the running API health endpoint
	@curl --max-time 5 -fsS "http://$(HOST):$(PORT)/health"
	@echo

compile: ## Compile Python sources without executing external services
	@"$(PYTHON)" -m compileall -q api lawagent_runtime lawagent_evaluation scripts tests main.py

test: ## Run all unit, contract, SSE and in-process ASGI HTTP tests
	@"$(PYTHON)" -m unittest discover -s tests -v

test-e2e: ## Run the current in-process ASGI HTTP E2E tests only
	@"$(PYTHON)" -m unittest discover -s tests -p 'test_http_e2e.py' -v

lint: ## Run Ruff when installed; fail clearly while the linter dependency is missing
	@"$(PYTHON)" -c 'import ruff' >/dev/null 2>&1 || { echo "BLOCKED: Ruff is not installed; see requirement.txt and GOV-001."; exit 2; }
	@"$(PYTHON)" -m ruff check api lawagent_runtime lawagent_evaluation scripts tests main.py

check: status compile test ## Run the currently available local quality gate
	@echo "PASS: status + compile + tests"
	@echo "DEBT: lint, real services, browser/visual, performance and independent review are not included."

verify: ## Run the existing core verifier and print full-product verification debt
	@LAWAGENT_PYTHON="$(PYTHON)" bin/verify_all

services-up: ## Start Redis and PostgreSQL through Compose
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose up -d --wait redis postgres

services-status: ## Show Redis and PostgreSQL container health
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose ps redis postgres

services-smoke: ## Verify real Redis TTL/delete and PostgreSQL transaction/schema operations
	@PYTHONPATH=. "$(PYTHON)" scripts/smoke_persistence_services.py

services-down: ## Stop Redis and PostgreSQL without deleting persistent data
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose stop redis postgres

qdrant-up: ## Start the repository Qdrant service through Compose
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose up -d qdrant

qdrant-status: ## Show Compose state and query the Qdrant collections endpoint
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose ps qdrant
	@curl --max-time 5 -fsS "$(QDRANT_URL)/collections"
	@echo

qdrant-down: ## Stop the repository Qdrant service without deleting its volume
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose stop qdrant

model-smoke: ## Run the six-role GLM smoke; requires an explicitly configured key
	@mkdir -p "$(REPORT_DIR)"
	@PYTHONPATH=. "$(PYTHON)" scripts/smoke_glm_six_roles.py --output "$(REPORT_DIR)/glm-six-role-smoke.json"

clean: ## Remove only Python bytecode/cache files through compileall
	@"$(PYTHON)" -m compileall -q -f api lawagent_runtime lawagent_evaluation scripts tests main.py
	@find api lawagent_runtime lawagent_evaluation scripts tests -type f -name '*.pyc' -delete
	@find api lawagent_runtime lawagent_evaluation scripts tests -type d -name __pycache__ -empty -delete
