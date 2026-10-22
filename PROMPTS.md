# ResolveDesk — Prompts for Claude Code

For you, not for Claude to read automatically. Copy one prompt per session.
Before each: `/clear`, then Shift+Tab into plan mode. After each: tests pass → commit → LEARNING.md → `/clear`.

---

## 0. Setup (once)

1. Create an empty folder `resolvedesk/` and copy into it: `CLAUDE.md`, `docs/`, `.claude/`, this file.
2. `git init && git add . && git commit -m "Project spec and Claude Code setup"`
3. Create `.env` (never commit it):
   ```
   GEMINI_API_KEY=...
   GROQ_API_KEY=...
   LLM_PROVIDER=gemini
   LLM_CLASSIFIER_PROVIDER=groq
   LLM_FALLBACK_PROVIDER=groq
   OLLAMA_BASE_URL=http://localhost:11434
   DATABASE_URL=postgresql+psycopg://resolvedesk:resolvedesk@localhost:5432/resolvedesk
   JWT_SECRET=dev-only-change-me
   ```
4. Add `.env` to `.gitignore`.
5. Open Claude Code in the folder; set model to Sonnet with `/model`.

---

## Kickoff prompt (first session)

```
You're joining a project that is fully specified in @docs/PROJECT.md, with working rules in CLAUDE.md.

Before writing any code:
1. Read docs/PROJECT.md fully once.
2. Reply with:
   a) A 10-line summary of what we're building, in your own words.
   b) The 10 hard rules, each restated in one line.
   c) Anything in the spec that is ambiguous, contradictory or risky for a 7-day POC (max 8 points), each with your suggested resolution.
   d) Your proposed session breakdown for Day 1 (section 19), as 3–4 sessions, each with its done-when test.
3. Don't create or edit any files in this session. I'll answer your questions, then we start Day 1 in a fresh session.
```

After it replies: answer its questions, add any decisions to `docs/DECISIONS.md` yourself or ask it to, commit, `/clear`.

---

## Day 1 — Foundation

### 1a. Project skeleton
```
Feature: Project skeleton and dev environment.
Context: @docs/PROJECT.md sections 4 and 5.
Build: pyproject.toml (uv), docker-compose.yml (postgres 16 + pgvector), Makefile with every command listed in CLAUDE.md (stub targets that aren't buildable yet should print "not implemented yet"), app/config.py with pydantic-settings reading .env, app/main.py with GET /health, ruff config, tests/ layout with one passing health test, .gitignore.
Done when: `make up && make test` passes with the health test, and `make lint` is clean.
Out of scope: database tables, auth.
Plan first and list the files you'll create. Ask before adding any dependency not in section 4.
```

### 1b. Tenancy tables and RLS
```
Feature: Tenancy schema with row-level security.
Context: @docs/PROJECT.md sections 3, 6, 7 (Tenancy group only).
Build: SQLAlchemy models + first Alembic migration for organizations, brands, locations, users, memberships. RLS on tenant-owned tables using current_setting('app.tenant_id'). A non-superuser app DB role so RLS actually applies. app/core/db.py with a session helper that sets app.tenant_id per request/transaction.
Tests: tests/isolation/ proving a session for tenant A cannot select, update or delete tenant B rows, and that a session with no tenant set sees nothing.
Done when: `make migrate && make test-isolation` passes.
Rules that apply: 1, 10. Explain in 2 lines why the app role must not be the table owner.
Plan first.
```

### 1c. Tenant loader and settings resolver
```
Feature: Generic tenant loader and settings inheritance.
Context: @docs/PROJECT.md sections 6, 14, 18. Vertical packs in section 11/18.
Build:
- verticals/cloud_kitchen.yaml and verticals/coffee_chain.yaml (issue categories, actions, metrics, vocabulary, default limits in paise).
- tenants/spice_route/tenant.yaml + catalogue.csv and tenants/brewco/tenant.yaml + catalogue.csv with the structure in section 6 (BrewCo: 5 outlets, franchisee A/B, Baner override refund_without_escalation_paise=30000).
- tenant_settings + feature_flags tables (migration), loader `make seed TENANT=<slug|all>` (config + catalogue only for now), app/core/settings_resolver.py: pack → org → brand → location, limits can only tighten.
Tests: unit tests for the resolver (including an override that tries to loosen a limit); loader idempotent (running twice changes nothing); conftest `tenant` fixture parametrized over every folder in tenants/.
Done when: `make seed TENANT=all && make test` passes. grep finds no tenant slug in app/.
Plan first.
```

