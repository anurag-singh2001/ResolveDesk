# Sprint 9

## Sprint Planning (2026-10-31)

**Sprint goal:** Platform portal backbone: the owner can see health, jobs, logs, alerts and AI performance across the platform without touching customer data.
**Dates:** TBD (2 days). Do NOT start Sprint 9 until every Sprint 8 story is merged and the Sprint 8 Review has run. At planning time (head ef4dbb8) merged: S8.1, S8.2, S8.3, S8.5a, S8.6, S7.9, S7.5, UI revamp merge. Not yet merged or unverified: S8.5b, S8.5d, S8.5c (stretch), S8.7 walkthrough. Any Sprint 8 carry-over is added on top of this plan with its points unchanged and pushes lowest-priority Sprint 9 items out (see Capacity).
**Source:** docs/ROADMAP.md (E17), docs/EPICS.md (E17, S8.5e, story template, DoD), docs/sprints/sprint-7.md (Owner decisions pending), docs/sprints/sprint-8.md, docs/research/privacy-page-needs.md (R5).

### Capacity and fit
- Capacity: about 40 SP (2-day sprint, 2-3 parallel builders). Sprint 7 showed building outpaces verification (about 52 SP built, 0 SP closed at first review), so the committed number is held at capacity and verification time is planned in.
- Pulled: 39 SP = S9.1 (8) + S9.2 (5) + S9.3 (5) + S9.4 (5) + S9.5 (8) + S8.5e (8).
- Core (committed): S9.1-S9.5 = 31 SP, matching the ROADMAP row. S8.5e (8 SP) is "if capacity allows": it is independent of the portal, so it runs in its own lane and is the first item to drop or slip if Sprint 8 carry-over arrives. Never drop tests or safety review.
- No story is above 8 SP; no split needed. S8.5e and S9.1 and S9.5 are each at the 8 SP ceiling: if any builder reports mid-sprint that it is larger, split it then (S9.1 into login and views; S9.5 into shell + health/jobs, then logs/alerts/AI; S8.5e into queue read + dry run, then approval + sweeper).
- Heavy processes: at most 2 at once. Machine memory is low (see Constraints).

### Constraints
- Machine memory is low: each builder runs at most ONE pytest process at a time, targeted files only. No full suite in builders; the full suite, evals and chaos run only on the merged head via test-runner / eval-runner, at most 2 heavy processes at once.
- No new dependencies (Python or npm) without owner approval. Scheduler is a plain asyncio loop (already agreed in ROADMAP). Charts: Recharts is approved but is used from S10.3; S9.5 uses tables and plain ChaiUI components unless the owner says otherwise.
- S9.5 follows the ChaiUI rules: read the installed ChaiUI skill files first, use the existing components and theme tokens (light, dark, System), sentence case, Devanagari-safe, 375px width. No bespoke styling outside the design system.
- Migrations continue from 0028 (0027 is the last Sprint 8 slot; repo head at planning is 0025, so confirm the real head on the merged Sprint 8 test branch and renumber if it differs). Reserve numbers now so parallel builders do not collide: 0028 = S9.1, 0029 = S9.2, 0030 = S9.4, 0031 = S8.5e (if it needs a table or column). S9.3 should need no migration (uses job_runs from 0029); if it does, use 0032. Each migration is applied with the owner role via MIGRATION_DATABASE_URL; each builder uses its own scratch database.
- Builders work in worktrees on DB-isolated branches; merge one story at a time; targeted tests on the merged head after each merge.

### Stories

