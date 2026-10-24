# Recipes are single commands so they run under cmd (Windows) or sh.
TENANT ?= all
SEED ?= 42
T ?=

.PHONY: up down db-check migrate seed api flight test test-tenant test-isolation test-chaos eval lint ui

db-check:
	uv run python -m scripts.db_check

up: db-check

down:
	@echo Database is hosted on Neon; nothing to stop.

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m scripts.seed $(TENANT) --seed $(SEED)

api:
	uv run uvicorn app.main:app --reload --port 8000

flight:
	uv run python -m scripts.flight $(ARGS)

test:
	uv run pytest -q -m "not isolation and not chaos and not live"

test-tenant:
	uv run pytest -q -m "not chaos and not live" -k "$(T)"

test-isolation:
	uv run pytest -q -m isolation

test-chaos:
	@echo not implemented yet

eval:
	@echo not implemented yet

lint:
	uv run ruff check . && uv run ruff format --check .

ui:
	@echo not implemented yet