### 1d. Auth and roles
```
Feature: Demo auth with roles and scope.
Context: @docs/PROJECT.md sections 3 (rules 1, 8), 6 (roles), 12 (POST /auth/login).
Build: app/core/auth.py (JWT, demo users from tenant.yaml, password "demo"), TenantContext dependency for FastAPI (tenant, user, role, scope), role/scope helpers, POST /auth/login.
Tests: isolation matrix rows for login + scope (Baner manager can't act on Kothrud; franchisee A can't see franchisee B outlets); cross-tenant access returns 404.
Done when: `make test` and `make test-isolation` pass for both tenants.
Then: run safety-reviewer and fix findings.
Plan first.
```

---

## Day 2 — Canonical data, mocks, registries

### 2a. Canonical tables + simulator history
```
Feature: Canonical commerce tables and deterministic history simulator.
Context: @docs/PROJECT.md sections 7 (Canonical, Tickets), 14.
Build: migration for customers, transactions, line_items, payments, fulfilments, tickets, ticket_messages, consents (RLS on all). simulator/ that reads the vertical pack + tenant.yaml + catalogue and generates the volumes and planted problems in section 14 with SEED=42. Extend `make seed` to run it.
Tests: same seed → identical row counts and checksums; planted problems present at the stated rates (±1%); all money columns are integers.
Done when: `make seed TENANT=all && make test` passes in under 60 s.
Plan first. Keep the simulator generic: it must not contain tenant slugs.
```

### 2b. Mock services with failure injection
```
Feature: Mock external services.
Context: @docs/PROJECT.md section 10 (mock payment contract), 12 (/admin/chaos).
Build: mocks/ FastAPI apps (or in-process fakes behind the same interface) for payment, POS, delivery app, messaging. Payment: idempotency contract, query by key, configurable timeout rate, delay, and "accept then time out". Chaos settings via /admin/chaos (dev only).
Tests: contract tests for each mock, including same key + different payload → 409.
Done when: `make test` passes.
Plan first.
```

### 2c. Registries, eligibility, no-LLM refund
```
Feature: Connector + action registries and a refund resolved without any LLM.
Context: @docs/PROJECT.md sections 8, 10, 7 (Engine, Money).
Build: Connector and Action base classes + registries; mock connectors; refund, free_item_voucher, send_status_update actions; engine tables (cases, workflow_runs, action_proposals, approvals, executions, verifications, refund_operations, audit_events, domain_events); proposals with payload hash; deterministic eligibility rules from settings; safe execution exactly as section 10 steps 1–5; POST /cases (no LLM: category passed explicitly for now), GET /approvals, POST /approvals/{id}/decision.
Tests: end-to-end refund for both tenants; over-refund blocked; expired approval blocked; changed payload invalidates approval.
Done when: `make test` passes. Then run safety-reviewer and fix findings.
Plan first. This is the most important session of the week; take it in 2–3 steps and stop after each for me to review.
```

After 2c: ask Claude to write `.claude/skills/add-action/SKILL.md` and `.claude/skills/add-connector/SKILL.md` from the code that now exists (prompt at the end of this file).

---

## Day 3 — LLM, RAG, agents

### 3a. LLM provider factory
```
Feature: LLM provider factory with fallback and dev cache.
Context: @docs/PROJECT.md section 4 (LLM providers).
Build: app/llm/providers.py — get_chat_model(role) for roles main/classifier, providers gemini/groq/ollama from env, retry with backoff on 429 then fallback, structured output helper with Pydantic validation and one repair attempt, file-based cache when LLM_CACHE=1, counters for calls/tokens per run.
Tests: use fake models; test fallback on simulated 429, repair path, cache hit.
Done when: `make test` passes and a smoke script `make llm-smoke` returns a JSON classification from the configured provider.
Plan first.
```

### 3b. Policies and RAG
```
Feature: Versioned, scoped policy retrieval.
Context: @docs/PROJECT.md section 11.
Build: write the policy markdown files for both tenants (realistic, short, with numbered sections; BrewCo Baner override). app/rag/ingest.py (split by heading, local bge-small embeddings, policy_documents + policy_chunks with RLS), app/rag/retrieve.py (filter tenant, scope location→brand→org, effective date; then similarity; return section refs). `make seed` ingests policies.
Tests: correct version chosen by order date; Baner override wins over org for Baner orders only; other tenant's policies never returned; missing policy reported as missing.
Done when: `make test` passes.
Plan first.
```

