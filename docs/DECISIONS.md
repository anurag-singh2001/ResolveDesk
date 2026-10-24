# Decisions

One entry per design choice. Newest first.

Format:
## YYYY-MM-DD · Title
- Decision:
- Why:
- Alternative rejected:

## 2026-10-24 · Refund execution: lock, reserve, call outside, reconcile by key
- Decision: `execute_refund` follows PROJECT.md section 10 exactly. A short transaction locks the order row (`SELECT … FOR UPDATE`), re-checks the approval (`check_usable`) and eligibility against the refundable balance (captured payments − refunds reserved/submitted/succeeded/unknown/pending), then inserts the execution and the `reserved` ledger row under `P-<proposal_id>:refund:1` and commits. The connector call happens with no transaction open. The outcome is written in a second short transaction; a timeout is stored as `unknown`, never as success. Re-running for an existing execution never mints a key: it asks the provider by key first and re-sends with the same key only if the provider has no record (timeout before accept) or was temporarily unavailable. Amounts come from the hashed params, never a separate column.
- Eligibility is pure: `Action.validate(ctx, inp, facts)` gets a `Facts` object (effective settings, order total, refundable balance) built by the engine. This extends the spec's `validate(ctx, inp)` so actions stay deterministic and unit-testable with no DB.
- Decisions (`decide`): staff only, in scope (otherwise "not found"); eligibility re-checked when approving; refunds above `refund_without_escalation_paise` need an hq_owner; expiry from `approval_expiry_minutes`; a second decision → `AlreadyDecided`. `auto_decide` never approves refunds; vouchers up to `voucher_auto_approve_max_paise`.
- Why: the lock serialises reservations per order (two refunds that fit alone can't both pass), the DB constraints from 0009 back every step, and the same-key rule makes retries and crashes safe.
- Alternative rejected: calling the provider inside the reservation transaction (holds locks across the network; a crash leaves no record of the attempt).

## 2026-10-24 · Engine least privilege, and the Neon owner bypasses RLS
- Finding: Neon's `neondb_owner` has `rolbypassrls = true` (via `neon_superuser`). `FORCE ROW LEVEL SECURITY` does not constrain it. Moving the dev reseed to the owner role made one tenant's reseed delete every tenant's history in the test database (caught by tests before any merge; the main database was last reseeded as the app role).
- Decision: every statement run as the owner (reseed, test cleanup) filters on `tenant_id` explicitly, and a test proves reseeding tenant A leaves tenant B unchanged. Runtime code never uses the owner.
- Decision (migration 0009, after the E2.3a safety review): the app role can't delete engine rows; proposals, approvals and verifications are insert+read only; executions and refund_operations may only change status columns; audit_events append-only, and the migration fails if the app role is missing. Executions must reference an approved approval of the same proposal (composite FK including `decision`), one per proposal; refund reservations must match their proposal's amount and order (trigger), one per proposal; `amount_paise` must equal the param it came from (check); approval expiry capped at 7 days; a proposal's run must belong to its case; `create_proposal` refuses order/customer/case ids that don't belong to the case.
- Why: these are exactly the invariants the executor (E2.3b) relies on; making them structural means a bug or a race can't violate them.
- Alternative considered: a separate NOBYPASSRLS maintenance role for reseeds (RLS would protect the reseed too). Deferred: needs another role and URL in `.env`; explicit filters plus the cross-tenant test cover the dev-only path.
- Accepted risk (pending the human's decision): with explicit filters, a forgotten `WHERE tenant_id = ...` on an owner-run statement is not caught by RLS. The re-review found one such miss (`load_refs`, fixed; composite FKs would have rejected the cross-tenant ids, so it failed closed). Mitigations: owner engine used only by `scripts/seed.py`, `simulator/load.py` and test cleanup; two tests cover it (cross-tenant reseed counts, colliding slugs). The maintenance role remains the recommended hardening.

## 2026-10-24 · Proposals, approvals and the refund ledger are enforced by the database
- Decision: `action_proposals` are immutable (UPDATE rejected by trigger) and unique on `(tenant_id, id, payload_hash)`; `approvals` reference that triple (so an approval can only exist for the exact hash) and are unique per proposal (two managers can't both decide); a human approval needs `decided_by`, an auto one must not have it, and `expires_at > decided_at`. `executions` and `refund_operations` have unique idempotency keys per tenant; refund amounts are `bigint > 0`. `audit_events` is append-only for the app role (no UPDATE/DELETE/TRUNCATE). The payload hash is sha256 of canonical JSON of `{action, case_id, params}`, floats refused; params are validated in JSON mode against the action's strict `Input` (`extra="forbid"`, ints stay ints).
- Connectors are chosen per tenant by settings (`payment_connector`, `messaging_connector`, `orders_connector`), always addressed with `merchant_id_for(ctx.tenant_id)`; they translate provider exceptions into outcomes (`unknown` after a timeout, `unavailable` for transient errors) and never decide retries.
- Reseeding history (dev only) clears engine tables before commerce tables; audit rows stay.
- Why: the executor (E2.3b) will re-check all of this in code, but the database is the last line of defence against a bug, a race between two approvers, or a replayed approval.
- Alternative rejected: storing approval state on the proposal row (mutable proposal, approval not bound to a hash).

## 2026-10-23 · Mocks: in-process fakes with one idempotency core
- Decision: `mocks/` holds in-process fakes (payment, messaging, POS, delivery app) shared through a process-wide registry. Payment and messaging share `IdempotentMock`: one stored operation per (merchant, idempotency key); same key + same canonical-JSON payload hash → the stored operation (never re-applied, even after a decline); same key + other payload → `IdempotencyConflict` (HTTP 409); `get_by_key` for reconciliation is never subject to chaos. Seeded chaos: timeout before accept (nothing applied), accept-then-timeout (applied, caller can't tell), decline, processing-then-settle, delay. `/admin/chaos` (hq_owner) is only mounted when `APP_ENV` is not prod.
- Why: fast, deterministic contract and chaos tests with no extra processes (the dev machine has little headroom); keys scoped per merchant mirror real providers, so two tenants can never collide.
- Alternative rejected: standalone FastAPI mock services (extra processes and ports for the same contract); random unseeded chaos (flaky tests).
- After safety review: chaos is per merchant (`merchant_id_for(tenant_id)`), so an hq_owner only affects their own tenant; `/admin` mounts only for `APP_ENV` in {dev, test} (allow-list; unknown env names fail settings validation). Each chaos outcome comes from `Random(seed:merchant:key:attempt)`, so seeded runs reproduce regardless of thread order or other tenants' traffic. Calls return snapshots taken under the lock. Failure taxonomy for the executor: `ProviderTimeout` = unknown → reconcile by key, then retry with the same key; `ProviderUnavailable` (5xx/429 before accept) = nothing applied → retry with the same key; a `failed` operation (decline) is final for that key → a new attempt needs a new approval and a new attempt-scoped key, never a silently minted one.

## 2026-10-23 · Simulator: config-driven, fixed calendar, replace-on-reseed
- Decision: volumes, planted problems (late / missing_item / wrong_item / repeat_drop with location, hour and weekday filters) and messy-data rates live in each tenant's `simulation:` block; the generic simulator reads them plus the vertical pack (`fulfilment_kinds`). The window ends on a configured `end_date`, not today. Ids are uuid5 of the tenant + row number; reseeding deletes and reinserts the tenant's commerce rows in one transaction. The loader now prunes only config tables (`CONFIG_MODELS`).
- Why: no tenant names in code (hard rule 2); same seed → byte-identical data on any day; delete+insert is simpler and faster than upserting ~80k rows. Measured: full seed of both tenants 47 s on Neon.
- Rate tolerance: planted rates must match within ±1 point, or 3 standard errors for narrow slices (e.g. one outlet's weekday mornings, ~300 orders, where ±1 point is below sampling noise). Averaged over 6 seeds every planted rate is on target (bias check).
- Alternative rejected: hard-coding the spec's planted problems per tenant in Python; dates relative to `now()` (non-reproducible).

## 2026-10-23 · Order visibility as one SQL predicate
- Decision: `TenantContext.visible_orders()` returns a WHERE clause used by both list and detail routes: hq_owner all; scoped roles by location, narrowed by brand when the membership has brands (closes the E1.4 brand-scope gap); customers only orders of the customer row linked to their own user id. Not visible → 404.
- Why: one rule for list and detail means they can't disagree; filtering in SQL avoids loading other customers' rows into Python.
- Alternative rejected: per-row Python checks after a broad query (easy to forget on a new route, and fetches data the caller may not see).

## 2026-10-23 · History safety after E2.1 review
- Decision: `load_history` refuses to run when `APP_ENV=prod`; a catalog test fails if any non-commerce table gets an FK into commerce tables (so E2.3's cases/refunds must extend the reseed path deliberately). Removing a login user unlinks their customer (`ON DELETE SET NULL (user_id)`, PG15+; Neon runs 18); removing a brand/location that orders reference aborts the whole load with `TenantLoadError`. Money consistency (line items = order total, payments ≤ total) is asserted on DB data by a test.
- Next for E2.3b (refunds): the refundable balance is enforced in code inside one short transaction with `SELECT … FOR UPDATE` on the transaction row (PROJECT.md section 7), against `payments` minus `refund_operations` in reserved/submitted/succeeded/unknown; not as a DB check constraint, because it spans rows.
- Why: reseeding must never destroy live data, and config edits must fail loudly instead of half-applying.
- Alternative rejected: `ON DELETE CASCADE` from brands/locations to orders (silent history loss).

## 2026-10-23 · Demo auth: thin token, scope from the DB, fail closed
- Decision: `POST /auth/login {tenant, email, password}` with one demo password for seeded users (`DEMO_AUTH` can switch it off). The HS256 JWT holds only `tid` + `sub` + `exp` (secret must be ≥ 32 bytes). Every request re-reads role and location/brand scope from the DB inside the token's tenant session. Only `hq_owner` sees the whole org; scoped roles with no scope rows see nothing. Out-of-scope and other-tenant records both return 404; a customer on a staff route gets 403 (the route exists for everyone, the record question doesn't arise).
- Why: a role or scope in the token could be replayed after it was revoked; reading the user under RLS means a token pairing tenant A with a user of tenant B finds no user (401). Failing closed avoids "empty scope = everything".
- Alternative rejected: role/scope claims in the JWT (stale after changes); 403 for out-of-scope records (confirms they exist).
- Hardening after safety review: `DEMO_AUTH` defaults to off and `APP_ENV=prod` refuses demo auth or the dev JWT secret; tokens carry and verify `iss`/`aud`, TTL 60 min; one membership per user (unique constraint, and the lookup fails closed on more than one); login runs the same queries whether or not the tenant/user exists and checks the password last; the caller's context and the route's data share one transaction per request.
- Known gaps, deliberately deferred: brand scope (`membership_brands`) is loaded but not enforced, because no data is keyed by brand yet; E2.1 (first brand-keyed data: orders) must enforce it and test it. No login rate limiting or token revocation list (demo; per-request DB re-read already cuts off deleted users and changed roles).

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
- Why: FORCE makes the owner role obey RLS too (correction 2026-10-24: not for a role with BYPASSRLS, which Neon's owner has; see the entry of that date); unset tenant → NULL → no rows. Composite FKs stop a row in tenant A pointing at a row in tenant B even though FK checks bypass RLS.
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
