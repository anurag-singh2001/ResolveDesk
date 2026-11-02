# Completion plan: Sprints 7-12 (written 2026-11-01 by scrum-master)

Base: branch `test` at 30edeae holds code for Sprints 7-9, S10.1-S10.3, S11.2, S11.3a, S11.4. Ticked: S7.1-S7.3, S7.8, S8.1, S8.2, S8.4, S8.5a, S11.1. A final full suite on 30edeae is running; `test` merges into `main` only when it is green and the owner says go. Nothing below is ticked yet; a tick needs evidence (commit hash, report path, click recorded in the sprint file).

Honest summary: almost everything left is verification, not building. The biggest limits are (a) the owner's clicking time, (b) the 4h+ full suite that must run alone, (c) owner approvals for designs and decisions. Sprint 12 (UI polish) is unsized and not started.

Rules used for sequencing
- Max 2 builders at once, each in a worktree with its own scratch DB. Main session merges one story at a time and runs targeted tests after each.
- A full suite (4h+) runs with nothing heavy alongside: no builders running tests, no evals, no chaos. Builders may edit code; no test runs on the shared Neon branch while it runs.
- Every safety review ends with the report pasted into the sprint file before the story can be ticked (Sprint 9 retro action).
- Tick the same day as the evidence exists (Sprint 7 retro action).

## Batch plan

### Batch 0: today, while the full suite runs (no heavy processes)
Owner: human clicks, main session records. Light work only.
1. Owner decisions D1-D9 (section 4), they unblock everything else.
2. Click-through session on demo data (growth on for spice_route is approved). Record each click in the sprint file with role, tenant and a note on console errors. Order below in section 1.1.
3. Safety reports: re-run or file S9.1, S9.2, S9.4, S8.5e, S7.5 reports (safety-reviewer is reading/analysis, light, one at a time). Effort: about 1.5h total.
4. Seed demo rows for the portal (job_runs, llm_usage, one alert, one log) so S9.3/S9.5 can be walked populated. Builder 1 or main session, small (S).
Evidence: click log in sprint-7/8/9 files; five filed safety reports.

### Batch 1: full suite result, then fixes (about half a day plus the 4h run)
1. Read the full-suite result on 30edeae. If green: record counts in sprint-7 review, run `make lint`, confirm CI on the pushed branch, ask owner to approve merge of test into main. If red: fix per failure, targeted re-runs only, then decide whether another full run is worth 4h (only if fixes touch app code).
2. Close Sprint 7-9 stories whose evidence is now complete (tick list in 1.4).
Evidence: suite counts, lint, CI run URL, EPICS ticks with hashes.

### Batch 2: Sprint 7-9 remaining gaps (builders, max 2)
- Builder A: S7.12 per-language eval scenarios and result (needs eval run; eval DB of its own, time-based hang limit, per Sprint 8 retro). Then S9.3 and portal Jobs page adding `platform_job_runs` (known gap). 
- Builder B: S8.7 web test/build counts and Devanagari check; S8.6 reset-demo wording fix if owner chooses to amend; S7.11 web test record.
- Evals and builders: only 2 heavy at once.
Evidence: eval report path with per-language result; `make web-test` and build counts; Devanagari screenshot.

### Batch 3: Sprint 10 and 11 verification
Code exists, so this is review, safety and clicks (section 2). Builders only for fixes found. One safety review per money/tenancy/consent story (S10.2, S11.3). Real scratch run for S10.1.

### Batch 4: Sprint 12 planning and build (section 3)
Needs the owner's design approval (D1/D2). Scrum-master plans Sprint 12 first; sized stories; 2 builders.

### Batch 5: final close (needs a quiet machine for ~5h)
1. Final full suite on the last head, alone. 2. `make lint`, `make test-isolation`, `make test-chaos` x1 (after the suite, not alongside). 3. Eval re-run on its own scratch DB. 4. Full browser walkthrough (all roles, both tenants, light/dark/375px). 5. README/RUNBOOK/SCENARIOS/DECISIONS check. 6. Owner approves merge to main. 7. Sprint 7-12 reviews, retros, velocity table, scorecard.

## 1. Closing Sprints 7-9

