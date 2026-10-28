# Sprint 7

## Sprint Planning (2026-10-28)

**Sprint goal:** Staff can handle every case; fair remedies; auto language; designs ready for approval.
**Dates:** 2026-10-28 → 2026-10-29 (2 days).
**Source:** docs/ROADMAP.md, epics E12, E13, E14, E19 (design).

### Capacity and fit
- Capacity: about 40 SP (2-day sprint, 2-3 parallel builders). First sprint measured in SP, so the figure is an assumption.
- Pulled: 60 SP = 47 SP code (S7.1-S7.12) + 13 SP design (S7.D1, S7.D2, run by the main session in Claude Design in parallel with the builders).
- FLAG: 47 SP of code is over the 40 SP capacity by 7 SP, and the design track is on top. Carry-over order if the sprint runs short (lowest risk to the goal first): S7.10 (5), S7.9 (5), S7.7 (1, only needs S7.4), S7.11 (1). Never dropped: tests, safety review. Points of carried stories stay unchanged.
- Dependency chain that limits parallelism: S7.2 -> S7.3, S7.5 -> S7.6; S7.8 -> S7.9 -> S7.10; S7.4 -> S7.7.
- Suggested builder lanes: A = S7.1, S7.2, S7.3, S7.5, S7.6 (case/hierarchy); B = S7.8, S7.9, S7.10, S7.11 (remedies); C = S7.4, S7.12 (AI/language), then S7.7.
- Common DoD (docs/EPICS.md "Working agreement"): tests for both tenants (never naming a tenant), `make lint` clean, safety review where marked, docs/manuals updated, browser walkthrough for UI stories, CI green.

### Stories

#### S7.1 Case page shows the order and the customer's words (3 SP)
- User story: As a location manager I want to see the order's items, totals, promised and delivered times and the customer's exact message on the case page so that I can judge the case without opening other tools.
- Acceptance criteria:
  - Given a staff user can see the order's location, When they open the case page, Then the items, totals, promised and delivered times are shown (via GET /orders/{id}, scoped by visible_orders).
  - Given a case with a customer report, When staff open it, Then the customer's exact message is shown (CaseOut.customer_message).
  - Given a staff user cannot see the order's location or the order is in another tenant, When they request it, Then the response is 404.
- Owner agent: Sonnet builder (lane A). Dependencies: none.
- DoD notes: safety review no (read path reuses existing scoping; tenancy tests included); browser walkthrough yes.

#### S7.2 Routing by hierarchy (5 SP)
- User story: As a location manager I want cases from my outlet assigned to me so that I own and resolve them, while the franchisee and HQ can oversee.
- Acceptance criteria:
  - Given an escalated case on an order at location L, When it is escalated, Then cases.owner_user_id is the location manager of L.
  - Given a franchisee owner, When they list cases, Then they see only cases of their locations; HQ sees all in the tenant.
  - Given an amount above refund_without_escalation_paise (needs_hq), When the case escalates, Then it is owned by HQ.
  - Given a user outside the scope or another tenant, When they open the case, Then 404.
  - Migration adds cases.owner_user_id with RLS intact.
- Owner agent: Sonnet builder (lane A). Dependencies: none (builds on TenantContext.can_see_location and approvals.decide scope).
- DoD notes: safety review YES (tenancy, RLS, migration).

#### S7.3 Escalation queue (3 SP)
- User story: As a location manager I want a "With our team" list showing why each case was escalated, how long it has waited and who owns it so that I can work the oldest first.
- Acceptance criteria:
  - Given escalated cases exist, When a staff user opens the queue, Then they see only cases in their role scope, each with reason (from audit case.escalated), wait time and owner.
  - Given filters (reason, owner, location, age), When applied, Then the list narrows server-side.
  - Given another tenant's cases, When queried, Then they never appear.
- Owner agent: Sonnet builder (lane A). Dependencies: S7.2.
- DoD notes: safety review no; browser walkthrough yes.

