# Sprint 3 · 2026-11-02 -> 2026-11-04 (CLOSED 2026-10-26, all non-human stories done; opened 2026-10-26; UI and evals already done in Sprint 2)

## Planning (2026-10-26, scrum-master)
Goal: finish the stretch growth loop (E8) without touching the verified core, and clear the human items.

| # | Story | Owner | Done when | Est | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | E8.1 Repeat-rate signal job + diagnosis agent | main | planted Baner drop detected | M | On feature/E8-growth, not merged; no evidence yet. |
| 2 | E8.2 Audience, campaign proposal with holdout, dual approval, idempotent sends | main + safety-reviewer | zero duplicate sends | L | Sends are external writes: stable keys, safety review required. |
| 3 | E8.3 Verdict (treatment vs holdout) + playbook entry | main | verdict computed | M | Depends on E8.2. |
| 4 | E7.2 close-out | human or main | API + web started from a fresh clone, one sign-in | S | Only gap left. |
| 5 | E0.3 rotate Neon owner password, `make db-check` on both branches | human | db-check shows bypassrls = False on both | S | Human action, not dev work. |
| 6 | test -> main release review | human | review done | S | Pending since Sprint 1. |

Tests and safety review are not dropped; E8 is the only droppable scope.

## Stand-ups
### 2026-10-26 (end of day)
- E8.1 done: merged 80eb079. E8.2 done: merged 80eb079 after safety fixes. E8.3 done: merged 80eb079.
- E7.2 next: human copies own .env into the clone. Blocked on human only.
- E0.3, test->main merge, worktree/test DB cleanup: blocked on human.

## Review (2026-10-26, scrum-master)
Verified by citing this session's reports and `git log` (full suite not re-run by me, about 70 min on Neon).

| Story | Result | Evidence |
| --- | --- | --- |
| E8.1 repeat-rate signal | done | e811ede, merged 80eb079; tests/integration/test_growth.py 27 passed, 1 skipped (tenant shape) |
| E8.2 campaign, holdout, dual approval, idempotent sends | done | c605096 after safety review: campaign row lock on decide, consent re-checked at send, expiry gates start only, per-send error handling; safety clean after fixes; growth + isolation on merged code 225 passed, 2 skipped; migration 0015 applied to test DBs and demo DB |
| E8.3 verdict + playbook | done | e811ede/80eb079; after e047336 test_growth + seed-reload 29 passed, 1 skipped |
| E7.2 clean clone | stays [~] | clone passed uv sync, lint, db-check, migrate, 357 unit, 45 web tests, web build, seed, flight check; `make api` + `make web` ran and sign-in worked; a case escalated safely ("AI unavailable: MissingAPIKey") because the clone has no .env. One human step left: copy your own .env into the clone and raise one case |
| E0.3 | stays [~] | human: rotate Neon owner password (leaked earlier), then `make db-check` on both branches |

Scope note: growth is API only (/growth, staff-only, 404 when flag `growth` is off; BrewCo on, Spice Route off). No web UI; recorded as follow-up, not part of done-when (README "Scope").

### Full-suite record on merged test (post-E8, before e047336)
1020 passed, 2 failed, 10 skipped; chaos 1 passed, 1 failed. Both fixed in e047336:
1. Seed-reload fingerprint test failed only after growth tests: the growth simulator's `sim_growth` orders leaked. Fixture now deletes them. Verified 29 passed, 1 skipped.
2. Chaos (brewco, intermittent about 1 in 3; reproduced and diagnosed with a debug dump): an older proposal on a case was refused for balance, so the case escalated and the customer saw "needs a check" although the latest refund had succeeded and been verified. Fix in app/engine/case_status.py: a confirmed payout shows "confirmed"; case stays escalated for staff; mismatch still escalates. Deterministic regression test in tests/integration/test_refund_executor.py fails without the fix on both tenants, passes with it. Safety review: no blocking issues. After fix: chaos 2 passed; case-status integration + unit tests 591 passed, 5 skipped; ruff clean. Found-and-fixed defect: the chaos suite doing its job.

### Correction
Earlier notes said `sr-quality-002` was unevaluated. It was evaluated in the 2026-10-26 run (evals/reports/eval-20261025-222049.md, spice_route 13 scenarios, 100%), as README "Evals" states. EPICS.md E6 lines corrected.

## Carried over / human-only
- E0.3 rotate Neon owner password, then `make db-check` on both branches.
- E7.2 copy your own .env into a fresh clone, raise one case, see an AI proposal.
- Approve the test -> main merge (pending since Sprint 1).
- Approve cleanup of old worktrees and test DBs resolvedesk_t1..t5.
- Follow-ups (not stories): explicit never-sent flag in the verifier instead of the error-prefix match; demo seed keeping packs current; mock providers are in-memory (restart forgets them); growth web UI.

## Retro
- Went well: the chaos suite caught a real customer-facing wording defect (found, diagnosed, fixed with a deterministic regression test); safety review before merge found four real E8 gaps; stretch scope finished inside the verified core.
- Hurt: full suite takes about 70 min on Neon, so the two post-merge failures surfaced late; test fixture leakage (`sim_growth`) only showed in a specific test order; a stale "unevaluated" note went uncorrected.
- Action for next sprint: after any new simulator or fixture, run the seed-reload test right after the new tests in the same invocation, and run chaos 3 times on the merged branch before calling a merge done.

## Agent/model scorecard (evidence: git log trailers, reports pasted above)
| Agent | Tasks done | First-try test pass | Rework commits | Safety findings raised/missed | Eval delta | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| main session (Claude Opus 5.5 per trailers) | E8.1-E8.3, e047336 fixes | no: merged suite 1020 pass, 2 fail on first full run | 2 (c605096 hardening, e047336) | n/a | no data this sprint | all commits carry the Opus 5.5 trailer |
| Sonnet builders | no data | no data | no data | n/a | no data | no separate commit trailers or reports available |
| safety-reviewer (sonnet) | E8 review, case_status fix review | n/a | n/a | E8: findings fixed in c605096 (count not recorded); case_status: no blocking; missed: none known, but the case_status defect was found by chaos, not review | n/a | clean after fixes |
| test-runner (haiku) | no data | no data | n/a | n/a | n/a | no pasted output |
| scrum-master (sonnet) | planning, review, retro | n/a | n/a | n/a | n/a | closed E8; left E7.2 and E0.3 open |