#### S9.1 Platform-admin login and aggregate-only cross-tenant path (8 SP)
- User story: As the platform owner I want to sign in as a platform admin and read cross-tenant health and usage numbers so that I can run the platform without ever seeing a customer's records.
- Acceptance criteria:
  - Given PLATFORM_ADMIN credentials set in the environment (never in the database or repo), When the owner signs in at the platform login, Then a token with a separate `platform_admin` principal is issued; it carries no tenant_id and is rejected by every tenant route.
  - Given a customer, staff or approver token, When they call a platform route, Then 403 (or 404 where existence should not leak); given a platform token, When it calls a tenant route, Then it is rejected.
  - Given the dedicated DB role (new, NOBYPASSRLS, no direct table grants), When it queries, Then it can SELECT only from named SECURITY DEFINER aggregate views (counts, sums, rates, latencies by tenant slug and day); a direct SELECT on any base table fails (test).
  - Given the aggregate views, When their columns are scanned in a test, Then none returns customer names, phones, addresses, message text, case text, order lines or any row-level customer id; small-count suppression is not required but no per-customer grouping exists.
  - Given the platform principal acts, When it reads, Then an audit event is written (actor, route, no personal content).
  - Given tests run, Then they run against both tenants through the same code and never name a tenant; the isolation suite gains platform-role tests.
- Owner agent: Sonnet builder (lane A). Dependencies: none (first in order). The views for llm_usage/job_runs/logs/alerts are added by S9.2/S9.4 in their own migrations, each as a SECURITY DEFINER aggregate view granted to the platform role; S9.1 ships the role, the principal, the first views (tenants, cases by state counts, approvals counts, sweeper last run) and the pattern.
- Safety review: YES (tenancy, RLS, migrations, new DB role, new principal). Migration 0028.
- DoD: common DoD; no browser walkthrough (API only; UI is S9.5); RUNBOOK and DECISIONS entries for the platform role and env credentials.

#### S9.2 Persist LLM usage and job runs (5 SP)
- User story: As the platform owner I want every model call and every background job run recorded so that I can see cost, speed, failures and AI performance per tenant.
- Acceptance criteria:
  - Given any LLM call through the provider factory, When it finishes or fails, Then one `llm_usage` row records tenant_id (nullable for platform-level calls), provider, model, purpose (classifier, drafting, embeddings, etc.), input/output tokens, cost in integer paise (or micro-units as integers, no floats), latency ms, outcome (ok, error, fallback_used), error class (no prompt or response text).
  - Given a job (sweep, retention dry run, growth nightly, pack refresh, eval, chaos), When it starts and ends, Then a `job_runs` row records job name, tenant (nullable), started/finished, status (running, ok, failed, skipped), counts, and an error summary without personal content.
  - Given the new tables, When inspected, Then tenant_id is present, RLS is on for tenant-scoped reads, and the runtime role can insert but staff routes cannot read them.
  - Given recording fails (DB error), When an LLM call is made, Then the customer-facing flow is unaffected (recording is best effort, logged) and no network call happens inside an open DB transaction (hard rule 5).
  - Given two tenants make calls, When aggregate views are read by the platform role, Then totals by tenant slug and day are correct and contain no prompt text.
  - Given tests run, Then both tenants pass without naming a tenant.