#### S7.4 Re-run the AI (3 SP)
- User story: As a location manager I want to re-run the AI on a case that escalated because the AI was unavailable so that it is handled without manual rework.
- Acceptance criteria:
  - Given a case escalated for "AI unavailable" or ProviderFailed, When staff press Re-run, Then the agent runner resumes the case and the result replaces the escalation.
  - Given the button is pressed twice or the sweeper retries, When the run repeats, Then no duplicate proposal, reply or payout is created (idempotent).
  - Given providers recover, When the sweeper runs, Then eligible cases are retried automatically.
  - Given a case escalated for another reason, When viewed, Then no Re-run button.
- Owner agent: Sonnet builder (lane C). Dependencies: none.
- DoD notes: safety review no; eval run after the change (AI path); browser walkthrough yes.

#### S7.5 Staff categorise and propose (8 SP)
- User story: As a location manager I want to set the category of an uncategorised escalated case and choose a remedy within the rule so that the customer gets a fair outcome.
- Acceptance criteria:
  - Given an uncategorised escalated case in my scope, When I set a category, Then it is stored and audited.
  - Given a category, When I pick a remedy within the rule limits, Then a proposal is created through create_proposal and goes through the same code checks, approval and executor path as AI proposals.
  - Given a remedy outside the rule limits, When I submit, Then it is rejected by code with a plain reason.
  - Given approval, When executed, Then the payout is single and verified, with a stable idempotency key.
  - Given a case outside my scope or another tenant, Then 404.
- Owner agent: Sonnet builder (lane A). Dependencies: S7.2.
- DoD notes: safety review YES (money, approvals); browser walkthrough yes.

#### S7.6 Templated staff replies and close-with-reason (5 SP)
- User story: As a location manager I want to send a templated reply (with optional free text) and close a case with a reason so that the customer is told the outcome and the case is not left open.
- Acceptance criteria:
  - Given an open case in my scope, When I pick a template, Then the reply is sent in the case language and shown in the customer timeline.
  - Given optional free text, When added, Then it is labelled "from our team" and states no unverified facts.
  - Given close reasons (resolved, no remedy, duplicate, unreachable), When I close, Then the reason is stored, a customer message is added where applicable, and both are audited.
  - Given a closed case, When I try to close or reply again, Then it is refused.
- Owner agent: Sonnet builder (lane A). Dependencies: S7.5 (shared staff actions), S7.12 for language (falls back to English).
- DoD notes: safety review YES (customer text); browser walkthrough yes.

#### S7.7 Clear up O0005779 (1 SP)
- User story: As the owner I want the stuck case O0005779 resolved so that the demo data has no dead-end case.
- Acceptance criteria:
  - Given O0005779 is escalated for an AI failure, When Re-run (S7.4) is used, Then the case reaches a proposal or reply and is no longer a dead end.
  - Given the result, When viewed in the UI, Then the state is shown correctly.
- Owner agent: main session. Dependencies: S7.4.
- DoD notes: safety review no; walkthrough yes.

#### S7.8 Size vouchers to the order (3 SP)
- User story: As a customer I want a voucher no larger than my order so that the offer is fair and believable.
- Acceptance criteria:
  - Given a voucher remedy, When computed, Then value = min(cap, voucher_percent of the affected item or order, order total) in integer paise.
  - Given a Rs 149 order and a Rs 150 cap, When a voucher is offered, Then it is at most Rs 149 (test).
  - Given the new pack setting voucher_percent, When absent in a tenant, Then a safe default applies and the settings resolver is used (no tenant branches).
- Owner agent: Sonnet builder (lane B). Dependencies: none.
- DoD notes: safety review YES (money); eval run after the change (existing sr-quality-002 style cases).

#### S7.9 Customer chooses voucher or refund where the rule allows (5 SP)
- User story: As a customer I want to choose between a voucher and a refund when the rule offers both so that I get the remedy that suits me.
- Acceptance criteria:
  - Given pack remedies with options (e.g. food_quality: voucher or refund_percent 50), When the customer reports, Then the options are shown on the report form or case page.
  - Given a choice, When submitted, Then code enforces the limits and the chosen remedy goes into the proposal.
  - Given a category with a single remedy, When shown, Then no choice is offered.
  - Given an option outside the pack, When submitted, Then rejected; ownership checked server-side.
