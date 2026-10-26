# Sprint 4 · Spec gaps to a complete v1

Dates: 2026-10-26 to 2026-10-27 (original plan 2026-11-05 to 2026-11-06 was pulled forward; the user's Claude usage resets Tuesday 2026-10-27).

## Planning (2026-10-26)
Goal: close every spec gap found by the section 12/13/17 audit so v1 is complete, then ship.

| Story | Owner | Branch | Est | Done-when (short) |
| --- | --- | --- | --- | --- |
| S4.1 Case reply to needs-info | Sonnet builder B1 (DB resolvedesk_b1) | feature/S4.1-case-reply | M | POST /cases/{id}/messages; owner-only, 404 other tenant, 409 unless awaiting_info, double submit gives one proposal, timeline "You replied" |
| S4.2 HQ insights + Growth UI | Sonnet builder B2 (resolvedesk_b2) | feature/S4.2-hq-insights-growth-ui | L | GET /insights/outlets + Insights page; Growth page flag-gated |
| S4.3a Simulated clock | B3 (resolvedesk_b3) | feature/S4.3-dev-clock-durable-mocks | S | GET/POST /admin/clock dev-only + dev panel card |
| S4.3b Durable mocks | B3 | same | S | MOCK_STATE_FILE persists mock providers across API restart |
| S4.4 Integration | main session (Opus) | test | L | merge after safety review, suite + chaos x3 + isolation green, evals re-run, browser walkthrough |
| S4.5 Ship | main session | test to main | M | docs updated, lint clean, merge test to main after user re-confirms |

Does not fit / flagged: S4.2 is the largest and the likeliest to slip; if capacity runs short, ship the Insights page first and the Growth page second. Never drop tests or safety review. E8 stretch is already done, so there is no stretch to drop.

Carried human-only: E0.3 (rotate Neon owner password), E7.2 (copy .env into clean clone, see an AI proposal).

Risks and mitigations
- Neon slowness: full suite takes about 70 min. Builders run only targeted tests plus isolation in their own DBs; the full suite runs once, in S4.4.
- Usage limits: two-day window with a reset on 2026-10-27. Order work by value (S4.1, S4.2, S4.3), keep S4.4 and S4.5 reserved, and record state in this file so a session can resume.
- Merge conflicts: B1, B2 and B3 all touch the web/src/App.tsx nav and docs/api/frontend-contract.md. Mitigation: each builder appends in its own clearly marked block and rebases on test before handing back; main session merges one at a time (B1, then B3, then B2) and re-runs web-test after each.
- Shared DB state: each builder uses only its own resolvedesk_bN database; never the demo or test DB.

## Housekeeping done 2026-10-26
- 17 merged, clean worktrees removed.
- Old test DBs resolvedesk_t1..t5 dropped.
- Three fresh isolated builder DBs resolvedesk_b1..b3 created and migrated to 0015.
- test merged to main at bf0a2b5 with the user's approval.
- Demo API restarted on the fixed code.

## Stand-ups
(none yet)

## Review
(pending)

## Retro
(pending)

## Scorecard
(end of sprint)