### 3c. Agents and graph up to proposal
```
Feature: LangGraph loop from classify to validated proposal.
Context: @docs/PROJECT.md sections 8, 9.
Build: classifier, investigation (read tools from section 9), policy, resolution agents with Pydantic outputs; app/engine/graph.py with nodes classify → investigate (+ policy concurrently where possible) → propose → (stop before approval for now); routing for missing info, no policy, invalid output, step/LLM-call limits. POST /cases now uses the classifier.
Tests: with fake LLMs, graph routing tests; with real provider behind a marker (`-m live`), 3 scenarios per tenant produce cited proposals.
Done when: `make test` passes and `uv run pytest -m live -k proposal` passes.
Plan first.
```

---

## Day 4 — Approval and safe execution

```
Feature: Approval pause/resume, execution, reconciliation, verification.
Context: @docs/PROJECT.md sections 8 (interrupt/resume), 10 (safe refund execution), 15 (chaos).
Build: approve node with interrupt() and Postgres checkpointer (schema lg), auto-approve rules from settings, resume on decision via Command(resume=...) same thread_id; executor node; reconciliation for unknown status; verifier; ticket updates with honest customer messages; audit + domain events (refund.succeeded etc).
Tests: tests/chaos/ — 50 cases per tenant concurrently with timeout_rate 0.3 → zero duplicates; double approval submit; worker killed mid-execution then resumed; two managers approving the same proposal; rejection path; expiry.
Done when: `make test-chaos` passes. Then safety-reviewer clean.
Plan first. Stop after the interrupt/resume part for me to review before execution.
```

---

## Day 5 — UI

```
Feature: Streamlit demo UI.
Context: @docs/PROJECT.md section 13. The API already exists; the UI only calls the API.
Build: ui/ pages: customer portal, manager queue, HQ view (metrics by outlet from existing data), dev panel (chaos, clock, reseed). Login picker with demo users of both tenants.
Done when: `make ui` and I can click through: customer raises late-order case → manager approves → customer sees confirmed refund, for Spice Route; and a wrong-order voucher at BrewCo Baner.
Keep it plain; no custom CSS beyond basics.
Plan first.
```

---

## Day 6 — Evals

```
Feature: Scenario eval harness.
Context: @docs/PROJECT.md sections 14 (scenario format), 16.
Build: evals/ harness (seed scenario → message via API → reviewer decision → wait → assert DB + mock state), metrics and per-tenant report table, reports saved to evals/reports/<timestamp>.md, --tenant, --held-out, --baseline (single-agent) flags. Write 30 scenarios (15 per tenant) across the six categories; mark 6 as held_out.
Done when: `make eval` prints the table for both tenants and baseline comparison.
Plan first. Then use eval-runner for later runs.
```

---

## Day 7 — Ship

```
Feature: README and demo readiness.
Context: @docs/PROJECT.md whole; current code.
Build: README.md (problem, scope, architecture diagram in Mermaid, setup in ≤ 6 commands, demo script for the 3 demos: approved refund, blocked request, timeout recovery; eval results table from the latest report; known limitations; tradeoffs). Check every Makefile target works from a clean clone.
Done when: a fresh clone + README steps reaches a working demo.
Plan first.
```

Stretch (only if Day 1–6 are done):
```
Feature: Growth signal end to end for BrewCo Baner.
Context: @docs/PROJECT.md section 17.
Build exactly steps 1–7; reuse proposals, approvals, executor, idempotency. Feature-flagged (spice_route has growth off).
Done when: the simulator's planted Baner drop is detected, a campaign proposal with holdout is approved, sent with zero duplicate sends, and the verdict is computed.
Plan first.
```

---

## Reusable prompts

**Write a skill from existing code**
```
Write .claude/skills/<name>/SKILL.md describing how to <add an action / add a connector / onboard a tenant / write a migration> in this repo, based on the real code in <paths>. Include: files to create, the interface to implement, registration, settings/flags, the test template, and a checklist. Under 80 lines. Frontmatter: name, description (when to use it).
```

**Review my code**
```
I wrote <file>. Review it against docs/PROJECT.md section <n> and hard rules <numbers>. List problems with file:line and why. Don't rewrite it; I'll fix it myself.
```

**Explain before I approve**
```
Before you implement, explain in plain words: what each new file does, why this approach over <alternative>, and what could break. Keep it under 15 lines.
```

**Something is off**
```
Stop. Don't change more code. Tell me what you think is wrong, what you've tried, and two options for fixing it.
```

**Quiz me (end of day, in claude.ai chat)**
```
Ask me 5 questions about what I built today in ResolveDesk (I'll paste today's LEARNING.md entries). Check my answers and tell me what to revisit.
```