- Owner agent: Sonnet builder (lane B). Dependencies: S7.8.
- DoD notes: safety review YES (money, customer text); browser walkthrough yes.

#### S7.10 Approver switches the remedy within limits (5 SP)
- User story: As an approver I want to switch the proposed remedy (for example voucher to refund) within the allowed limits so that I can settle the case fairly without re-running it.
- Acceptance criteria:
  - Given a pending proposal, When the approver switches to an allowed remedy, Then the old proposal is superseded and a new one is created with a new payload hash.
  - Given an approval bound to the old hash, When the switch happens, Then the old approval cannot execute the new proposal.
  - Given a remedy above the approver's or the rule's limit, When attempted, Then rejected.
  - Given the switch, Then it is audited with who and why.
- Owner agent: Sonnet builder (lane B). Dependencies: S7.9.
- DoD notes: safety review YES (approvals, money); browser walkthrough yes.

#### S7.11 Fair-use shown as a warning (1 SP)
- User story: As a manager I want repeat-claim signals shown as a clear warning so that I understand a person must decide, not that something failed.
- Acceptance criteria:
  - Given a customer with N claims in 30 days over the threshold, When the case is shown, Then the label reads "Repeat claimant: N in 30 days, needs a person" in warning style.
  - Given no breach, When shown, Then no label.
  - Red "failed" wording no longer appears for fair use.
- Owner agent: Sonnet builder (lane B). Dependencies: none.
- DoD notes: safety review no; web test and walkthrough yes.

#### S7.12 Detect the customer's language from their message (5 SP)
- User story: As a customer I want replies in the language I wrote in so that I never have to find a language setting.
- Acceptance criteria:
  - Given a message in Devanagari, When classified, Then the case language is hi.
  - Given Roman Hindi, When classified, Then the case language is hi-Latn (classifier language field, with heuristic fallback if the LLM is unavailable).
  - Given English, Then en. The language is stored in cases.language (migration) and all templates for that case follow it.
  - Given the Help language picker, Then it is removed; preferred_language is used only as a fallback when a message gives no signal.
  - Given eval scenarios per language, When the eval runs, Then each language is detected correctly.
- Owner agent: Sonnet builder (lane C), with business-analyst input on detection approaches. Dependencies: none.
- DoD notes: safety review YES (customer text, migration); eval run YES; no new dependency.

#### S7.D1 Design system in Claude Design (5 SP)
- User story: As the owner I want a coherent design system so that every page of the revamped UI looks and behaves consistently.
- Acceptance criteria:
  - Given Claude Design, When the system is delivered, Then it defines colours, typography scale, spacing, and components (tables, cards, charts, forms, status chips).
  - Given both themes, Then light and dark are defined; Devanagari text renders correctly.
  - Given the chaicode skill, When the owner has installed it and the files have been read, Then it is used where relevant.
  - The result is shown to the owner.
- Owner agent: main session (Claude Design / DesignSync tooling). Dependencies: owner installs the chaicode skill (not blocking the start).
- DoD notes: safety review no; no app code changes; owner approval is the exit gate.

#### S7.D2 Wireframes for every page and role (8 SP)
- User story: As the owner I want wireframes for every page and role so that I can approve the UI before any build starts.
- Acceptance criteria:
  - Given customer pages, Then wireframes exist for orders, report, case, policies, privacy.
  - Given staff pages, Then wireframes exist for queue, case workspace, approvals, insights, growth, marketing.
  - Given the platform portal, Then wireframes exist for health, jobs, logs, alerts, AI performance, scenario lab.
  - Given each persona, Then a UX flow is documented.
  - The owner's approval (or requested changes) is recorded here; until approved, no UI build starts.
- Owner agent: main session (Claude Design). Dependencies: S7.D1.
- DoD notes: safety review no; gate for S8.7.