### 1.1 Click-through list (one session, by role; record pass/fail and console errors)
Customer
- S7.9: report a problem where voucher or refund is allowed; pick each; limits enforced. Effort 10 min.
- S8.10 / O0005931: give the answer to the ask. 5 min.
- S7.12: write one message in English, one Devanagari, one Roman Hindi; check the stored language and the template language. 15 min.
- S8.5b: toggle consent off and on; see immediate effect and record. 5 min.
- S8.5c: export readable HTML and JSON. 5 min.
- S8.5d: request erasure, see lists and expected-by date, confirm, then cancel before approval. 10 min.
- S8.3: click a citation, lands on the exact policy section. 5 min.
Location manager (and staff)
- S7.4: Re-run AI on an AI-unavailable escalation; also the sweeper retry (dev panel, Run sweeper). 10 min.
- S7.7: re-run O0005779 as staff and view the result. 5 min.
- S7.5: set category, propose remedy within rule, approve with a second user, single verified payout. 15 min.
- S7.6: templated reply, free-text "from our team", each close reason; check the customer timeline. 15 min.
- S7.10: approver switches remedy; hash-bound new proposal; audited. 10 min.
- S7.11: fair-use chip shows as a warning, not red "failed". 5 min.
HQ owner
- S8.5e: privacy queue, due dates, dry run, approve and reject, overdue flag. 15 min.
- S8.6: Demo controls help text; the reset wording (D3).
- S9.3/S9.5 on seeded rows: Health, Jobs, Logs and alerts, AI performance populated.
Platform admin
- S9.1: sign-in; confirm no raw customer rows visible.
Total about 2.5 h for the owner, or main session drives and owner watches.

### 1.2 Safety reports to file (safety-reviewer, one at a time, report pasted in the sprint file)
S9.1 (platform role, SECURITY DEFINER views), S9.2, S9.4, S8.5e (approvals and customer data), S7.5 (filed text missing). Effort about 20-30 min each. Without filed reports these stories stay `[~]`.

### 1.3 Other evidence
- S7.12: eval scenarios per language exist per done-when; need the run showing Devanagari -> hi and Roman Hindi -> hi-Latn, both tenants. Builder A plus eval-runner. M effort.
- S9.3/S9.5 portal demo rows: seed (S) then walk.
- S8.7: `make web-test` and `npm run build` counts, Devanagari check. 30 min.
- S8.3, S8.6, S7.7: covered by clicks above.
- S7.D1/S7.D2: no artefact in repo. Needs owner (D1). If designs exist in Claude Design, export or screenshot them into docs and record approval.

### 1.4 Tick list once evidence lands
Sprint 7: S7.4, S7.5, S7.6, S7.7, S7.9, S7.10, S7.11, S7.12, (D1, D2 after owner). Sprint 8: S8.3, S8.5b, S8.5c, S8.5d, S8.6, S8.7. Sprint 9: S9.1-S9.5, S8.5e. About 100 SP waiting on verification.

## 2. Closing Sprints 10 and 11

| Story | Needs | Owner | Effort |
| --- | --- | --- | --- |
| S10.1 Scenario lab | One real run: create/edit a scenario YAML, run a subset on a scratch DB, compare with last report. Record report path. No safety review required unless it writes to a shared DB; confirm it uses a scratch DB. | main session + eval-runner | M, 1h plus LLM time |
| S10.2 Metrics API | Targeted tests both tenants, scope tests (location, franchisee, HQ, other tenant 404), safety review (tenancy), file report | main session, safety-reviewer | M |
| S10.3 Dashboards | Web tests, build, browser walkthrough per role with drill-down, Recharts approved (D5) | main session + human clicks | M |
| S11.2 Segments and cohorts | Tests; consented-only check; walkthrough as HQ. Safety review advised (consent) | builder fix if needed, safety-reviewer | M |
| S11.3a Calendar | Walkthrough over existing growth campaigns (needs growth on for spice_route, now approved) | human clicks | S |
| S11.3b ROI with holdout | NOT built. Build with holdout attribution; uses the verdict code from E8.3. Safety review (consent/messaging). Needs sent campaign data: run a demo campaign on the simulated clock. | builder (Sonnet), safety-reviewer | M-L, about 8 SP; split (calc vs UI) if over 8 |
| S11.4 Brand signals | Tests both tenants (brewco has 5 outlets, spice_route has 3 brands); walkthrough | builder fix if needed | S |

Note S11.3 in EPICS is one story; propose splitting into S11.3a (calendar) and S11.3b (ROI) in EPICS at Sprint 11 planning, and ticking each separately.

