# Decisions

One entry per design choice. Newest first.

Format:
## YYYY-MM-DD · Title
- Decision:
- Why:
- Alternative rejected:

## 2026-10-23 · Demo auth: thin token, scope from the DB, fail closed
- Decision: `POST /auth/login {tenant, email, password}` with one demo password for seeded users (`DEMO_AUTH` can switch it off). The HS256 JWT holds only `tid` + `sub` + `exp` (secret must be ≥ 32 bytes). Every request re-reads role and location/brand scope from the DB inside the token's tenant session. Only `hq_owner` sees the whole org; scoped roles with no scope rows see nothing. Out-of-scope and other-tenant records both return 404; a customer on a staff route gets 403 (the route exists for everyone, the record question doesn't arise).
- Why: a role or scope in the token could be replayed after it was revoked; reading the user under RLS means a token pairing tenant A with a user of tenant B finds no user (401). Failing closed avoids "empty scope = everything".
- Alternative rejected: role/scope claims in the JWT (stale after changes); 403 for out-of-scope records (confirms they exist).

## 2026-10-23 · Git branches: feature → test → main
- Decision: GitHub `origin`; `main` = deployed/stable, `test` = integration, `feature/<story-id>-<name>` cut from `test`. A story merges into `test` only after `make lint`, `make test`, `make test-isolation` (and safety-reviewer where required) pass; `test` is promoted to `main` at sprint review. Merges use `--no-ff` so one `git revert -m 1 <merge>` undoes a whole story.
- Why: the human reviews remotely; every story is isolated and revertible, and `main` only ever holds verified work.
- Alternative rejected: committing straight to `main` (no safe rollback point, unreviewed work deployed).

## 2026-10-23 · Remedy rules are tenant settings, not code or fixed spec values
- Decision: late-delivery tiers, voucher auto-approve cap (default ₹150 = 15000 paise), refund channel (`tenant_gateway` | `aggregator_only`) and money limits are vertical-pack settings that a tenant overrides at org/brand/location. Settings have a kind: `limit` (integer ceiling; lower levels may only lower it) or `value` (replaced). Refunds always need human approval: that stays a hard rule, not a setting.
- Why: the human asked that business answers (tiers, caps, aggregator handling) be configurable from the platform, not decided in code. Overrides live in `tenant_settings`, so a future admin UI/API can change them without a deploy.
- Alternative rejected: hard-coded tiers and caps (BA research found no market norm to justify one fixed value).

## 2026-10-23 · Deterministic tenant IDs for the loader
- Decision: tenant and child IDs are `uuid5` of slugs; the loader upserts by id and only rewrites a row when a value differs (`IS DISTINCT FROM`). Packs are stored in `vertical_packs` (platform-wide, no RLS). The seed CLI sets the tenant from the folder it loads; this is an admin path, not a request path.
- Why: with RLS the loader can't look an org up by slug before the tenant is set; deterministic ids make reruns a no-op (`updated_at` unchanged), which the idempotency test checks.
- Alternative rejected: lookup-then-insert as owner (bypasses RLS on the write path).

## 2026-10-23 · Test database instead of a Neon test branch
- Decision: tests use a second database `resolvedesk_test` on the same Neon branch; the app role is cluster-wide so it works in both. Bootstrap (role, vector, `lg` schema, grants) runs in both databases.
- Why: creating a branch needs the Neon CLI/console login; a database needs only the owner URL. Same isolation for tests.
- Alternative rejected: Neon `test` branch (extra setup step; can revisit for CI resets).

## 2026-10-23 · Tenancy schema: forced RLS + composite foreign keys
- Decision: RLS is ENABLED and FORCED on every tenant table with policy `tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid` (USING + WITH CHECK). Child tables reference parents by `(tenant_id, id)`. `organizations.tenant_id = id` (check constraint). Brand/location many-to-many via `location_brands`.
- Why: FORCE makes the owner role obey RLS too; unset tenant → NULL → no rows. Composite FKs stop a row in tenant A pointing at a row in tenant B even though FK checks bypass RLS.
- Alternative rejected: single-column FKs (cross-tenant links possible), RLS without FORCE (owner bypasses).

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