### Planned SP summary
| Group | Stories | SP |
| --- | --- | --- |
| E12 staff handling | S7.1-S7.7 | 28 |
| E13 fair remedies | S7.8-S7.11 | 14 |
| E14 language | S7.12 | 5 |
| E19 design | S7.D1, S7.D2 | 13 |
| Total | 14 stories | 60 (capacity ~40; see flag) |

## Daily Scrum (2026-10-28, opening, before any Sprint 7 build work)

Baseline: branch test, main merged at cf6a861; Sprint 6 closed (b3d42e8); latest commit 891f427 (CORS allows PUT). No Sprint 7 commits yet.

| Participant | Done (evidence) | Next | Blocked |
| --- | --- | --- | --- |
| Opus coordinator (main session) | Approved plan written (C:\Users\user\.claude\plans\there-are-some-setup-jaunty-platypus.md); process update commissioned. No Sprint 7 commits yet | Start design track (S7.D1/S7.D2) in Claude Design; assign builders to lanes A/B/C; merge one at a time | none |
| scrum-master | This planning: .claude/agents/scrum-master.md Scrum events, docs/EPICS.md (agreement + E12-E19), docs/ROADMAP.md, this file | Track SP and dependencies; next stand-up after the first merge batch | none |
| business-analyst | no activity this sprint yet | Language-detection approaches for S7.12 (feeds lane C) | none |
| Sonnet builders (to be assigned: lanes A, B, C) | no activity | Lane A: S7.1 then S7.2; lane B: S7.8; lane C: S7.4 and S7.12, each in a worktree on a DB-isolated branch (at most 2 heavy processes) | none |
| safety-reviewer | no activity | Review S7.2, S7.5, S7.6, S7.8, S7.9, S7.10, S7.12 before each merge | none |
| test-runner | no activity | Targeted tests per merged story; one full suite and a chaos run at sprint close | none |
| eval-runner | no activity | Eval run after S7.4, S7.8, S7.12 | none |
| Owner (human) | Approved the v2 roadmap | Review designs when ready (approval gate for UI build); run `npx skills add https://ui.chaicode.com -a claude-code`; E0.3 rotate Neon owner password; E7.2 copy .env into the clean clone; confirm provisional decisions (365-day retention floor; privacy contact label and 30-day target vs 90-day ceiling; support needs no consent record; Hinglish/Devanagari native review; GST/accounting retention for order references) | Waiting on the owner: design approval (later), skill install |

## Daily Scrum 2026-10-28 (after first merge batch)

Verified against git: test head 5025c9f (S7.12 merged locally, not pushed), S7.1 merged at 1c46a1f. Branch heads: S7.8 bf09f2e, S7.2/S7.3 b8038ab, UI-foundation 1d10ddd, UI-pages 7d6853b. Test counts below are coordinator-reported, not re-run by the scrum-master.

