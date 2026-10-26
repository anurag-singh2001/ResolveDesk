# Recipes are single commands so they run under cmd (Windows) or sh.
TENANT ?= all
SEED ?= 42
T ?=

.PHONY: up down db-check migrate refresh seed sweep retention api flight test test-tenant test-isolation test-chaos eval lint ui llm-smoke web web-install web-build web-test

db-check:
	uv run python -m scripts.db_check

up: db-check

down:
	@echo Database is hosted on Neon; nothing to stop.

migrate:
	uv run alembic upgrade head
	$(MAKE) refresh

# Re-apply tenants/ packs, settings and policies (dev only; no-op otherwise; never touches history).
refresh:
	uv run python -m scripts.refresh

sweep:
	uv run python -m scripts.sweep

seed:
	uv run python -m scripts.seed $(TENANT) --seed $(SEED)

# DPDP retention (S5.1): dry run by default; `make retention APPLY=1` really redacts (irreversible).
retention:
	uv run python -m scripts.retention $(if $(APPLY),--apply,)

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
	uv run pytest -q -m chaos

eval:
	uv run python -m evals.run $(ARGS)

lint:
	uv run ruff check . && uv run ruff format --check .

ui:
	uv run streamlit run ui/app.py

llm-smoke:
	uv run python -m scripts.llm_smoke

# React web app (web/). Run web-install once; the API must be running (make api).
web-install:
	npm --prefix web ci

web:
	npm --prefix web run dev

web-build:
	npm --prefix web run build

web-test:
	npm --prefix web test
