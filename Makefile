# One command vocabulary, shared with vex-agent-integration. Run `make` or
# `make help` to list targets. This is a thin wrapper over scripts/ and the
# compose files, so behavior matches running those by hand.
#
# Docker targets honor COMPOSE, so on a host where docker needs sudo run e.g.
#   make dev COMPOSE='sudo docker compose'
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help install dev down logs ps test lint format format-check build deploy

help: ## List the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install the backend (editable, dev extras) and frontend deps
	pip install -e '.[dev]'
	npm --prefix frontend install

dev: ## Start the local dev stack (api reload + Vite on :3000); Ctrl-C to stop
	$(COMPOSE) up

down: ## Stop the local dev stack
	$(COMPOSE) down

logs: ## Follow the stack logs
	$(COMPOSE) logs -f

ps: ## Show stack status
	$(COMPOSE) ps

test: ## Run backend (pytest) and frontend (vitest) tests
	pytest -q
	npm --prefix frontend test

lint: ## Lint the backend with ruff
	ruff check app tests

format: ## Format the backend (ruff) and frontend (prettier)
	ruff format app tests
	npm --prefix frontend run format

format-check: ## Check formatting without writing changes
	ruff format --check app tests
	npm --prefix frontend run format:check

build: ## Build the frontend bundle
	npm --prefix frontend run build

deploy: ## Prod deploy: roll the stack (frontend is built inside the image)
	./scripts/deploy.sh
