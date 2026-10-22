# Sprint 1 · 2026-10-26 → 2026-10-28 (started early, 2026-10-23)

## Planning (2026-10-23, scrum-master)
Goal: tenancy + RLS foundation and the data/money core proven on a real Neon DB.

Critical blocker: E0.3 (human: Neon project, branches, app role, `.env`). E1.2 onward cannot be verified until `make db-check` passes on both branches. Work that needs no DB (E0.6, E2.3a unit logic, E2.2 mocks, E2.4 draft) can start now.

| Story | Owner | Done when | Est | Depends |
| --- | --- | --- | --- | --- |
| E0.3 Neon + role + .env (carry-over) | human | `make db-check` bypassrls=False on both branches | S | none |
| E0.6 Market research (carry-over) | business-analyst | `docs/research/market.md` with sources + story mapping | M | none |
| E1.2 Tenancy tables + RLS | main + safety-reviewer | `make migrate && make test-isolation` | L | E0.3 |
| E1.3 Vertical packs, tenant folders, settings, loader | main | `make seed TENANT=all && make test`; no slug in `app/` | L | E1.2 |
| E1.4 Demo auth, TenantContext, login | main + safety-reviewer | `make test` + `make test-isolation`; safety clean | M | E1.2 |
| E2.1 Canonical tables + simulator (SEED=42) | main | same checksums, rates +-1%, seed < 60 s | L | E1.3 |
| E2.2 Mock payment/POS/delivery/messaging + chaos | main | contract tests, same key + diff payload -> 409 | M | none for mocks; E1.4 for `/admin/chaos` |
| E2.3a Registries, engine tables, payload-hash proposals | main | unit tests pass | M | E1.2 |
| E2.3b Eligibility + safe refund execution | main + safety-reviewer | over-refund, expired, changed payload blocked | L | E2.3a, E2.2 |
| E2.3c Cases/approvals endpoints, e2e refund both tenants | main + safety-reviewer | e2e for both tenants; safety clean | L | E2.3b, E1.4 |
| E2.4 Skills add-action / add-connector | main | files under `.claude/skills/` | S | E2.3b (written from real code) |

### Scope verdict: unrealistic
11 stories (5 L, 4 M, 2 S) in 3 working days (about 5 with the early start), with a hard external blocker and three safety reviews. Money/approvals/RLS code must not be rushed (tests and safety review are never dropped).

Proposed commit for Sprint 1: E0.3, E0.6, E1.2, E1.3, E1.4, E2.1, E2.2, E2.3a.
Propose moving to Sprint 2: E2.3b, E2.3c, E2.4 (they form one safe-execution slice and E2.4 must follow real code). Caveat: Sprint 2 already holds E3 and E4, so it becomes overloaded; if so, the next drop is E3.3 live tests into Sprint 3 before touching tests/safety. E8 stays dropped. Decision needed from the human.

### At risk
- E0.3 (blocks E1.2-E1.4, E2.1, E2.3a-c).
- Everything in the critical chain if E0.3 is not done by 2026-10-24.

## Stand-ups
_none yet_

## Review
_to fill at sprint end_

## Retro
_to fill at sprint end_

## Scorecard
_to fill at sprint end_
