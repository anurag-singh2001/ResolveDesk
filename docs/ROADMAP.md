# ResolveDesk roadmap: v2 (Sprints 7-12)

Owned by the scrum-master agent. Backlog and status: docs/EPICS.md. Per-sprint detail: docs/sprints/sprint-N.md. Story points (SP) are Fibonacci 1/2/3/5/8/13.

## Context: why v2
v1 is complete (Sprints 0-6 closed, merged to main at cf6a861, CI green). The owner's live walkthrough found gaps:
- Escalated cases ("With our team") are dead ends: staff have no actions.
- Remedies are rigid: a Rs 150 voucher was offered on a Rs 149 order; vouchers are flat; the customer cannot choose a refund; the approver cannot switch the remedy; "Fair use failed" in red is confusing.
- The case page shows no order details and not even the customer's own words.
- Language must be set by hand in Help; it should be detected from what the customer writes.
- Privacy and data page feels useless; the Dev panel is unclear.
- No hierarchy: location managers should own their outlet's cases, with franchisee and HQ overseeing.
- Insights and Growth are tables with no charts, no hierarchy views, no HQ marketing module.
- Rules and policies are cited by decisions but nobody can read them.
- The owner needs a personal platform portal (health, schedulers, logs, alerts, AI performance, scenario lab).
- The UI is basic and needs a full revamp, designed in Claude Design and approved before any build.
- The process needs formalising: Scrum events and story points (see .claude/agents/scrum-master.md).

## Epics

| Epic | Goal | Sprints | Total SP |
| --- | --- | --- | --- |
| E12 Staff case handling and hierarchy | Every escalated case can be handled by the right person | 7 | 28 (S7.1-S7.7) |
| E13 Fair remedies | Sized vouchers, customer choice, approver switch, clear fair-use | 7 | 14 (S7.8-S7.11) |
| E14 Language auto-detection | Detect customer language from their message | 7 | 5 (S7.12) |
| E15 Transparency: rules and policies | Policies and plain-language rules readable; decisions link to source | 8 | 13 (S8.1-S8.3) |
| E16 Privacy rework and Demo controls | Useful privacy page; clear demo controls | 8 (S8.5e in 9) | 29 (S8.4 2, S8.5a-d 16, S8.5e 8, S8.6 3); re-estimated at Sprint 8 planning |
| E17 Platform owner portal | Owner sees health, jobs, logs, alerts, AI performance; scenario lab | 9-10 | 39 (S9.1-S9.5, S10.1) |
| E18 Analytics, visualisation and HQ marketing | Hierarchy dashboards with Recharts; HQ marketing module | 10-11 | 40 (S10.2-S10.3, S11.1-S11.4) |
| E19 UI/UX revamp | Designs in Sprint 7, approval gate, build 8-12 | 7 (design), 8-12 (build) | 13 design (S7.D1-D2) + 8 provisional S8.7; later build stories sized at planning |

## Sprint map

| Sprint | Dates | Goal | Epics | Planned SP |
| --- | --- | --- | --- | --- |
| 7 | 2026-10-28 → 2026-10-29 | Staff can handle every case; fair remedies; auto language; designs ready for approval | E12, E13, E14, E19-design | 60 (47 code + 13 design); see sprint-7.md capacity flag |
| 8 | 2026-10-30 → 2026-10-31 (proposed) | Transparency and trust: rules readable, useful privacy page, clear demo controls, new UI ships | E15, E16, E19 ship | 42 (39 core + 3 stretch; includes 5 carry-over S7.9); see sprint-8.md |
| 9 | TBD | Platform portal backbone | E17 (S9.x) | 31 |
| 10 | TBD | Scenario lab + metrics API + dashboards | E17 S10.1, E18 S10.2-S10.3 | 24 |
| 11 | TBD | HQ marketing module | E18 S11.x | 24 (S11.2-S11.4 sized 8/8/5 here; confirm after S11.1) |
| 12 | TBD | UI revamp completion, polish, full walkthrough, merge to main | E19 | ~30 (unsized, set at planning) |

## Velocity

| Sprint | SP planned | SP done (ticked only) | Note |
| --- | --- | --- | --- |
| 4 | not estimated in SP | not estimated in SP | S/M/L estimates only |
| 5 | not estimated in SP | not estimated in SP | S/M/L estimates only |
| 6 | not estimated in SP | not estimated in SP | S/M/L estimates only |
| 7 | 60 | (filled at Sprint Review) | |
| 8 | 42 (39 core + 3 stretch S8.5c; incl. 5 carry-over S7.9) | | Re-estimated at planning: S8.5 split 5 -> 16, S8.7 8 -> 5; S8.5e (8) moved to Sprint 9 |
| 9 | 31 | | |
| 10 | 24 | | |
| 11 | 24 | | |
| 12 | ~30 | | |

Capacity assumption: about 40 SP per 2-day sprint with 2-3 parallel builders. Revise from actual velocity after Sprint 7.

## Dependencies and gates
- Recharts approved by the owner as a web dependency (used from S10.3). The scheduler is a plain asyncio loop; language detection is heuristic plus a classifier field; no other new dependency is planned.
- The owner runs `npx skills add https://ui.chaicode.com -a claude-code` themselves; the main session reads the installed skill files before using them in design or build.
- Approval gate: no UI build (S8.7 onwards, S9.5, S10.3) starts until the owner approves the Claude Design wireframes (S7.D2).
- Backend order inside Sprint 7: S7.2 before S7.3/S7.5; S7.4 before S7.7; S7.8 before S7.9; S7.9 before S7.10; S7.5 before S7.6 for the close/reply flow.
- Sprint 9: S9.1 and S9.2 before S9.3-S9.5. S10.2 before S10.3. S11.1 before S11.2-S11.4.
- Merge `test` into `main` at each sprint close with the owner's go-ahead.
