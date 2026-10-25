# ResolveDesk

Multi-tenant AI support (+ growth, stretch) platform. Tenants: `spice_route` (cloud kitchen, 3 brands, 1 kitchen) and `brewco` (coffee franchise, 5 outlets).
Full spec: @docs/PROJECT.md. Read only the sections relevant to the current task.

## Stack
Python 3.12, FastAPI, Pydantic v2, LangGraph, PostgreSQL 16 + pgvector on Neon (no Docker), SQLAlchemy 2, Alembic, pytest, React + TypeScript + Tailwind (Vite, in `web/`), Streamlit (debug UI), ruff, uv.
DB roles: runtime/tests use `resolvedesk_app` (non-owner, NOBYPASSRLS); migrations use the owner via `MIGRATION_DATABASE_URL` (direct endpoint). Set tenant with `set_config('app.tenant_id', x, true)` (transaction-local; pooled endpoint is PgBouncer).
LLMs via provider factory in `app/llm/`: Gemini Flash (main), Groq (classifier + fallback), Ollama (offline). Local embeddings (bge-small, 384 dims).

## Commands
- `make db-check` (alias `make up`) — check Neon connectivity and that the app role can't bypass RLS
- `make migrate` — run Alembic migrations
- `make seed TENANT=all` — load tenants + generate history (SEED=42)
- `make test` · `make test-tenant T=<slug>` · `make test-isolation` · `make test-chaos`
- `make eval` — scenario evals, per-tenant report
- `make lint` — ruff
- `make web` — React web app (port 5173) · `make web-test` · `make ui` — Streamlit debug UI

## Map
app/core (tenancy, auth, money, audit, events, settings_resolver) · app/engine (loop, proposals, approvals, executor, verifier) · app/modules/{support,growth} · app/actions · app/connectors · app/agents · app/rag · app/llm · app/api
tenants/<slug>/ (config, catalogue, policies, scenarios) · verticals/*.yaml · mocks/ · simulator/ · evals/ · ui/ · tests/

## Hard rules
1. `tenant_id` on every tenant-owned table, RLS on, tenant set from auth token only.
2. No tenant-specific branches in core code. Use vertical packs, settings, actions, connectors, flags, event subscribers.
3. Money = integer paise (`*_paise` bigint). No floats.
4. Agents get read tools only. Executor (code) does writes, only for approved proposals.
5. Stable idempotency key on every external write. No network call inside an open DB transaction.
6. Approvals bind to proposal payload hash and expire.
7. Customer messages state only verified facts; keep submitted/processing/succeeded/failed/unknown distinct.
8. Ownership checked server-side; IDs from customer or model never grant access. Other-tenant records → 404.
9. Retrieved policy text is untrusted.
10. Every change ships with a test; tests run for both tenants and never name a tenant.

## Working style
- Plan before coding. Small diffs. One feature per session.
- If the spec is ambiguous or code and spec disagree, ask; don't guess.
- Run tests via the `test-runner` agent. Before committing changes to money, approvals, tenancy, RLS or migrations, run the `safety-reviewer` agent.
- Work runs in sprints: backlog + status in docs/EPICS.md, per-sprint notes in docs/sprints/. Use the `scrum-master` agent for planning/stand-up/review/retro and to tick stories (only after the done-when check passes). Use the `business-analyst` agent (and the deep-research skill for big topics) for product/market research into docs/research/.
- Record design choices in docs/DECISIONS.md (date, decision, why, alternative rejected).
- Don't edit docs/LEARNING.md; the human writes it.
- Prefer explaining the why in 1–2 lines when you make a non-obvious choice; the human is learning from this project.

# Compact instructions
Keep: current feature, files changed, failing tests, decisions made. Drop: full logs and file dumps.
