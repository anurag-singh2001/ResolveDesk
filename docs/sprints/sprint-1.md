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
### 2026-10-23
- E0.3 [~]: Neon project, app role (bypassrls=False), test DB `resolvedesk_test` (database not branch, see DECISIONS.md) verified. Blocked on human: fill .env, rotate owner password (leaked in chat), then `make db-check` from .env.
- E0.6 done (6d76056).
- E1.2 done, c8ca319: `make migrate` (0001+0002) ok; `make test-isolation` 42 passed (133s, run with URLs from scratchpad file); `make test` 4 passed; `make lint` clean.
- Safety: pass 1 = 4 findings (membership scope arrays w/o tenant check; hand-kept RLS table list; weak update test; ORM-only updated_at), all fixed. Pass 2 = 4 low notes, 3 fixed, 1 deferred: pin search_path on set_updated_at() in next migration.
- Process incident: test-runner reported 42 isolation errors; cause was CRLF in env lines loaded in bash (`channel_binding=require
`), wrongly blamed on the driver. Not a code defect.
- Next: E1.3, E1.4 (E1.4 needs safety review), E2.2 mocks, E2.3a.
- Blocked: .env (human). Open human decisions: move E2.3b/E2.3c/E2.4 to Sprint 2; BA questions (aggregator framing, graduated late tiers, Rs150 voucher cap).
- Scorecard notes so far: test-runner false failure (accuracy); safety-reviewer 4 findings pass 1, 0 high after fixes.

### 2026-10-23 (second stand-up)
- E1.3 done, feature 374ccca, merged to test as 99d3c96. Verified: `make seed TENANT=all` loaded both tenants twice with identical ids; `make test` 44 passed; `make test-isolation` 54 passed (Neon); `make lint` clean; test_core_code_never_names_a_tenant passes. Ticked [x] in EPICS.md.
- Safety: pass 1 = 5 findings (app role DML on vertical_packs; unvalidated unreachable brand settings; loader did not prune removed rows; loader import guard; missing DB-level loosening test), all fixed incl. migration 0004. Pass 2 confirmed all. One suggestion rejected by main: looser integer overrides are clamped by design (spec: effective=min), not errors.
- E0.3 still [~]: human has not created .env (permission rules stop Claude writing it); DB work runs with URLs from a scratchpad file.
- New process: GitHub origin; branches main (deployed) <- test (integration) <- feature/<story>; --no-ff merges so `git revert -m 1` undoes a story; see DECISIONS.md. Human works remotely from phone; proceed without waiting unless blocked.
- Human decision: remedy tiers, voucher auto-approve cap (default Rs150) and refund channel are per-tenant settings (DECISIONS.md). BA questions on these are closed.
- Still open: Sprint-1 rescope (move E2.3b/E2.3c/E2.4 to Sprint 2). Planning defaults to the recommendation (move them).
- Next: E1.4 auth + roles (needs safety review). (Correction in third stand-up: the set_updated_at() search_path pin is NOT pending; it shipped in migration 0003, 374ccca.)

### 2026-10-23 (third stand-up)
- E1.4 done: 737baec, 7cf6113, 6552126, merged to test as 24bc2bb. E1 complete (E1.1-E1.4 all [x]).
- Verified by scrum-master today: `git log` shows the merge; `make lint` clean; `make test` 97 passed in 104 s. Isolation not re-run (4-5 min); cited from main session: 64 passed after the final commit.
- Safety: pass 1 = 7 findings (unsafe auth defaults, ambiguous membership, brand scope unenforced, login timing, two transactions per request, test gaps, no iss/aud + long TTL); all fixed except brand scope, deferred to E2.1 per DECISIONS.md and added as an explicit acceptance criterion on E2.1. Pass 2 confirmed; 3 minor follow-ups (APP_ENV defaults to prod, seed cleanup, one-transaction test) fixed.
- Correction to previous stand-up: the set_updated_at search_path pin is not pending; it shipped in migration 0003 (374ccca).
- Risk (new): Neon free tier drops connections mid-run (compute restarted 05:01 GMT). Mitigated with pool_recycle and a test-only seed retry on invalidated connections; may cause flaky CI/eval runs, keep watching.
- Scorecard notes: safety-reviewer found 7 real issues on E1.4 pass 1 (high value); main session needed 2 rework commits on E1.4.
- Next: E2.1 canonical tables + simulator. Still open: E0.3 .env (human), Sprint-1 rescope. No story at risk yet (sprint ends 2026-10-28).

