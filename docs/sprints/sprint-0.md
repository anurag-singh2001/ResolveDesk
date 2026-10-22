# Sprint 0 · 2026-10-23 → 2026-10-24

## Planning (2026-10-23)
Goal: tools, process and research in place; project skeleton green; Neon ready for Sprint 1 (tenancy + RLS).

Written by the main session: the scrum-master agent file was created this session and loads only after a Claude Code restart. From Sprint 0 review on, the scrum-master owns this file.

| Story | Owner | Done when | Est |
| --- | --- | --- | --- |
| E0.1 Tools (make, uv, py3.12, ruff) | main | versions print | S |
| E0.2 Git repo + first commit | main | spec commit in log | S |
| E0.3 Neon project, branches, app role, `.env` | **human** | `make db-check` ok on both branches, bypassrls=False | S |
| E0.4 Scrum-master + BA agents, EPICS, sprint files | main | this file has planning; scrum-master runs review | S |
| E0.5 Docs Docker → Neon, decisions | main | DECISIONS.md entries | S |
| E0.6 BA market research | main (deep-research) + business-analyst | `docs/research/market.md` with sources + story mapping | M |
| E1.1 Project skeleton | main + test-runner | `make test` passes, `make lint` clean | M |

Risks: E0.3 depends on the human; Sprint 1 (RLS) can't start without it.

## Stand-ups
### 2026-10-23
- Done: E0.1, E0.2 (047cb5d). E0.4, E0.5, E1.1 written; `make test` 1 passed, `make lint` clean; not yet committed.
- Next: commit Sprint 0 work; E0.6 research.
- Blocked: E0.3 waiting on human (Neon console + `scripts/neon_bootstrap.sql` + `.env`). `make db-check` → "not set".

## Review (2026-10-23, scrum-master)
Checks run by me today: `make --version` GNU Make 4.4.1, `uv --version` 0.13.5, `ruff --version` 0.17.2; `make test` 1 passed; `make lint` all checks passed, 6 files formatted; `make db-check` fails: DATABASE_URL / TEST_DATABASE_URL not set.

| Story | Result | Evidence |
| --- | --- | --- |
| E0.1 | done (already ticked) | versions print |
| E0.2 | done (already ticked) | 047cb5d |
| E0.3 | NOT done, blocked on human | `make db-check` -> "not set". Carried to Sprint 1 as a blocker |
| E0.4 | done | Agent files exist (a2b9846). Planning section was written by main because the agent was not loaded yet. Scrum-master (now running) ratifies it: scope, owners and estimates stand; E0.6 owner is business-analyst with deep-research. Ticked on that basis; a strict reading of "written by" was not met on 10-23 morning |
| E0.5 | done | DECISIONS.md has Neon-instead-of-Docker and two-roles entries (a2b9846) |
| E0.6 | NOT done | `docs/research/` does not exist yet; BA running now. Carried over |
| E1.1 | done | `make test` + `make lint` verified above (a2b9846) |

Gap: test-runner was not used for E1.1 (main ran `make test` directly); only 1 trivial test exists.

## Retro
- Went well: tooling, skeleton and process docs landed in one commit; test and lint green first try.
- Hurt: the only external dependency (Neon) is on the critical path and was not unblocked; agents created mid-session did not load until restart; one commit mixes three stories (hard to attribute rework).
- Action for Sprint 1: unblock E0.3 first thing (nothing in E1.2+ can be verified without it); commit per story.

## Scorecard
| Agent (model) | Tasks done | First-try test pass | Rework commits | Safety findings | Eval delta | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| main session (Opus 5.5, per trailer) | E0.1, E0.2, E0.4, E0.5, E1.1 | 1/1 test passed (verified by me; first-try not evidenced in a log) | 0 (2 commits, no fix-ups) | n/a | n/a | one commit for 3 stories |
| test-runner (haiku) | 0 | no data | no data | no data | no data | not used in Sprint 0 |
| safety-reviewer (sonnet) | 0 | no data | no data | no data | no data | not used in Sprint 0 |
| eval-runner (haiku) | 0 | no data | no data | no data | no data | not used |
| business-analyst (sonnet) | E0.6 in progress | no data | no data | no data | no data | output not yet delivered |
