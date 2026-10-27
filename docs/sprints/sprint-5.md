# Sprint 5 · Privacy basics and growth hardening

Status: CLOSED 2026-10-27 (built overnight, pushed at 1d917f8). S5.3 carried as [~] (chaos x3 on the final head not run).

## Planning (draft, 2026-10-27)
Goal: close the biggest "needed before real customer data" gaps (DPDP), harden the new growth path under failure, and polish staff screens.

Sources: README "Limits"; docs/research/market.md (R9 deletion workflow left as stretch; grievance-officer display from F12; Q6 verify legal items against official text); open items in docs/EPICS.md (E0.3 and E7.2 are human-only; follow-ups demo seed refreshing packs and dev-panel reseed are not in this sprint).

| # | Story | Owner | Est | Research first? | Done-when |
| --- | --- | --- | --- | --- | --- |
| S5.1 | DPDP: retention setting plus purge job for case messages | Sonnet builder, main reviews | M | yes (business-analyst: retention norms, what DPDP requires, checked against official text) | per-tenant `message_retention_days` setting; job redacts or deletes older messages with an audit row; tests for both tenants; safety review clean |
| S5.2 | DPDP: consent records plus customer access/erasure request flow | Sonnet builder, main reviews | L | yes (same pass as S5.1) | consent stored per customer with timestamp; customer files an access or erasure request, HQ owner works it, outcome audited; erasure keeps money records (paise amounts) and redacts PII; isolation tests + safety review clean |
| S5.3 | Growth chaos test: campaign sends under messaging chaos | Sonnet builder | M | no | with messaging failures and timeouts injected, zero duplicate sends and consent re-checked at send; included in `make test-chaos`, green x3 |
| S5.4 | Approvals-queue filter and sort (status, amount, age, location) | Sonnet builder | S | no | server-side, tenant-scoped query params; web tests cover each filter/sort; `make web-test` green |
| S5.5 | Grievance-officer display and acknowledge/resolve SLA marker (market.md F12, R5) | Sonnet builder | S | maybe (confirm wording against official rules text) | officer name/contact is a tenant setting shown on the customer portal; overdue marker (48 h acknowledge, 1 month resolve) visible to staff; tests for both tenants |
| S5.6 | Hindi templates for customer-facing messages | Sonnet builder | M | yes (which strings, language per customer vs per tenant) | needed-info and status templates have `hi` variants chosen by a customer language field; verifier still checks facts in either language; English fallback; tests for both tenants |

Not a story, 30 minutes: check that the Insights and Growth sections already in docs/manual/{hq_owner,franchisee_owner,location_manager}.md match the screens during the sprint walkthrough.

Order by value: S5.1, S5.2 (README says they are needed before real data), S5.3 (safety), S5.5, S5.4, S5.6.
Drop first if short: S5.6, then S5.4. Never drop tests or safety review (S5.1, S5.2, S5.3 touch retention, PII and idempotent sends).

Does not fit: S5.1 + S5.2 are close to a full sprint on their own. If the research pass is slow, start S5.3-S5.5 in parallel, with at most 2 heavy processes at once (Sprint 4 retro).

Carried human-only: E0.3 (rotate Neon owner password), E7.2 (copy .env into the clean clone and see an AI proposal).

Entry rule: Sprint 4 closed (final full suite and chaos green, test to main confirmed).

## Stand-ups
(none written; work ran overnight, state recorded in EPICS.md E10)

## Review (2026-10-27)
Six stories built by Sonnet builders, each safety-reviewed, merged to test, pushed at 1d917f8.
- S5.1 ticked: 6e28e19, rework 7616458 (2 HIGH), fixes d3e434e; migration 0017; 52 tests.
- S5.2 ticked: 4524060, rework 6d892a5 (2 MEDIUM), 0c410a7 (deadlock found in re-review); migration 0018; 40 tests. Deadlock safety rests on lock-order reasoning, not a reproducing test.
- S5.3 stays [~]: c9ee4c0, no bug found, passes one chaos run (3 passed, 1 skipped); done-when needs green x3.
- S5.4 ticked: 8ff8434, 6592bd9. S5.5 ticked: 74efee9, 7aa7444. S5.6 ticked: 7e881a6, 4a228cc; migration 0019.
- Research: docs/research/dpdp-and-hindi.md (da590d6).

Final verification on 1d917f8 in 7 sequential batches (memory): unit 411 passed/2 skipped; isolation 206/1 skipped; cases+reply+language+meta 118 passed (b2; the b4 run had transient Neon errors); data rights+retention+privacy 104 passed (b2; the b4 run errored at setup in 42 s, connection); approvals+growth+sweeper 70/2 skipped; refunds+vouchers+resume 116/3 skipped plus 1 transient error that passes alone; agent graph 76. Web 83 passed, ruff clean, single alembic head 0019. No single full-suite run; passes on b2 stand in for the transient b4 failures.

Provisional decisions awaiting the owner (DECISIONS.md, not legal advice): 365-day retention floor; "privacy contact" label, 30-day internal target vs 90-day reported ceiling; support needs no consent record; Hinglish/Devanagari native-speaker review; GST/accounting retention for order references unresearched.