- Owner agent: Sonnet builder (lane B). Dependencies: S9.1 role and view pattern for the aggregate views (builder can write tables and recording first and add the views once S9.1 merges, or branch from S9.1's migration).
- Safety review: YES (migration, tenant tables, RLS). Migration 0029.
- DoD: common DoD; RUNBOOK and DECISIONS (cost unit, no prompt text stored).

#### S9.3 Job scheduler inside the app (5 SP)
- User story: As the platform owner I want the recurring jobs to run on their own inside the app, with safe toggles, so that sweeps, retention checks, growth runs and pack refreshes happen without me starting them.
- Acceptance criteria:
  - Given the app starts with the scheduler enabled, When intervals elapse, Then a plain asyncio loop runs the sweeper, retention dry run, growth nightly and pack refresh on settings-driven intervals and records a `job_runs` row for each.
  - Given a dev or test environment, When no override is set, Then the scheduler is OFF by default and can be toggled per job via settings; tests never start background loops implicitly.
  - Given a job is still running, When its next tick arrives, Then it is skipped and recorded as skipped (no overlap); given a job raises, When it fails, Then the loop continues and the failure is recorded.
  - Given more than one app process, When both start, Then a database advisory lock or lease row ensures one runs each job at a time (no double sweep, no double growth send).
  - Given retention runs, When the scheduler triggers it, Then it is dry run only unless an explicit setting enables deletion (unchanged safety stance).
  - Given the app shuts down, When the loop is cancelled, Then in-flight jobs end cleanly and are marked failed or skipped, not left "running" forever.
  - Given a fake clock, When tests advance time, Then job due-times are computed deterministically (no real sleeps).
- Owner agent: Sonnet builder (lane B, after S9.2). Dependencies: S9.2 (job_runs). No new dependency; no migration expected.
- Safety review: no (no money, tenancy or customer text change), but the builder must confirm growth sends still go through approvals and consent checks unchanged; escalate to safety review if the diff touches them.
- DoD: common DoD; RUNBOOK (how to enable, toggles, what each job does).

#### S9.4 Logs and alerts (5 SP)
- User story: As the platform owner I want errors logged in one place and rules that raise alerts so that I find out about problems before customers do.
- Acceptance criteria:
  - Given an unhandled error in a route, job or provider call, When it occurs, Then a structured `error_log` row records time, tenant (nullable), source, error class, short message, request id; messages are scrubbed so no customer text, phone, name or token is stored (test with seeded PII strings).
  - Given rule-based alerts, When rules are evaluated (by the scheduler or on request), Then an `alerts` row opens for: job failed, provider failure rate above threshold, escalation spike versus trailing average, eval regression, stuck sweeper or chaos run; thresholds come from settings.
  - Given the same alert condition persists, When rules run again, Then the existing alert is updated, not duplicated; given it clears, When rules run, Then it is marked resolved with a timestamp.
  - Given the platform admin acknowledges an alert, When they act, Then acknowledgement is audited; tenant staff cannot read or change alerts.
  - Given the platform role, When reading logs and alerts, Then it does so only through aggregate or scrubbed views (S9.1 pattern).
  - Given fake data for each condition, When tests run, Then each rule fires and clears as specified, on both tenants.
- Owner agent: Sonnet builder (lane B or A after S9.1, whichever frees first). Dependencies: S9.2 (llm_usage, job_runs feed the rules), S9.1 (role and views); S9.3 helpful for scheduled evaluation but not required (rules can also run on request).
- Safety review: YES (migration; logs must not leak customer text). Migration 0030.
- DoD: common DoD; RUNBOOK (alert list and thresholds), DECISIONS (scrubbing approach).

#### S9.5 Portal UI (8 SP)
- User story: As the platform owner I want a portal with health, jobs, logs, alerts and AI performance pages so that I can see the state of the whole platform in one place.
- Acceptance criteria:
  - Given a platform token, When the owner opens the portal, Then they see Health (service and DB status, last sweep, tenants and counts), Jobs (recent runs, status, duration, skipped/failed), Logs (scrubbed error log, filter by source and time), Alerts (open and resolved, acknowledge) and AI performance (calls, tokens, cost, latency, failure and fallback rate by provider and tenant slug, per day).
  - Given a non-platform user, When they open any portal route, Then they are redirected or shown not-found; the Demo controls link to the portal now works instead of the placeholder.
  - Given the portal shows data, When scanned, Then no customer name, phone, address or message text is rendered anywhere.
  - Given the pages, When built, Then they follow the ChaiUI rules: existing components and tokens, light/dark/System themes, sentence case, empty, loading and error states, keyboard focus, 375px width.
  - Given the web tests, When run, Then component tests cover each page and the role redirect (existing web tests still pass; at most one web test process at a time).
  - Given the finished UI, When walked through in a browser, Then each page on desktop and 375px in light and dark is recorded with screenshots in this file.
- Owner agent: Sonnet builder (UI, lane A after S9.1; main session reviews the walkthrough). Dependencies: S9.1, S9.2; S9.3 and S9.4 endpoints for Jobs, Logs, Alerts (build Health, AI performance and the shell first; add Jobs/Logs/Alerts as their APIs merge). Approval gate: owner direction on the ChaiUI revamp recorded 2026-10-28; confirm the portal screens are covered by the approved wireframes, otherwise reuse existing page patterns and show the owner screenshots before merge.
- Safety review: no for the UI itself (confirm in the diff that it adds no server code and no new data access); the endpoints it reads are covered by S9.1/S9.2/S9.4 reviews.
- DoD: common DoD; browser walkthrough is core; README and RUNBOOK portal section.

#### S8.5e Owner privacy request queue with deadlines and audit (R5) (8 SP) - if capacity allows
- User story: As an HQ owner I want a queue of privacy requests with due dates and an audit trail so that I answer every request in time and approve each erasure knowingly.
- Acceptance criteria:
  - Given a staff user with the HQ/owner role, When they open the queue, Then it lists their tenant's privacy requests (erasure; access and correction as types) with type, state, received date, internal due date (tenant setting `privacy_request_target_days`, default 30), days left, and the legal ceiling shown separately.
  - Given a pending erasure request, When the approver opens it, Then a dry run shows what will be removed, what is kept and why, and what is deferred (open case or refund) before they decide.
  - Given the approver approves, When the decision is stored, Then the approval is bound to the request payload hash and expires (hard rule 6); a changed payload or an expired approval cannot execute; the agent has no write tool; only the executor erases, and only after approval.
  - Given a role without permission (customer, support agent, other tenant's HQ), When they open or act on a request, Then 403 or 404 (other-tenant records are 404).
  - Given the sweeper runs with the fake clock, When a request is near due or overdue, Then it is flagged in the queue and an audit event is written once per transition.
  - Given any state change (received, in progress, approved, rejected, executed, deferred, cancelled), When it happens, Then an audit event records actor and request id with no personal content; the customer's status view (S8.5d) reflects the new state, and "done" appears only after the executor succeeded.
  - Given an existing owner-side view (research open question 1), When planning is confirmed, Then reuse it; the working assumption is none exists.
  - Given both tenants, When tests run, Then they pass without naming a tenant.
- Owner agent: Sonnet builder (lane C). Dependencies: S8.5d merged (request model, status, executor). Possible migration 0031 (due-date and approval columns if S8.5d did not add them).
- Safety review: YES (approvals, customer data, erasure executor).
- DoD: common DoD; browser walkthrough yes (queue, dry run, approve/reject); RUNBOOK privacy request handling.

### Common Definition of Done (docs/EPICS.md "Working agreement")
Tests added and passing for both tenants (never naming a tenant), `make lint` clean, safety review where marked YES, docs and manuals updated (README, RUNBOOK, SCENARIOS, DECISIONS as relevant), browser walkthrough for UI stories, CI green on the pushed branch.

### Dependency order and lanes (2-3 builders)
1. First wave, in parallel: S9.1 (lane A, creates the platform role/principal and 0028), S9.2 tables and recording (lane B, 0029; add its aggregate views after S9.1 merges), S8.5e (lane C, only after S8.5d merged; independent of the portal chain).
2. Second wave: S9.3 (lane B, after S9.2 merges); S9.5 shell + Health + AI performance pages (lane A, after S9.1 and S9.2 merge, mock-free against the real endpoints).
3. Third wave: S9.4 (lane A or B, whichever frees first; needs S9.1, S9.2; 0030); S9.5 Jobs/Logs/Alerts pages as S9.3/S9.4 merge.
4. Close: portal walkthrough, safety reviews (serialised: S9.1, S9.2, S9.4, S8.5e; ask for S9.1 first and share findings), full suite + evals on the merged head via test-runner / eval-runner, then Review.
- Merge order: S9.1, S9.2, S9.3, S8.5e (any time after its review), S9.4, S9.5. One merge at a time, targeted tests on the merged head.
- Safety reviews are the likely bottleneck (four YES stories). Request each review as soon as a builder reports done, not at the end.

### Sprint 9 points
| Group | Stories | SP |
| --- | --- | --- |
| E17 portal backbone (core) | S9.1 (8), S9.2 (5), S9.3 (5), S9.4 (5), S9.5 (8) | 31 |
| E16 privacy queue (if capacity allows) | S8.5e | 8 |
| Total | 6 stories | 39 (capacity about 40) |
| Carry-over from Sprint 8 | none known at planning; added at start if any | 0 |

### Sprint 7 / 8 open owner decisions that affect Sprint 9
| Decision (source) | Affects | Default used until answered |
| --- | --- | --- |
| Sprint 8 dates and sign-off; Sprint 9 may only start after S8 merged (sprint-7 #8) | Whole sprint | Wait for the Sprint 8 Review; no start before |
| Privacy defaults: 365-day retention floor, contact label, 30-day target vs 90-day ceiling, no consent record for support (sprint-7 #6; sprint-8 Q2, Q3, Q6) | S8.5e due dates and ceiling display; S9.3 retention schedule | 30-day `privacy_request_target_days`, 90-day ceiling shown separately, "Privacy contact" label, 365-day floor, dry run only |
| Is a staff request queue already built? (sprint-8 Q1) | S8.5e scope | Assume not; build it |
| S7.5 defaults: four-eyes on staff-created proposals, no staff auto-approve (sprint-7 #5) | S8.5e approval rules should reuse the same approval engine and four-eyes setting | Both on (recommended) |
| S7.10: four-eyes for switching a remedy (sprint-7 #2) | Approval engine behaviour reused by S8.5e | Follow whatever S7.10 merged |
| Highlight case: capitalize vs sentence case (sprint-7 #1; sprint-8 UI) | S9.5 styling | Sentence case |
| Design approval for portal screens (S7.D2 covers app pages; portal screens not confirmed) | S9.5 start | Use ChaiUI patterns; owner reviews screenshots before merge |
| Campaign dual approval (sprint-7 #7) | Sprint 11, not Sprint 9; growth nightly in S9.3 sends nothing new | Not needed this sprint |
| "What we do not keep" claims (sprint-8 Q4) | None for Sprint 9 | Hidden until the owner confirms |
| Platform admin credentials: who sets PLATFORM_ADMIN_* in .env and the Render/host secrets | S9.1 | New human-only item: owner sets a strong password in .env (never committed) |
| Hosting/scheduler: confirm the single-process in-app scheduler is acceptable on the free tier (sleeping instances skip jobs) | S9.3 | Accept; advisory-lock lease covers multiple instances; note the limitation in RUNBOOK |
| Human-only items still open: E0.3 rotate Neon owner password (matters more once a new DB role is created), E7.2 copy .env to the clean clone, Hinglish/Devanagari native review (sprint-7 #9) | S9.1 role creation uses the owner credential | Owner to do E0.3 before or at S9.1 merge |

### Risks
- Sprint 8 carry-over (S8.5b, S8.5d, S8.5c, S8.7 walkthrough) lands on top: S8.5e depends on S8.5d, so it slips first, then S9.4/S9.5 detail pages; S9.1 and S9.2 are never dropped.
- New DB role and SECURITY DEFINER views are the most security-sensitive change of the sprint: owner-defined search_path and explicit grants required; safety review serialises behind S9.1.
- Low machine memory plus Neon flakiness: one pytest per builder, no full suite in builders, heavy runs only on the merged head.
- Verification (walkthroughs, safety reviews) was the Sprint 7 bottleneck; plan Review time, do not treat build completion as done.
- Migration number collisions between parallel lanes: use the reserved numbers above and rebase before merging.

## Sprint Review (2026-11-01, provisional: the sprint was built inside the Sprint 8 integration)

Evidence base (2026-11-01, from the coordinator, not re-run by the scrum-master): full suite on 2f84f23 (holds all Sprint 7-9 code) 2408 passed, 34 skipped, 2 failed in 4h05; both failures were tests/integration/test_history_db.py::test_reload_with_same_seed_is_identical (test-order problem), fixed in 2ebcb06, 3 passed on rerun. A final full run on 2ebcb06 is PENDING. Eval evals/reports/eval-20261031-202218.md: agents BrewCo 92%, Spice Route 93%, 0 over rule, 0 errors, injections held; bc-wrong-002 and sr-quality-002 escalated rather than proposed. Browser walkthrough on the demo DB (migrated 0027 to 0034): no console errors on both HQ pages, franchisee (own 2 outlets only), location manager, customer, Approvals, Cases to handle, Policies, Privacy, Demo controls, platform portal; 375px overflow check on 8 pages; light and dark on the dashboard. `make lint` and CI were not re-run by the scrum-master; both stay on the final-run checklist.

Sprint 9 stories were built and merged in integ/s8b (21d1255 S9.1+S9.2, d15bc6a and 395e52c S9.3, ad30d60 S9.4, 1323123 S9.5, 1a92b26 S8.5e). Portal pages walked: sign-in, Health, Jobs, Logs and alerts, AI performance, Scenario lab. Jobs, alerts, logs and AI usage have NO rows on the demo DB, so only empty states were seen.

| Story (SP) | Verdict | Evidence / what is missing |
| --- | --- | --- |
| S9.1 (8) | open | 21d1255, review-fix commits; no filed safety report in the sprint notes; sign-in seen |
| S9.2 (5) | open | 21d1255; no filed safety report; AI usage view empty |
| S9.3 (5) | open | d15bc6a, 395e52c, migration 0032; done-when includes pack refresh but DECISIONS rejected scheduling it (mismatch, owner to resolve); Jobs page empty and omits platform_job_runs (known gap below) |
| S9.4 (5) | open | 00088cc, ea9e87c, ad30d60 (0033); no filed safety report; logs and alerts only empty state |
| S9.5 (8) | open | 98828b5, a346e28, 514263e (0034); walkthrough saw empty states only, no populated views |
| S8.5e (8) | open | see sprint-8 |

Honest note on safety: the sprint notes lack filed reports for S9.1, S9.2, S9.4 and S8.5e; only "review fixes" commits exist (ea9e87c, af55b9b, 395e52c), which suggests reviews happened but the reports are not recorded. Not counted as safety clean until filed.

Velocity: planned 39 SP, done (ticked) 0 SP. Merged code 39 SP.

Owner questions: (1) pack refresh in the scheduler: keep it rejected and amend the S9.3 done-when, or build it? (2) file or re-run the safety reviews for S9.1, S9.2, S9.4, S8.5e. (3) add platform_job_runs to the portal Jobs page. (4) seed some rows or run a job so populated views can be walked.

## Sprint Retro (2026-11-01)

Went well: the aggregate-only platform path and the portal were built and merged with migrations 0032-0034, and the portal opens without console errors.

Hurt: safety reports not filed; empty demo data hid populated-view issues (the Jobs page already misses platform_job_runs); verification lag again.

Action: every safety review ends with a pasted report in the sprint file before merge; seed demo job and usage rows before a portal walkthrough.

Previous retro actions (Sprint 8: separate eval DB, time-based hang limit): the final eval ran cleanly (eval-20261031-202218); otherwise not evidenced.


### Known gaps
- 2026-11-01: the portal Jobs page omits `platform_job_runs`, so platform-level job runs are not shown there. Logged by the owner; not yet scheduled.

### Safety reports filed 2026-11-01
Static read of the code and migration text by safety-reviewer; no tests run, grants not checked on a live database.

| Story | Verdict | Non-blockers |
|---|---|---|
| S9.1 platform admin | Clean | Failed logins are logged, not audited; lockout is per process and five bad guesses lock the admin out for 15 minutes; REVOKE ALL covers tables existing at migration time only, and whether a test guards later tables was not checked; audit and read share a transaction, so a failed view query loses the audit row |
| S9.2 LLM usage | Clean | `error_class` and `model` are length-capped but not pattern-checked |
| S9.4 logs and alerts | Clean | Tables are not revoked from `resolvedesk_maint` (views are); `log_error_count` and `alerts_apply` are executable by the app role; failed log writes drop that interval's counts |
| S8.5e privacy queue | Clean | A refused approval is logged, not audited; the token can be replayed for 30 minutes by the same approver (erasure is idempotent and re-checks the hash); the GET dry run writes an audit row and mints a token |

These are non-blockers, logged here and not scheduled.

### Growth flag on for spice_route (2026-11-01)
Owner decision: `growth: true` in the tenant file. Tests with the flag on: test_growth 30 passed, brand signals 19 passed, tenant loader 10 passed. Known gap: that tenant's simulation plants no repeat-rate drop and has no third staff user at its location, so its end-to-end campaign flow and 7 campaign tests skip. Its campaign flow is therefore not exercised by a test.