## 3. Sprint 12 and the rest of the roadmap

Roadmap content: Sprint 12 = "UI revamp completion, polish, full walkthrough, merge to main", epic E19, about 30 SP, explicitly unsized. It has no stories in EPICS yet. Proposed contents (to be sized at planning, split over 8 SP):
- Restyle remaining pages to the approved design system, all roles, both themes, Devanagari (about 13 SP across 2-3 stories).
- Accessibility and responsive pass at 375px, empty/error/loading states (5 SP).
- Docs/manuals: in-app Help and docs/manual updated for new screens (3 SP).
- Final full walkthrough, README/RUNBOOK/SCENARIOS update, demo script (5 SP).
- Merge test into main with owner go (1 SP, process).
Size: about 30 SP, roughly one sprint of work (about 2 days of builders) once designs are approved. It can start in parallel with Batch 3 only after D1.
Other roadmap items not started: S8.10 (ask the customer; built, answer pending), the known gap "Jobs page omits platform_job_runs", dev-panel reseed (deliberately not built), automatic pack refresh (rejected). Nothing else on the roadmap is unaccounted for.

## 4. Owner decisions (listed once, recommended answer)

| # | Decision | Blocks | Recommended |
| --- | --- | --- | --- |
| D1 | Were S7.D1/S7.D2 designs delivered and approved? Where are the artefacts? | S7.D1, S7.D2, all of Sprint 12 | Export to docs/design/, record approval date; if not approved, approve or amend now |
| D2 | Refund fit to policy, four-eyes on remedy switch, "no remedy due" wording | S7.9, S7.10 | Approve as built (code enforces limits; four-eyes on switch) |
| D3 | S8.6 "guarded reset-demo" vs RUNBOOK "disabled on purpose" | S8.6 | Amend done-when: disabled with explanation satisfies it |
| D4 | S9.3 pack refresh in scheduler: DECISIONS rejected it | S9.3 | Keep rejected, amend done-when |
| D5 | Recharts dependency approved (ROADMAP says approved) | S10.3 | Confirm |
| D6 | Add platform_job_runs to portal Jobs page | S9.5 | Yes, small |
| D7 | Seed demo job/usage/alert rows for portal walkthrough | S9.3/S9.5 | Yes |
| D8 | Merge test into main after green suite | closing | Yes, only after green suite, lint, CI |
| D9 | Split S11.3 into 3a/3b in EPICS | S11.3 | Yes |
| D10 | Provisional privacy figures (365-day retention floor, privacy contact label, 30-day target vs 90-day ceiling, no consent record for support) | S5/S8.5 sign-off | Accept as provisional, label not legal advice |
| D11 | Optional: paste primary Swiggy/Starbucks India privacy pages | S8.4 limit note | Skip; labelled secondary sources are acceptable |

Human-only, cannot be completed without the owner
- E0.3: rotate the Neon owner password, then `make db-check` on both branches.
- E7.2: copy your own .env into the clean clone, raise a case, see an AI proposal (the assistant may not read or create .env).
- Native-speaker review of Hinglish/Devanagari templates (S5.6, S7.12); until done, wording is "unreviewed" in README.
- S7.D1/S7.D2 delivery and approval (D1).
- All browser clicks in 1.1 if the owner wants them done by a person; the main session can drive a browser, but the owner should watch the money flows.
- Merge to main (D8).
- The S8.10 customer answer on O0005931.
Not completable without these: E0.3, E7.2, native review, D1-gated Sprint 12 build, S7.D1/D2 ticks. Everything else can be closed by the main session and builders.

## 5. Sequencing around the 4h suite
- Suite window 1 (now, about 4h): clicks, decisions, safety reports (reading only), doc edits, EPICS notes. No builders running tests, no evals.
- After it: Batch 2 builders (2 at once, targeted tests only, own scratch DBs) plus at most one eval.
- Do not start another full suite until all code changes are done; the one that counts is the final run in Batch 5 (about 4-5h, run alone, ideally overnight).
- Chaos (`make test-chaos`) and isolation run after the final suite, not beside it.
- Rough calendar: Batch 0-1 first session; Batch 2-3 one to two sessions; Batch 4 one to two sessions after D1; Batch 5 one session plus the overnight suite. About 5-6 working sessions in total, longer if D1 slips.