### 2026-10-23 (fourth stand-up)
- E2.1 done: d7e891c, 39bc7d0, 57e6967, merged to test as 0156464. Ticked [x] in EPICS.md. Safety re-review (pass 2) is running: pending, not yet confirmed.
- Evidence (main session report, git log checked by scrum-master; DB suites not re-run): `make seed TENANT=all` brewco 2500 customers/15000 orders/400 tickets in 32.0s, spice_route 1500/6025 (25 outside window)/300 in 14.9s, 47s total (< 60s). `make test` 122 passed (1 skip); `make test-isolation` 111 passed (1 skip: brand-scope API test needs a multi-brand location, brand scope also covered per tenant by a DB-level test); `make lint` clean.
- Planted rates, mean of 6 seeds: late 7.99% (cfg 8), missing 1.89% (2), wrong 2.03% (2), Baner weekday-morning wrong 6.41% (6); Baner repeat-rate drop > 5 points after day 35, only at Baner. Deviation (DECISIONS.md): narrow slices (~300 orders) use 3 standard errors, not +-1 point, which is below sampling noise there.
- Carried E1.4 criterion (brand scope enforced and tested): met.
- Safety pass 1 = 5 findings (reseed could destroy live data; loader prune vs history FKs; brand scope proven for one tenant only; shared-state test; money not cross-checked), all fixed in 39bc7d0.
- Infra: a background test run was killed by Claude Code for low machine memory (not a code failure). Isolation suite ~12 -> ~3.5 min by sharing seeded tenants per module. Human confirmed: stay on Neon, no local Postgres.
- Scorecard notes: main session caught 1 design bug itself before ship (loader prune would have wiped history) and fixed 2 small test bugs; 1 safety-driven rework commit (39bc7d0).
- Next: E2.2 mocks, then E2.3a (per rescope plan). No story at risk (sprint ends 2026-10-28).

### 2026-10-24 (fifth stand-up)
- E2.2 done: d1e4920, 319ab3a, merged to test as 84c5395. Ticked [x] in EPICS.md. Done-when met: contract tests incl. same key + different payload -> 409.
- Evidence (main session report; scrum-master checked git log only, DB suites not re-run): `make test` 188 passed (1 skip); `make test-isolation` 111 passed; `make lint` clean; unit suite stable over 3 consecutive runs (concurrency/timing tests).
- Safety pass 1 = findings: chaos shared across tenants, too-loose dev-route gate, order-dependent seeded RNG, live-object reads, no transient-error model, test gaps. All fixed in 319ab3a. Re-review pending (not yet confirmed).
- E2.1 re-review pass 2: clean; its note closed by 650c75f (TenantLoadError names table + constraint).
- Design rule for E2.3b: a decline is final per key; a new attempt needs a new approval and an attempt-scoped idempotency key.
- Scorecard notes: 1 safety-driven rework commit (319ab3a) on E2.2; safety-reviewer pass 1 found 6 issue groups.
- Next: E2.3a (M). Fits: 4 days left (ends 2026-10-28), depends only on E1.2. Not at risk.
- Rescope reconfirmed: E2.3b, E2.3c, E2.4 -> Sprint 2 (one safe-execution slice, E2.4 written from real code). Human has still not answered; default stands.

