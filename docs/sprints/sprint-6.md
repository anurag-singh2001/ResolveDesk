# Sprint 6 · Hardening and handover

Status: OPEN 2026-10-27. Dates 2026-10-27 to 2026-10-28 (2 days).

## Planning (2026-10-27)
Goal: prove the final head is clean (suite, deadlock, evals, CI) and leave a runnable, documented project.

| # | Story | Owner | Est | Done-when |
| --- | --- | --- | --- | --- |
| S6.1 | One clean full-suite run on the final head | main session | S | `pytest -m "not chaos and not live"` in ONE process on a quiet DB: 0 failed, counts recorded; README Tests line updated |
| S6.2 | Deadlock repro test for S5.2 customer lock | Sonnet builder | M | test fails on pre-fix lock mode/order, passes on current code, both tenants |
| S6.3 | Eval re-run incl. 3 Hinglish/Hindi scenarios, scratch DB | eval-runner / main | S | report in evals/reports/ with per-tenant table, over-rule 0, injections held; README Evals table updated |
| S6.4 | CI on GitHub Actions | Sonnet builder | M | workflow: ruff, unit tests, web tests + build on push/PR, no secrets; green on pushed branch |
| S6.5 | Demo runbook + scenario catalogue | main session | M | docs/RUNBOOK.md and docs/SCENARIOS.md exist; every scenario cites a test or eval id |
| S6.6 | Cleanup | main session | S | only neondb/resolvedesk_test remain; `git worktree list` shows main checkout only |

Order: S6.2 and S6.4 (builders) in parallel with S6.5 docs; S6.1 and S6.3 after builders merge (they need the final head and a quiet DB); S6.6 last.

Does not fit / flags:
- S6.1 and S6.3 both want a quiet DB and the final head: run sequentially, never alongside builder test runs. Max 2 heavy processes at once (Sprint 4 retro).
- S6.4 "green on the pushed branch" needs a push, which the human must approve; stays `[~]` until then.
- S6.6 must wait for S6.1-S6.3 (they use scratch DBs b1..b7).
- Drop first if short: S6.5 SCENARIOS.md depth (keep RUNBOOK). Never drop S6.1 or S6.2 tests.

Risks: Neon connection drops (rerun, record the flake, do not hide it); memory (max 2 heavy processes); usage limits (do the cheap docs stories first if limits tighten).

Deadline check 2026-10-27: 0 of 2 days used; nothing at risk yet. Mark at risk when under 25% of time remains (from 2026-10-28 midday) and not `[~]`.

Entry rule: Sprint 5 closed (yes, 1d917f8; S5.3 ticked at 989cf8f). Observation: worktrees for S6.2 (feature/S6.2-deadlock-repro) and S6.4 (feature/S6.4-ci) already exist at e2e0aeb, no commits yet.

## Stand-ups

### Stand-up 2026-10-27 (sprint opening)
Evidence: git log HEAD e2e0aeb on branch test; `git worktree list`.

| Participant | Done (evidence) | Next | Blocked |
| --- | --- | --- | --- |
| Main session (Opus) | Sprint 5 closed and ticked (d4097ec, 61362cc); sprint overview and stand-up rule (e2e0aeb) | Start S6.5 docs; coordinate builders; later S6.1, S6.3, S6.6 | none |
| Builder S6.2 (Sonnet) | Worktree created (feature/S6.2-deadlock-repro at e2e0aeb); no commits yet | Write deadlock repro test, verify it fails on pre-fix lock | none |
| Builder S6.4 (Sonnet) | Worktree created (feature/S6.4-ci at e2e0aeb); no commits yet | Write GitHub Actions workflow (ruff, unit, web test + build, no secrets) | Push approval for the green check |
| safety-reviewer | no activity this sprint (last: S5.2 re-review) | Review S6.2 only if lock code changes | none |
| test-runner | no activity this sprint | Run suites for S6.1 once the final head is set | none |
| eval-runner | no activity this sprint | S6.3 after builders merge, scratch DB | quiet DB needed |
| business-analyst | no activity | none planned | none |
| scrum-master | Opened Sprint 6 (this file, E11 in EPICS.md) | Review/tick stories with evidence | none |
| Human owner | Approved Sprint 6 scope | Waiting on human: E0.3 rotate Neon owner password; E7.2 clean-clone .env check; provisional decisions and Hindi/Hinglish native review; approve push for S6.4 CI | none |

## Review
(pending)

## Retro
(pending)

## Scorecard
(pending, end of sprint)
