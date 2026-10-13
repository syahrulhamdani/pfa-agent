# Shortcuts for the commands in the README. Nothing depends on Make: every target is
# just the plain command shown next to it. Use another env file with ENV=path.
ENV ?= .env
RUN := uv run --env-file $(ENV)

.DEFAULT_GOAL := help
.PHONY: help install env db migrate chat-id doctor seed api web test lint check reset-db

help: ## Show this list
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-9s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install the Python and web dependencies
	uv sync
	cd web && npm ci

env: ## Create .env from .env.example (never overwrites an existing one)
	@test -f .env && echo ".env already exists, leaving it alone" || (cp .env.example .env && echo "Created .env. Fill in the token, key and secret.")

db: ## Start Postgres in Docker and wait until it is ready
	docker compose up -d --wait db

migrate: ## Create or update the database tables
	$(RUN) alembic upgrade head

chat-id: ## Find your Telegram chat id (message your bot first)
	$(RUN) pfa chat-id

doctor: ## Check the settings, database, Telegram and Gemini
	$(RUN) pfa doctor

seed: ## Fill an empty database with fictional sample data
	$(RUN) pfa seed-demo

api: ## Run the API, the Telegram bot and the scheduler
	$(RUN) uvicorn pfa.main:app

web: ## Run the web app on http://localhost:5173
	cd web && npm run dev

test: ## Run the tests (needs `make db`)
	uv run --env-file .env.example pytest

lint: ## Check the Python and web code
	uv run ruff check .
	uv run black --check .
	cd web && npm run lint

check: test lint ## Tests, lint and a web build
	cd web && npm run build

reset-db: ## DELETE all data and start a fresh database (asks first)
	@printf "This deletes the pfa database volume and everything in it. Continue? [y/N] " && read answer && [ "$$answer" = "y" ] && docker compose down -v && docker compose up -d --wait db || echo "Nothing was changed."