Human-only remaining: E0.3 rotate Neon owner password; E7.2 copy .env into the clean clone; confirm the decisions above.

## Retro
Went well
- Reviewers found real defects in 5 of 6 stories (2 HIGH in S5.1) before merge; each was fixed with rework commits.
- Research first (dpdp-and-hindi.md) gave builders concrete rules; open legal points logged as provisional instead of guessed.

Hurt
- Sonnet usage limit hit about 03:40; two builders paused until reset.
- Memory pressure killed a broad run even with 1 heavy process; verification had to be split into 7 sequential batches.
- Neon connection drops caused setup errors; reruns moved to another DB, so there is no clean single run.
- Parallel-branch clashes: S5.2 and S5.5 both created app/engine/privacy.py (renamed data_rights.py); two migrations numbered 0018 (renumbered; S5.6 became 0019).
- The S5.2 re-review found a new deadlock introduced by the fix; no test reproduces it.

Action for next sprint
- At planning, reserve the migration number and module name per story before parallel builders start, and run broad suites as sequential batches on a dedicated, stable DB.

## Scorecard
Evidence only; "no data" where none was recorded.

| Agent | Tasks done | First-try test pass | Rework commits | Safety findings raised/missed | Eval delta | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| main session | integration, deadlock fix 0c410a7, migration renumber, final verification | no data (batches only, see Review) | 0c410a7, 4a228cc | n/a | no data | |
| builders (Sonnet) S5.1-S5.6 | 6 stories built | no data | 7616458 + d3e434e (S5.1), 6d892a5 (S5.2), 6592bd9 (S5.4), 7aa7444 (S5.5), 4a228cc (S5.6) | n/a | no data | rework on 5 of 6 stories |
| safety-reviewer (sonnet) | reviewed all six | n/a | n/a | raised: 2 HIGH (S5.1), 2 MEDIUM (S5.2) plus 1 new medium on re-review, 1 MEDIUM (S5.5); S5.3, S5.4 clean; missed: none known | n/a | S5.6 translations reviewed clean vs rule 7 |
| test-runner (haiku) | no data | no data | no data | n/a | n/a | |
| eval-runner (haiku) | no eval run this sprint | n/a | n/a | n/a | no data | |
| business-analyst (sonnet) | docs/research/dpdp-and-hindi.md (da590d6) | n/a | n/a | n/a | n/a | legal points provisional |

## Stand-up 2026-10-27 evening (post-close)
First stand-up under the new stand-up rule (docs/EPICS.md "Working agreement"). Evidence from git log and the Review section above.

| Participant | Done (evidence) | Next | Blocked |
| --- | --- | --- | --- |
| Opus coordinator (main session) | Merged all S5 branches; fixes bfe1b30 (audit-scan false positive), 0c410a7 (exclusive customer lock after deadlock finding), 989cf8f (privacy page: no "as the law requires" claim); chaos x3 on 989cf8f (3 passed, 1 skipped each); test merged to main at 9f596aa; 7-batch verification on 1d917f8 (see Review) | Support the owner's human items; any follow-ups the owner picks | none |
| Builder S5.1 (Sonnet) | 6e28e19, rework 7616458 and d3e434e; migration 0017; 52 tests | none, story closed | none |
| Builder S5.2 (Sonnet) | 4524060, rework 6d892a5; migration 0018; 40 tests | none, story closed | none |
| Builder S5.3 (Sonnet) | c9ee4c0, no bug found; chaos 3 passed, 1 skipped | none, story closed | none |
| Builder S5.4 (Sonnet) | 8ff8434, 6592bd9; web 83 passed | none, story closed | none |
| Builder S5.5 (Sonnet) | 74efee9, rework 7aa7444 | none, story closed | none |
| Builder S5.6 (Sonnet) | 7e881a6, 4a228cc; migration 0019 | none, story closed | none |
| safety-reviewer | Reviewed all six stories: 2 HIGH (S5.1), 2 MEDIUM + 1 new on re-review (S5.2), 1 MEDIUM (S5.5), all fixed; S5.3, S5.4 clean; S5.6 translations clean vs rule 7 | Review any follow-up touching money, approvals, tenancy, RLS or migrations | none |
| test-runner | No separate reports recorded; final counts are in the Review section (unit 411, isolation 206, batches above) | On request | none |
| eval-runner | no activity (no eval run this sprint) | On request | none |
| business-analyst | docs/research/dpdp-and-hindi.md (da590d6) | On request; GST/accounting retention for order references is unresearched | none |
| scrum-master | Closed Sprints 4 and 5: reviews, retros, scorecards, ticks (close commit 2d2d08d; S5.3 tick d4097ec; S4.5 tick 61362cc); this stand-up and docs/sprints/README.md | Run the next stand-up under the rule | none |
| Owner (human) | Approvals given today (push when green, test merged to main) | E0.3 rotate Neon owner password; E7.2 copy .env into clean clone and see an AI proposal; confirm provisional decisions (365-day floor; privacy contact label, 30-day target vs 90-day ceiling; no consent record for support; native review of Hinglish/Devanagari; GST retention) | Waiting on the owner for all of these |
