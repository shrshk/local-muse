.DEFAULT_GOAL := help
.PHONY: help env build up up-detached down restart logs ps psql migrate \
        test test-integration lint format typecheck check web-dev clean

COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env
# uv warns when an unrelated virtualenv is active; each project uses its own .venv.
UV := env -u VIRTUAL_ENV uv run
PY_PROJECTS := backend sandboxd

# -- lifecycle ---------------------------------------------------------------

env: ## Create .env from .env.example with random secrets (refuses to overwrite)
	@test ! -f .env || (echo ".env exists; delete it first to regenerate" && exit 1)
	@awk '{ if ($$0 ~ /=change-me$$/) { cmd="openssl rand -hex 32"; cmd | getline s; close(cmd); sub(/change-me$$/, s) } print }' .env.example > .env
	@echo "wrote .env"

build: ## Build all images
	$(COMPOSE) build

up: ## Run the stack in the foreground
	$(COMPOSE) up --build

up-detached: ## Run the stack in the background and wait for health
	$(COMPOSE) up -d --build --wait

down: ## Stop the stack
	$(COMPOSE) down

restart: ## Recreate every service so .env and code changes take effect
	$(COMPOSE) up -d --build --force-recreate --wait

logs: ## Tail logs
	$(COMPOSE) logs -f

ps: ## Service status
	$(COMPOSE) ps

psql: ## Postgres shell on the app database
	$(COMPOSE) exec postgres sh -c 'psql -U $$POSTGRES_USER muse'

migrate: ## Apply Alembic migrations
	$(COMPOSE) run --rm migrate

# -- quality -----------------------------------------------------------------

test: ## Unit and boundary tests (no stack needed)
	@for p in $(PY_PROJECTS); do (cd $$p && $(UV) pytest) || exit 1; done

test-integration: ## Integration tests against the running stack (make up-detached first)
	cd backend && $(UV) pytest -m integration tests/integration

lint: ## Ruff lint + format check
	@for p in $(PY_PROJECTS); do (cd $$p && $(UV) ruff check . && $(UV) ruff format --check .) || exit 1; done

format: ## Ruff format and autofix
	@for p in $(PY_PROJECTS); do (cd $$p && $(UV) ruff format . && $(UV) ruff check --fix .) || exit 1; done

typecheck: ## mypy strict + tsc
	@for p in $(PY_PROJECTS); do (cd $$p && $(UV) mypy) || exit 1; done
	cd apps/web && npm run typecheck

check: lint typecheck test ## Everything that runs without the stack

web-dev: ## Vite dev server on :5173, proxied to the running stack
	cd apps/web && npm run dev

# -- housekeeping ------------------------------------------------------------

clean: ## Stop the stack and delete its volumes (destroys the database)
	$(COMPOSE) down -v

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'
