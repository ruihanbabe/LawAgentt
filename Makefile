# LawAgent standardized developer commands.
# Keep targets thin: reusable implementation belongs in bin/ or scripts/.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON ?= python3
PYTHON_MINIMUM ?= 3.11
HOST ?= 127.0.0.1
PORT ?= 8000
QDRANT_URL ?= http://127.0.0.1:6333
DOCKER_HOST ?= unix:///tmp/lawagent-docker.sock
REPORT_DIR ?= data/reports
PYCACHE_DIR ?= /tmp/lawagentt-pycache

.PHONY: help python-ready setup status run health compile test test-e2e lint check verify \
	services-up services-status services-smoke services-down \
	qdrant-up qdrant-status qdrant-down model-smoke test-coupling clean

help: ## Show available standardized commands
	@awk 'BEGIN {FS = ":.*## "; printf "LawAgent developer commands\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

python-ready:
	@command -v "$(PYTHON)" >/dev/null 2>&1 || { echo "BLOCKED: Python not executable: $(PYTHON)"; exit 1; }
	@"$(PYTHON)" -c 'import sys; required=tuple(map(int, "$(PYTHON_MINIMUM)".split("."))); raise SystemExit(0 if sys.version_info >= required else "BLOCKED: Python $(PYTHON_MINIMUM)+ required; found " + ".".join(map(str, sys.version_info[:3])))'

setup: python-ready ## Prepare local configuration and check the interpreter (does not install dependencies)
	@test -f .env || cp .env.example .env
	@chmod 600 .env
	@LAWAGENT_PYTHON="$(PYTHON)" QDRANT_URL="$(QDRANT_URL)" bin/project_status

status: ## Report project entry points and local interpreter readiness
	@LAWAGENT_PYTHON="$(PYTHON)" bin/project_status

run: ## Start the Web/API server (override HOST= and PORT=)
	@LAWAGENT_PYTHON="$(PYTHON)" LAWAGENT_HOST="$(HOST)" LAWAGENT_PORT="$(PORT)" bin/run_app

health: ## Check the running API health endpoint
	@curl --max-time 5 -fsS "http://$(HOST):$(PORT)/health"
	@echo

compile: python-ready ## Compile Python sources without executing external services
	@PYTHONPYCACHEPREFIX="$(PYCACHE_DIR)" "$(PYTHON)" -m compileall -q src scripts tests main.py

test: python-ready ## Run all unit, contract, SSE and in-process ASGI HTTP tests
	@PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$(PYTHON)" -m unittest discover -s tests -v

test-e2e: python-ready ## Run the current in-process ASGI HTTP E2E tests only
	@PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$(PYTHON)" -m unittest discover -s tests -p 'test_http_e2e.py' -v

lint: python-ready ## Run Ruff when installed; fail clearly while the linter dependency is missing
	@"$(PYTHON)" -c 'import ruff' >/dev/null 2>&1 || { echo "BLOCKED: Ruff is not installed; see requirement.txt."; exit 2; }
	@"$(PYTHON)" -m ruff check src scripts tests main.py

check: compile test ## Run the offline local quality gate
	@echo "PASS: compile + tests"
	@echo "DEBT: lint, real services, browser/visual, performance and independent review are not included."

verify: check ## Run the local quality gate and print full-product verification debt
	@echo "DEBT: real GLM, online Qdrant product flow, browser, visual, performance, independent review and fixed product evaluation remain unverified."

services-up: ## Start Redis and PostgreSQL through Compose
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose up -d --wait redis postgres

services-status: ## Show Redis and PostgreSQL container health
	@DOCKER_HOST="$(DOCKER_HOST)" docker compose ps redis postgres

services-smoke: ## Verify real Redis TTL/delete and PostgreSQL transaction/schema operations
	@PYTHONPATH=src "$(PYTHON)" scripts/smoke_persistence_services.py

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
	@PYTHONPATH=src "$(PYTHON)" scripts/smoke_glm_six_roles.py --output "$(REPORT_DIR)/glm-six-role-smoke.json"

test-coupling: ## Run real-service/model coupling checks after explicit authorization
	@test "$${LAWAGENT_ALLOW_REAL_MODEL_TESTS:-false}" = "true" || { echo "BLOCKED: set LAWAGENT_ALLOW_REAL_MODEL_TESTS=true only after explicit user authorization."; exit 2; }
	@$(MAKE) services-smoke PYTHON="$(PYTHON)"
	@$(MAKE) model-smoke PYTHON="$(PYTHON)"

clean: ## Remove only Python bytecode/cache files
	@find src scripts tests -type f -name '*.pyc' -delete
	@find src scripts tests -type d -name __pycache__ -empty -delete
	@if test -d "$(PYCACHE_DIR)"; then find "$(PYCACHE_DIR)" -type f -delete; find "$(PYCACHE_DIR)" -depth -type d -empty -delete; fi