### 2026-10-24 (sixth stand-up)
- E2.3a done: 7abf3b1, 754996a, 3e3b24f, c0c7c66, merged to test as 8fde736. Ticked [x] in EPICS.md.
- Evidence (main session report; scrum-master checked git log only, DB suites not re-run): `make test` 297 passed (2 skips); `make test-isolation` 149 passed; `make lint` clean.
- Safety pass 1 = 8 issues (DELETE+reinsert of proposals, mutable approvals, executions not bound to an approved approval of the same proposal / double-spend, refund ledger not tied to proposal, amount column vs params, params not bound to case, audit grants untested, test gaps); fixed in migration 0009 + code. Pass 2 = 1 more owner-path miss (load_refs), fixed with a colliding-slug test.
- Incident: Neon `neondb_owner` has BYPASSRLS (FORCE RLS does not bind it). An owner-run reseed wiped another tenant's history in the TEST db only; caught by tests, never merged. Fixed with explicit tenant filters, then (human approved) a NOBYPASSRLS maintenance role `resolvedesk_maint` (migration 0010) for reseeds/cleanup.
- Human decisions (2026-10-24): merge E2.3a; rescope accepted: E2.3c and E2.4 move to Sprint 2 (EPICS.md updated). Human reviews test -> main via docs/review/sprint-1.md.
- E2.3b pulled forward from Sprint 2 and started now, since Sprint 1 has time left (ends 2026-10-28). Not at risk. Needs safety review (money).
- Blocked on human: create .env (now incl. MAINT URLs); rotate `neondb_owner` password.
- Scorecard notes: safety-reviewer high value on E2.3a (9 findings over 2 passes, incl. a real cross-tenant data-loss path); 3 safety-driven rework commits (754996a, 3e3b24f, c0c7c66).

### 2026-10-24 (seventh stand-up)
- E2.3b done: b2431eb, d03d2b6, 42e72bb, 2cfec15, merged to test as b6f469e (human said merge). Ticked [x] in EPICS.md. Done-when met: over-refund, expired approval, changed payload all blocked.
- Evidence (main session report; scrum-master checked git log only, DB suites not re-run): `make lint` clean; `make test` 353 passed (6 skips); executor tests 43 passed (3 skips); `make test-isolation` 149 passed (run before the final tweak, which only touched quarantine auditing).
- Safety, 3 passes. Pass 1 = 10 findings (stale status downgrade, resume after expiry, blind resend, scope-check ordering leak, hash not checked at decision, weak redaction, etc.), all fixed. Pass 2 = real double-refund hole (releasing a reservation on 'no record yet' while an earlier request may still land); replaced by quarantine (ledger pending_reconciliation keeps the balance held, late success still recorded) plus forward-only status writes. Pass 3 clean.
- New backlog story E4.4 (operator release of quarantined refunds) added to EPICS.md.
- Scorecard notes: safety-reviewer caught 2 money-critical bugs on E2.3b (high value); 2 safety-driven rework commits (d03d2b6, 42e72bb).
- Next: E2.3c (case + approval API, uvicorn so the human can browse /docs). Sprint 1 ends 2026-10-28, 4 days left: pulled forward from Sprint 2 if the human agrees; needs safety review. Not at risk.

### 2026-10-24 (eighth stand-up)
- E2.3c done: c370de4, d4be4c3, merged to test as 7735de5. Ticked [x] in EPICS.md. Done-when met (end-to-end refund for both tenants, safety clean). PROJECT.md section 19 Day 2 done-when ("a refund resolves via API with no LLM, for both tenants") is met: Day 2 complete.
- Evidence (main session report; scrum-master checked git log only, DB suites not re-run): case API tests 22/22 (refund resolves over HTTP with no LLM; timeout shows processing, then confirmed after reconcile; rejection honest; 409 on second decision; ownership 404s); `make test` 374 passed (1 Neon connection drop, passed on rerun); `make test-isolation` 149 passed.
- Safety pass 1 = 7 findings, all fixed. Pass 2 clean + 2 minor (lock order row on open, keep repeat messages on the thread), fixed in d4be4c3.
- New backlog story E4.5 (sweeper for approved-but-never-executed refunds) in EPICS.md.
- Human can browser-test via `make api` + /docs once .env exists.
- Next: E2.4 skills (S), pulled forward from Sprint 2, the last open Sprint 1 story. Not at risk (ends 2026-10-28).
- Scorecard notes: 1 safety-driven rework commit (d4be4c3) on E2.3c; safety-reviewer found 7 issues pass 1; Neon connection drop is a flake, not a code failure.

## Review
_to fill at sprint end_

## Retro
_to fill at sprint end_

## Scorecard
_to fill at sprint end_