## 6. First five next actions
1. Owner answers D1-D4, D8-D9 (blocks the most).
2. Start the click-through (1.1), recording each click in sprint files.
3. Safety-reviewer files reports for S9.1, S9.2, S9.4, S8.5e, S7.5.
4. Seed portal demo rows (D7) and add platform_job_runs to Jobs page (D6).
5. Read the full-suite result on 30edeae; run `make lint`; confirm CI; then ask for the main merge (D8).

## 7. Update after the 2026-11-01 click-through (supersedes sections 1.1-1.4 and the decision table where it differs)

Decisions made: growth on for spice_route (a902a69); S11.3 split accepted (D9 done); main merges when the final suite is green (D8 given, conditional). Safety reports filed for S8.5e, S9.1, S9.2, S9.4, S7.5 (the safety-report action in Batch 0 is done; S10.2 and S11.3b still need one).

Ticked now (9 stories, 54 SP): S7.4, S7.5, S7.6, S7.7, S7.10, S8.5b, S9.1, S9.2, S10.3.

Open, with the single thing that closes each
| Story (SP) | Left to do | Who |
| --- | --- | --- |
| S7.9 (5) | click one voucher and one refund choice on the report form, see it in the proposal; D2 | human/main |
| S7.11 (1) | record the web test run (with S8.7) | main |
| S7.12 (5) | eval scenarios per language with a per-language result, both tenants | builder + eval-runner |
| S7.D1, S7.D2 (13) | owner delivers/approves designs (D1) | human |
| S8.3 (3) | confirm the older-section fallback text on screen, or fix the v3 anchor mismatch | main/builder |
| S8.5c (3) | click the JSON download | main |
| S8.5d (5) | request, confirm and withdraw an erasure on a throwaway customer | main |
| S8.5e (8) | approve and reject on a throwaway customer (dry run already seen) | main + human watch |
| S8.6 (3) | D3 wording | human |
| S8.7 (5) | `make web-test` and build counts, Devanagari check | main |
| S9.3 (5) | D4 amend done-when; add platform_job_runs to the Jobs page; walk populated | builder |
| S9.4 (5) | show one rule firing (seed a failed job); populated logs | builder/main |
| S9.5 (8) | walk populated health, jobs, logs, alerts, AI pages after seeding | main |
| S10.1 (8) | one real scratch-DB run and compare (needs a scratch DB created by the owner or a builder; main session may not touch DBs without approval) | main + eval-runner |
| S10.2 (8) | safety review (tenancy) filed; scope tests both tenants cited | safety-reviewer |
| S11.2, S11.3a, S11.4 (8+0+5) | see them on Spice Route with growth on; S11.2 safety review advised | main |
| S11.3b ROI (about 8) | build and safety-review; first add an end-to-end Spice Route campaign test (no such test exists) | builder + safety-reviewer |

New SP totals (planned vs ticked): Sprint 7 60/36, Sprint 8 42/18, Sprint 9 39/13, Sprint 10 24/8, Sprint 11 24/3. Open SP: 24 + 19 + 26 + 16 + 21 = 106, plus Sprint 12 about 30 (unsized, gated on D1) = about 136 SP. Of the 106, 13 SP are human-gated designs (D1/D2), about 8 SP is the unbuilt S11.3b, and the rest is clicks, evidence and small fixes.

Findings added to the backlog (to be sized at next planning, none ticked or counted): (a) no-remedy closing message points disputes to the Privacy desk, wording fix (1 SP); (b) O0003646 shows Refund confirmed while status says needs a check after mock state loss (needs human reconcile or documented limit); (c) staff proposal amounts are hidden from the customer timeline until approved (confirm intended); (d) mixed Hinglish and English on the Privacy page, needs the native review; (e) policy page and case lists take 5-9 s to load, performance story for Sprint 12 (3 SP); (f) no end-to-end Spice Route campaign test (add with S11.3b).

Revised first five actions: (1) Spice Route views of S11.2, S11.3a, S11.4 with growth on; (2) seed portal rows and fix the Jobs page, then walk S9.3-S9.5; (3) remaining action clicks (S7.9 choice, S8.5c JSON, S8.5d, S8.5e on a throwaway customer); (4) S7.12 per-language eval and S10.1 real scratch run; (5) read the final suite result, lint, CI, then merge to main.