| Participant | Done (evidence) | Next | Blocked |
| --- | --- | --- | --- |
| Opus coordinator (main session) | S7.1 merged 1c46a1f (pushed); S7.12 merged 5025c9f (local only); research docs fecf31c (S8.4), ab98d85 (S11.1) pushed | Push test with S7.12 once merged-head test_cases_api + test_case_reply_api pass; merge S7.8, then S7.2/S7.3 one at a time; hold UI merge | Shared Sonnet usage limit hit once overnight (resumed) |
| Builder S7.1 (lane A) | 1c46a1f merged; follow-up tests 53 passed/1 skipped, vitest 85 (2793237) | Browser walkthrough evidence for the case page | none |
| Builder S7.12 (lane C) | 4197f75 six review fixes; unit 447 passed, language/agent 131 passed | Eval run per language (required by DoD); merged-head API tests in progress | none |
| Builder S7.8 + S7.11 (lane B) | bf09f2e; KeyError on old seeded packs fixed; 637 passed/7 skipped/2 failed, then the 2 fixed (35 passed) | Rebase on test, merge, re-run targeted tests; eval run (DoD); web test/walkthrough for the S7.11 label | none |
| Builder S7.2 + S7.3 (lane A) | b8038ab rebased onto test; migration 0021 after 0020; 6 review fixes; 78 passed/2 skipped on a stub 0020 | Re-run on the real migration chain, then merge | Evidence is on a stub 0020 only |
| Builder UI (ChaiUI) | 1d10ddd foundation, 7d6853b 10 pages, System/Light/Dark, 87 vitest, build ok, desktop browser-checked | Restyle CasePage, ApprovalDetail, Help, Queue, then merge | Owner question: highlight capitalize vs sentence case |
| safety-reviewer | S7.1 no blockers; S7.12 no blockers (6 fixes); S7.8 KeyError found and fixed; S7.2/S7.3 no blockers (6 fixes) | Review S7.5, S7.6, S7.9, S7.10 as they land | none |
| business-analyst | S8.4 privacy (fecf31c), S11.1 HQ marketing (ab98d85) committed and pushed | No Sprint 7 task queued | Open owner questions listed in those docs |
| test-runner / eval-runner | Targeted runs reported above; no eval output yet this sprint | Merged-head runs per merge; evals after S7.8, S7.12 (and S7.4) | Neon free-tier flakiness |
| scrum-master | This stand-up; EPICS.md S7.1 and S7.12 set to [~] with evidence | Review and ticks at close | none |
| Owner (human) | Roadmap v2 approved | Answer highlight-case question; E0.3 rotate Neon owner password; E7.2 copy .env to clean clone; install chaicode skill; confirm provisional decisions; open questions in S8.4/S11.1 docs | Human-only items: E0.3, E7.2 |

### Burndown
- Planned 60 SP (47 code + 13 design), capacity about 40. Ticked (done) SP: 0.
- Merged on test, awaiting last evidence: S7.1 (3, walkthrough), S7.12 (5, eval run + merged-head tests) = 8 SP.
- Built, on branch, not merged: S7.8 (3), S7.11 (1), S7.2 (5), S7.3 (3) = 12 SP.
- Not started: S7.4 (3), S7.5 (8), S7.6 (5), S7.7 (1), S7.9 (5), S7.10 (5) = 27 SP; design S7.D1/S7.D2 13 SP (no evidence of progress in git).
- Sprint ends 2026-10-29, so about half the time is left with 0 SP ticked.

### Risks (at risk: not yet [~] with more than 25% time gone)
- AT RISK: S7.4, S7.5, S7.6, S7.7, S7.9, S7.10 (not started), S7.D1/S7.D2 (no repo evidence).
- S7.2/S7.3 only tested on a stub 0020; migration order clash is possible.
- UI merge is large and held; mixing it with story merges raises conflict risk.
- Evals not yet run for S7.8 and S7.12 though the DoD requires them.
- Sonnet usage limit and Neon flakiness can stall the 2-heavy-process budget.

### Today's plan (in order)
1. Push S7.12 after merged-head test_cases_api + test_case_reply_api pass; run its language evals.
2. Merge S7.8 (+S7.11), then S7.2/S7.3 on the real migration chain; targeted tests after each merge.
3. Restyle the 4 remaining pages (Case, ApprovalDetail, Help, Queue), then merge UI.
4. Build S7.4 -> S7.7, then S7.6 (needs S7.5, so S7.5 first), S7.5, S7.9, S7.10 as capacity allows. Note S7.6 depends on S7.5, so the real order is S7.4, S7.7, S7.5, S7.6, S7.9, S7.10.
5. If capacity runs out, carry over in the agreed order: S7.10, S7.9, S7.7, S7.11 (points unchanged). With 47 SP of code against about 40 capacity, S7.10 and S7.9 (10 SP) are the likely carry-over. S7.5 + S7.6 (13 SP) stay in only if lane A is free after S7.3.
6. Sprint Review + Retro with the scorecard; tick only verified stories.
7. Merge test to main only when the full suite is green.

Ticks today: none. S7.1 meets its code criteria on test but lacks browser walkthrough evidence, so it stays [~].
