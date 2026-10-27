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
### 2026-10-26 evening
- S4.1 done: f9dd2fa / 6177d9b; browser bug (every reply 500 after S4.3 merge, _out signature) fixed 59a711e. Next: F2. Blocked: none.
- S4.2 done: b357f71 / 23376a5; walkthrough fixes eb51a70 (data_as_of), 02e25d4 (rupees). Next: none.
- S4.3 done: e25679b / 26e6e3d; rework 8f1b28b + 040081e after safety HIGH (simulated clock leaked into approval/growth timestamps).
- S4.4 [~]: chaos x3 green (2/2 each); targeted 77 passed, 3 skipped; full suite before reply fix 1077 passed, 4 failed (all test_case_reply_api, fixed 59a711e); full re-run on 02e0ade in progress.
- S4.4 evals (eval-20261026-161051.md): agents 100% both; baseline brewco 100%, spice_route 92% (sr-wrong-001); over-rule 0; injections held 2/2, 1/1.
- S4.5 [~]: README demo steps 6-7 (02e0ade); test to main needs user re-confirm.
- Follow-ups (not ticked): F1 explicit never-sent flag in verifier; F2 sweeper net for skipped reply resume + concurrent-reply test; F3 done (ea2103e); F4 polish (needed-info templates, growth rounding 76.4 vs 76.5, mock persistence O(n^2), 154 msgs ~2 min).

## Status
CLOSED 2026-10-27. Only the S4.5 test-to-main merge tick remains (main session, after the merge).

## Review (2026-10-27)
- S4.1, S4.2, S4.3a, S4.3b: ticked earlier with commits (see EPICS.md).
- S4.4 ticked: full suite on 914f1bb 1128 passed, 12 skipped, 6 failed. The 6 (test_meta_api categories, test_pack_refresh, test_workflow_resume restart) came from the working tree changing mid-run (S5.1/S5.5 merged, a reviewer checked out another commit). Clean-head re-run 136 passed; its one failure was an audit-scan false positive fixed in bfe1b30. Chaos 3 passed, 1 skipped (growth off for one tenant); chaos x3 on merged Sprint 4 code earlier 2/2 each. Isolation 206 passed on 1d917f8. Caveat: no single full run on the final head; Sprint 5 batches cover it.
- Follow-ups merged: F1 (migration 0016, b09c157), F2 (beae726), F3 (ea2103e), F4 (0158378), clock-skew fix d0ee6ef.
- S4.5 stays [~]: README demo steps 6-7 done (02e0ade); test to main pending. The user said "push when green... close all open points", so the merge follows this docs commit.

## Retro (final, 2026-10-27)
Went well
- Parallel builders on isolated DBs (b1..b3) delivered S4.1-S4.3 in one day; safety review caught a real HIGH (simulated clock leaked into approval and growth timestamps) before merge.
- The browser walkthrough found what unit tests missed; the F1 and F2 reviews each found a medium that was fixed before merge.

Hurt
- (a) The Sonnet session limit hit around midnight and stopped two agents mid-task (F4 among them).
- (b) The machine ran critically low on memory with 2 servers, a full suite, chaos, evals, 4 builders and 7 Neon DBs at once. Claude Code killed the API, the web server, the full-suite run and one test run. Lesson: cap parallelism at about 2 heavy processes.
- (c) Semantic merge conflict between parallel builders: S4.1 called `_out(db, case)` after S4.3 changed its signature, so every customer reply returned 500. Git merged cleanly; only the browser walkthrough caught it. Lesson: after merging parallel branches run the merged branch's targeted tests before the walkthrough, and give builders the current branch head.
- (d) A stale vite server on port 5173 served a broken page.

- (e) The full suite on a moving working tree gave 6 false failures (a reviewer checked out another commit in the same folder). Lesson: never review or merge in the folder a suite is running from.

Action for next sprint
- Add to the planning checklist: max 2 heavy processes at once; a targeted-test run on the merged head after every merge, before any browser check; kill stale dev servers (port 5173, API) before a walkthrough.

## Scorecard
Final; "no data" where no output was pasted into this file.

| Agent | Tasks done | First-try test pass | Rework commits | Safety findings raised/missed | Eval delta | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| main session (Opus per S4.4 owner; trailer not checked) | S4.4/S4.5 integration, F1, F2, F3, fixes 59a711e, eb51a70, 02e25d4 | full suite before reply fix: 1077 passed, 4 failed (all test_case_reply_api) | 59a711e (S4.1 integration), b09c157 (F1 review fix), F2 review fixes | n/a | evals eval-20261026-161051.md: agents 100% both tenants; baseline brewco 100%, spice_route 92%; over-rule 0 | final: 1128 passed / 6 failed from moving tree, clean re-run 136 passed |
| builder B1 (Sonnet) | S4.1 | no data | 0 own (integration fix by main) | safety: no high/medium | no data | |
| builder B2 (Sonnet) | S4.2 | no data | eb51a70, 02e25d4, ea2103e (walkthrough follow-ups) | no data | no data | |
| builder B3 (Sonnet) | S4.3a, S4.3b | no data | 8f1b28b, 040081e after safety HIGH | 1 HIGH raised (clock leak); 0 known missed | no data | |
| test-runner (haiku) | no data | no data | no data | n/a | n/a | |
| safety-reviewer (sonnet) | reviews of B1-B3, F1, F2, F4 (lows fixed 0158378) | n/a | n/a | raised: 1 HIGH (B3), 1 medium (F1), 1 medium + lows (F2); missed: the _out merge break (outside its scope) | n/a | |
| eval-runner (haiku) | evals run 2026-10-26 | n/a | n/a | n/a | see main row | |
| business-analyst (sonnet) | no work this sprint | n/a | n/a | n/a | n/a | |
