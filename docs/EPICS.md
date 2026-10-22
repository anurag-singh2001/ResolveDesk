# Epics & stories

Backlog and status for the whole project. Owned by the `scrum-master` agent; the human can edit too.

Status: `[ ]` todo · `[~]` in progress · `[x]` done **and** done-when verified (commit hash in brackets).
A story is never ticked on a claim alone; the scrum master runs or cites the check.

| Sprint | Dates | Goal |
| --- | --- | --- |
| 0 | 2026-10-23 → 2026-10-24 | Tools, process, research, project skeleton |
| 1 | 2026-10-26 → 2026-10-28 (starting early 2026-10-23) | Foundation (tenancy, RLS, settings, auth) + data & money core |
| 2 | 2026-10-29 → 2026-10-31 | AI pipeline + safe execution |
| 3 | 2026-11-02 → 2026-11-04 | UI + evals |
| 4 | 2026-11-05 → 2026-11-06 | Ship (+ growth stretch) |

---

## E0 · Setup & process — Sprint 0
- [x] E0.1 Install make, uv, Python 3.12, ruff — done when: `make --version`, `uv --version`, `ruff --version` work
- [x] E0.2 Git repo + .gitignore + first commit — done when: `git log` shows spec commit [047cb5d]
- [ ] E0.3 (BLOCKED on human, carried to Sprint 1) Neon project, `main` + `test` branches, `resolvedesk_app` role via `scripts/neon_bootstrap.sql`, `.env` filled (human) — done when: `make db-check` shows app role with `bypassrls = False` on both branches
- [x] E0.4 Scrum-master + business-analyst agents, EPICS.md, sprint files — done when: sprint-0.md has a planning section written by scrum-master [a2b9846]
- [x] E0.5 Docs: Docker → Neon in PROJECT.md/CLAUDE.md, decisions logged — done when: DECISIONS.md has the entries [a2b9846]
- [ ] E0.6 (carried to Sprint 1, BA in progress) BA market research (`docs/research/market.md`) — done when: file exists with sources + recommendations mapped to stories

## E1 · Foundation — Sprint 0–1
- [x] E1.1 Project skeleton: pyproject, Makefile, config, `/health`, ruff, tests layout — done when: `make test` passes + `make lint` clean [a2b9846]
- [ ] E1.2 Tenancy tables + RLS (organizations, brands, locations, users, memberships), app role, tenant session helper — done when: `make migrate && make test-isolation` passes
- [ ] E1.3 Vertical packs, tenant folders (config + catalogue), tenant_settings/feature_flags, loader, settings resolver — done when: `make seed TENANT=all && make test` passes; no tenant slug in `app/`
- [ ] E1.4 Demo auth (JWT), TenantContext, roles/scope, `POST /auth/login` — done when: `make test` + `make test-isolation` pass; safety-reviewer clean

## E2 · Data & money core — Sprint 1
- [ ] E2.1 Canonical tables + deterministic simulator history (SEED=42) — done when: same seed → same checksums; planted rates ±1%; seed < 60 s
- [ ] E2.2 Mock payment/POS/delivery/messaging with failure injection + `/admin/chaos` — done when: contract tests pass incl. same key + different payload → 409
- [ ] E2.3a Connector + action registries, engine tables, proposals with payload hash — done when: unit tests pass
- [ ] E2.3b Deterministic eligibility + safe refund execution (section 10 steps 1–5) — done when: over-refund, expired approval, changed payload all blocked
- [ ] E2.3c `POST /cases` (no LLM), `GET /approvals`, `POST /approvals/{id}/decision` — done when: end-to-end refund for both tenants; safety-reviewer clean
- [ ] E2.4 Skills `add-action` and `add-connector` written from real code — done when: files exist under `.claude/skills/`

## E3 · AI pipeline — Sprint 2
- [ ] E3.1 LLM provider factory (gemini/groq/ollama, 429 backoff + fallback, repair, cache, counters) — done when: fake-model tests pass; `make llm-smoke` returns JSON
- [ ] E3.2 Policy files for both tenants + RAG ingest/retrieve (version, scope, date) — done when: version/override/isolation/missing tests pass
- [ ] E3.3 Agents + LangGraph classify → investigate/policy → propose, routing + limits — done when: routing tests pass; `pytest -m live -k proposal` passes 3 scenarios per tenant

## E4 · Safe execution — Sprint 2
- [ ] E4.1 Approve node with `interrupt()`, Postgres checkpointer (schema `lg`), auto-approve rules, resume — done when: interrupt/resume tests pass (review stop)
- [ ] E4.2 Executor, reconciliation of `unknown`, verifier, tickets + honest messages, audit + domain events — done when: rejection + expiry tests pass
- [ ] E4.3 Chaos suite: 50 cases/tenant, timeout 0.3, double submit, worker kill, two managers — done when: `make test-chaos` zero duplicates; safety-reviewer clean

## E5 · UI — Sprint 3
- [ ] E5.1 Customer portal + login picker — done when: customer raises a late-order case
- [ ] E5.2 Manager queue — done when: approve with evidence, citations, expiry visible
- [ ] E5.3 HQ view + dev panel (chaos, clock, reseed) — done when: full click-through for Spice Route refund and BrewCo Baner voucher

## E6 · Evals — Sprint 3
- [ ] E6.1 Eval harness + metrics + per-tenant report — done when: `make eval` prints table
- [ ] E6.2 30 scenarios (15/tenant, 6 held out) across the six categories — done when: all load and run
- [ ] E6.3 Single-agent baseline + comparison — done when: report shows both

## E7 · Ship — Sprint 4
- [ ] E7.1 README (problem, scope, Mermaid diagram, ≤ 6 setup commands, demo script, eval table, limits, tradeoffs) — done when: written
- [ ] E7.2 Clean-clone check of every Makefile target — done when: fresh clone + README reaches working demo

## E8 · Growth (stretch) — Sprint 4, only if E0–E7 done
- [ ] E8.1 Repeat-rate signal job + diagnosis agent — done when: planted Baner drop detected
- [ ] E8.2 Audience, campaign proposal with holdout, dual approval, idempotent sends — done when: zero duplicate sends
- [ ] E8.3 Verdict (treatment vs holdout) + playbook entry — done when: verdict computed
