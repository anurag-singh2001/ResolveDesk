# Sprint 3 · 2026-11-02 -> 2026-11-04 (opened 2026-10-26; UI and evals already done in Sprint 2)

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
_none yet_
