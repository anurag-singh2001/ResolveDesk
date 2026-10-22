# Decisions

One entry per design choice. Newest first.

Format:
## YYYY-MM-DD · Title
- Decision:
- Why:
- Alternative rejected:

## 2026-10-23 · Sprints with scrum-master and business-analyst agents
- Decision: 5 sprints (0–4) tracked in docs/EPICS.md + docs/sprints/; a `scrum-master` agent runs meetups, ticks stories only after verifying done-when, and keeps an evidence-based agent/model scorecard; a `business-analyst` agent writes sourced research into docs/research/.
- Why: visible progress against deadlines and a record of which agent/model performed well; research keeps policies, data and scenarios realistic.
- Alternative rejected: following the day-by-day plan with no status tracking (progress claims unverified).

## 2026-10-23 · GNU make on Windows
- Decision: keep the Makefile; install make via `winget install ezwinports.make`. Recipes are single `uv run ...` / `echo` commands so they work under cmd or sh.
- Why: matches the spec and is what other developers expect from the README.
- Alternative rejected: a Python task runner (diverges from spec and CLAUDE.md commands).

## 2026-10-23 · Two DB roles, transaction-local tenant
- Decision: migrations run as the Neon owner on the direct endpoint; the app and tests connect as `resolvedesk_app` (created by SQL, NOBYPASSRLS, DML grants only). Tenant is set with `set_config('app.tenant_id', x, true)` inside each transaction.
- Why: table owners and neon_superuser members bypass RLS; Neon's pooled endpoint is PgBouncer transaction mode, so a session-level SET could leak to another client.
- Alternative rejected: one owner URL for everything (RLS silently not enforced).

## 2026-10-23 · Neon instead of Docker Compose
- Decision: hosted Neon Postgres 16 + pgvector, with a `main` branch for dev/demo and a `test` branch for pytest.
- Why: no Docker Desktop on the dev machine; Neon is free, supports pgvector and RLS, and branches give a cheap, resettable test DB.
- Alternative rejected: Docker Compose Postgres (not available); local Windows Postgres install (harder for others to reproduce).

## 2026-10-22 · LLM proposes, code executes
- Decision: Agents only get read tools; the executor is plain code acting on an approved, hash-bound proposal.
- Why: money and customer messages must be deterministic and auditable.
- Alternative rejected: giving the resolution agent a refund tool (unbounded risk, hard to test).

## 2026-10-22 · Row-level security for tenancy
- Decision: one database, `tenant_id` on every tenant-owned table, Postgres RLS with a session variable.
- Why: isolation enforced by the database even if application code has a bug.
- Alternative rejected: schema per tenant (heavier migrations, harder to demo onboarding).

## 2026-10-22 · Free LLM stack
- Decision: Gemini Flash main, Groq classifier + fallback, Ollama offline, local embeddings.
- Why: zero cost for a POC; provider switch shows production readiness.
- Alternative rejected: one paid provider.
