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

## Review
_To fill at sprint end (scrum-master): run each done-when, tick EPICS.md with commit hash._

## Retro
_To fill at sprint end._

## Scorecard
| Agent (model) | Tasks done | First-try test pass | Rework commits | Safety findings | Eval delta | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| main session (Opus 5.5) | | | | | | |
| test-runner (haiku) | | | | | | |
| safety-reviewer (sonnet) | | | | | | |
| business-analyst (sonnet) | | | | | | |
