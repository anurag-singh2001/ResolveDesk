# Sprint 8

## Sprint Planning (2026-10-28, written during Sprint 7)

**Sprint goal:** Transparency and trust: customers and staff can read the rules behind every decision; the privacy page is useful; demo controls are clear; the new UI ships.
**Dates:** 2026-10-30 → 2026-10-31 (2 days, proposed; starts only after Sprint 7 closes and the owner confirms; shift if Sprint 7 overruns).
**Source:** docs/ROADMAP.md (E15, E16, E19), docs/research/privacy-page-needs.md (R1-R6), docs/sprints/sprint-7.md (Daily Scrum 2026-10-28).

### Sprint 7 state this plan assumes (coordinator facts, to be re-verified at Sprint 7 close)
- Merged and pushed on test (head b3535c7): S7.1, S7.12, S7.8, S7.11, S7.2, S7.3, S7.4, S7.7. Not yet ticked in EPICS.md (Sprint 7 Review does that).
- In progress: S7.5, S7.6 (3 review blockers being fixed), S7.10. UI branch feature/UI-chaiui is ready except CasePage. S7.9 not started.
- Anything from Sprint 7 not ticked at its close carries over with its points unchanged. Only S7.9 is pulled here as a known carry-over. If S7.5 (8), S7.6 (5) or S7.10 (5) also carry over, Sprint 8 is full and the stretch items below drop first (see the capacity section).

### Capacity and fit
- Capacity: about 40 SP (2-day sprint, 2-3 parallel builders). Sprint 7 velocity is not known yet; revise at Sprint 7 Review.
- Pulled: 42 SP = 5 (carry-over S7.9) + 13 (E15) + 3 (S8.6) + 16 (S8.5 split into S8.5a-S8.5d) + 5 (S8.7).
- Committed core: 39 SP. Stretch: S8.5c readable export (3 SP). Planned total including stretch: 42 SP, 2 SP over capacity. Drop S8.5c first if short; never drop tests or safety review.
- S8.5 was 5 SP in the roadmap; the R1-R6 research shows it is about 16 SP of work (plus the 8 SP owner queue). Re-estimated here, as Planning allows. Roadmap total for Sprint 8 moves from 31 (provisional) to 42.
- S8.7 was 8 SP provisional (foundation). The foundation and ten pages already exist on feature/UI-chaiui, so the remaining work is CasePage restyle, merge and the walkthrough: re-estimated 5 SP. Later UI build stories (S9.5, S10.3, Sprint 12) are sized at their own planning.
- No story is above 8 SP. S8.5 was split before pulling. S8.5e (owner request queue, 8 SP) is not pulled; planned for Sprint 9.
- Heavy processes: at most 2 at once (full suite, evals, chaos).
- Suggested lanes: A = S7.9 then S8.6 (remedy and demo panel); B = S8.1, S8.3, then S8.2 (policies; S8.3 needs S8.1); C = S8.5a, S8.5b, S8.5d, S8.5c (privacy); D (main session or one builder) = S8.7 (UI merge and walkthrough). Four lanes exceed the 2-3 builder assumption: lane A's work is small, so S8.6 can go to lane D's builder after S8.7 merges, if needed.

### Gates
- S8.7: the UI is built from approved designs. Owner direction recorded 2026-10-28 in chat: install the ChaiUI skill, follow its rules, update the wireframes and implement the revamp in code; the owner reviewed the ChaiUI wireframes (dark + light) and app screenshots and asked to continue. The owner question on the highlight capitalisation stays open (default: sentence case). Merge the UI branch before the page stories where possible to avoid a double restyle.

### Stories

#### S7.9 (carry-over) Customer chooses voucher or refund where the rule allows (5 SP)
- User story: As a customer with a rule-eligible complaint I want to choose between a voucher and a refund where the rule allows both so that I get the remedy that suits me.
- Acceptance criteria:
  - Given a pack rule that lists more than one remedy option for a category, When the customer reports an issue, Then the report form and case page offer only the options the rule allows.
  - Given the customer picks an option, When the proposal is created, Then it carries that remedy and code enforces the rule limits (amount, cap, order total); a choice outside the rule is rejected.
  - Given a rule with a single option, When the customer reports, Then no choice is shown and the existing flow is unchanged.
  - Given the same input on both tenants, When tests run, Then both pass without naming a tenant.
- Owner agent: Sonnet builder (lane A). Dependencies: S7.8 (merged).
- Safety review: YES (money).
- DoD: common DoD below; browser walkthrough yes (report form and case page).

#### S8.1 Policies endpoint and pages (5 SP)
- User story: As a customer or staff member I want to read the current policy documents so that I know the rules a decision was based on.
- Acceptance criteria:
  - Given a signed-in customer or staff user, When they call GET /policies, Then they receive the current documents with their sections (id, title, text, version, in force from), for their own tenant only.
  - Given a customer opens "Our policies", When the page loads, Then documents and sections are readable, with in-page anchors per section.
  - Given a staff user opens the policy view, When the page loads, Then they see the same documents plus the version and date in force.
  - Given a request for another tenant's policy or an unknown section, When made, Then 404.
  - Given policy text contains markup or instructions, When rendered, Then it is shown as plain text (policy text is untrusted, hard rule 9).
- Owner agent: Sonnet builder (lane B). Dependencies: none.
- Safety review: no (read path, tenant-scoped; tenancy test included).
- DoD: common DoD; browser walkthrough yes.

#### S8.2 Plain-language rules summary (5 SP)
- User story: As a customer I want a short "what you get when..." summary per issue category so that I know what to expect before I ask.
- Acceptance criteria:
  - Given the tenant's pack remedies, settings resolver values and late tiers, When the summary is requested, Then each category shows the remedy in plain words with amounts formatted from paise.
  - Given a rule changes in settings, When the summary is requested, Then the new values appear with the date in force; nothing is hard-coded in a component.
  - Given a category with several options (see S7.9), When shown, Then all allowed options are listed.
  - Given both tenants, When tests run, Then each summary reflects only that tenant's own rules.
  - Given the summary and the code rule disagree, When tests run, Then a test fails (summary is generated from the same source the executor uses).
- Owner agent: Sonnet builder (lane B). Dependencies: S8.1 (page host), S7.9 (options).
- Safety review: no (read only; derived from money rules, so a test pins the figures to the rule source).
- DoD: common DoD; browser walkthrough yes.

#### S8.3 Every decision links to its source (3 SP)
- User story: As a customer or staff member I want each decision to link to the exact policy section and rule that produced it so that I can check why it was made.
- Acceptance criteria:
  - Given a decision cites a policy, When the case page is shown, Then the citation opens the exact section in the policies page (anchor).
  - Given a remedy line, When shown, Then it names the rule that set the amount (for example "voucher capped at Rs 150 by the refund rule").
  - Given a citation whose section no longer exists, When shown, Then it falls back to the document and says the section changed; no broken link.
  - Given both tenants, When tests run, Then links resolve inside the same tenant only.
- Owner agent: Sonnet builder (lane B). Dependencies: S8.1.
- Safety review: no.
- DoD: common DoD; browser walkthrough yes.

#### S8.5a "What we hold" table and privacy contact (R1 + R6) (5 SP)
- User story: As a customer I want to see what the business holds about me, why, for how long and who else sees it, with a named contact for questions so that I can trust and control my data.
- Acceptance criteria:
  - Given a signed-in customer, When they open Privacy, Then a table lists data items (name, phone masked, address, orders, support messages, refund and voucher records, consent choices) with real counts or values, a one-sentence purpose, retention from tenant settings, and help-or-marketing.
  - Given another customer's or tenant's id, When requested, Then 404.
  - Given a tenant setting for processors (AI providers, messaging channel), When the page loads, Then "Who else sees it" lists them.
  - Given the "What we do not keep" line, When a claim is shown, Then it is backed by a setting; a test fails if shown without backing. (Default: line hidden until the owner confirms claims.)
  - Given the privacy contact setting (label, email, identifier), When the page loads, Then the contact shows near the top and in the footer; every rights message includes it, tested on both tenants.
  - Given row labels, When rendered, Then they come from the vertical pack or settings, not a tenant-specific component.
- Owner agent: Sonnet builder (lane C). Dependencies: none (S5.5 contact setting exists).
- Safety review: YES (customer data, tenancy).
- DoD: common DoD; browser walkthrough yes.

#### S8.5b Consent framed as benefits (R2) (3 SP)
- User story: As a customer I want each marketing choice explained by what I get, with help messages shown as always on, so that I can consent freely and withdraw easily.
- Acceptance criteria:
  - Given each purpose, When shown, Then it has a title, a benefit sentence, what is sent and how often (cap from settings) and the channel.
  - Given help messages, When shown, Then they read "always on, needed to resolve your order" with no switch.
  - Given a switch is toggled, When saved, Then the change applies immediately, defaults are off, one action withdraws, and a consent record is written (purpose, channel, timestamp, notice version).
  - Given growth targeting, When it selects an audience, Then it reads the latest record (test).
  - Given the page copy, When read, Then it states withdrawal never affects order help.
- Owner agent: Sonnet builder (lane C). Dependencies: S8.5a (page layout).
- Safety review: YES (consent, customer messaging).
- DoD: common DoD; browser walkthrough yes.

#### S8.5c Readable export plus JSON (R3) (3 SP) - STRETCH
- User story: As a customer I want to download my data in a form I can read, plus the raw file, so that I can see what the business holds.
- Acceptance criteria:
  - Given the customer presses Download my data, When they choose readable, Then a print-friendly HTML page opens with sections (details, orders, cases, refunds and vouchers, choices, processors); JSON remains as the second option.
  - Given money and dates, When shown, Then amounts come from paise via the one money formatter and dates are in Asia/Kolkata with month names.
  - Given a second customer in the same tenant and a customer in the other tenant, When the export runs, Then only the signed-in customer's records appear.
  - Given internal fields (code-only ids, prompts, other customers' names in shared cases), When the export is scanned, Then none appear (test).
  - Given each export, When completed, Then an audit event is written with no personal content.
- Owner agent: Sonnet builder (lane C). Dependencies: S8.5a.
- Safety review: YES (customer data).
- DoD: common DoD; browser walkthrough yes.

#### S8.5d Erasure explained and tracked (R4) (5 SP)
- User story: As a customer I want to know what erasure removes, what stays and why, and follow my request to the end so that I can decide and trust the result.
- Acceptance criteria:
  - Given the erasure card, When shown in account settings, Then it lists "We will remove", "We will keep" (with a reason per item) and "We may wait" (open case or refund).
  - Given the customer presses Request, When confirming, Then a confirmation step restates the lists before the request is created.
  - Given a request exists, When viewed, Then it shows status (received, in progress, done, deferred with reason), received date, expected-by date (tenant setting, default 30 days) and the privacy contact; "done" appears only after the executor has succeeded.
  - Given the request is not yet approved, When the customer cancels, Then it is withdrawn and audited.
  - Given an open case, When erasure is requested, Then it is deferred with a stated reason; after completion name, contact and message text are removed, paise amounts and audit rows remain, and the customer's export shows the erased state.
- Owner agent: Sonnet builder (lane C). Dependencies: S8.5a.
- Safety review: YES (customer data, erasure executor, approvals).
- DoD: common DoD; browser walkthrough yes.

#### S8.5e Owner privacy request queue with deadlines and audit (R5) (8 SP) - NOT PULLED, plan for Sprint 9
- Estimated at 8 SP: a staff page (type, state, received, internal due, days left, legal ceiling), role-gated approve/reject bound to the payload hash with expiry, dry-run of what is removed and held back, sweeper flags for near-due and overdue (fake-clock test), audit per state change, tenant-scoped.
- User story: As an HQ owner I want a queue of privacy requests with due dates and an audit trail so that I answer every request in time and approve each erasure knowingly.
- Owner agent: Sonnet builder. Dependencies: S8.5d. Safety review: YES (approvals, customer data). To confirm in Sprint 9 planning whether an owner-side view already exists (research open question 1).

#### S8.6 Rename and explain the Dev panel as "Demo controls" (3 SP)
- User story: As the owner running a demo I want clearly named and explained controls so that I know what each does and cannot reset the demo by accident.
- Acceptance criteria:
  - Given the panel, When opened, Then it is titled "Demo controls" and each control has a one-line help text.
  - Given reset-demo, When pressed, Then a guard (confirmation plus dev-only check) is required; outside dev it is disabled or 404.
  - Given the panel, When viewed, Then it links to the platform portal (placeholder page until S9.5 if not yet built).
  - Given the clock and mock controls, When used, Then behaviour is unchanged (existing tests still pass).
- Owner agent: Sonnet builder (lane A). Dependencies: none.
- Safety review: no (dev-only; guard test included).
- DoD: common DoD; browser walkthrough yes.

#### S8.7 UI revamp ship: CasePage restyle, merge UI branch, walkthrough (5 SP; re-estimated from 8 provisional)
- User story: As any user I want a consistent, accessible new interface in light and dark so that the product is clear to use on desktop and phone.
- Acceptance criteria:
  - Given feature/UI-chaiui, When CasePage (with the S7.1/S7.2 content, escalation actions) is restyled, Then all its states render with the new components (the remaining pages, ApprovalDetail, Help, Queue, are done by Sprint 7 or listed as an exception here).
  - Given the branch, When merged into test, Then conflicts with merged Sprint 7 stories are resolved, web tests (87+) and build pass, `make lint` is clean.
  - Given the merged app, When walked through in a browser, Then every role page on both tenants works in light, dark and System themes and at 375px width, with screenshots recorded in this file.
  - Given Devanagari text, When rendered, Then glyphs display correctly (design system requirement).
  - Given the owner's open highlight question (capitalize vs sentence case), When unanswered, Then default is sentence case.
- Owner agent: Sonnet builder (UI, lane D) with main-session review. Dependencies: S7.D2 direction recorded 2026-10-28; Sprint 7 case-page stories merged (S7.5/S7.6 UI in particular, else CasePage is restyled twice).
- Safety review: no (no money or tenancy change; confirm no server code in the diff).
- DoD: common DoD; browser walkthrough is the core of this story.

### Common Definition of Done (docs/EPICS.md "Working agreement")
Tests added and passing for both tenants (never naming a tenant), `make lint` clean, safety review where marked YES, docs and manuals updated (README, RUNBOOK, SCENARIOS, DECISIONS as relevant), browser walkthrough for UI stories, CI green on the pushed branch.

### Dependency order
S8.1 before S8.2 and S8.3; S7.9 before S8.2 (options); S8.5a before S8.5b, S8.5c, S8.5d; S8.5d before S8.5e (Sprint 9). Merge the UI branch (S8.7) early on day 1 if the owner gate is met, so page stories are built once. Merge one story at a time; targeted tests on the merged head after each.

### Sprint 8 points
| Group | Stories | SP |
| --- | --- | --- |
| Carry-over | S7.9 | 5 |
| E15 transparency | S8.1, S8.2, S8.3 | 13 |
| E16 privacy | S8.5a (5), S8.5b (3), S8.5d (5), S8.5c stretch (3) | 16 |
| E16 demo controls | S8.6 | 3 |
| E19 UI | S8.7 | 5 |
| Total | 10 stories | 42 (39 core + 3 stretch; capacity about 40) |
| Not pulled | S8.5e privacy request queue | 8 (Sprint 9) |
| Done earlier | S8.4 research (2 SP, fecf31c) | counted in Sprint 7 working time, not in these 42 |

### Owner's open questions and the default used until answered
| Question (source) | Default the team uses |
| --- | --- |
| Internal response target for privacy requests: 30 days or shorter for the demo? (research Q2, DECISIONS provisional) | 30 days as tenant setting `privacy_request_target_days`; legal ceiling 90 days shown separately. Demo can set a shorter value. |
| "Privacy contact" or "grievance officer"? (Q3) | "Privacy contact" label; configurable per tenant; revisit with counsel. |
| Retention figures shown to customers: 12 months messages, 7 years payment records? (Q6) | Show tenant-setting values; seeded defaults 12 months for messages (365-day floor already decided) and 7 years for payment and refund records; labelled provisional in DECISIONS. |
| Readable export: print-friendly HTML or PDF? (Q5) | Print-friendly HTML plus the existing JSON; no PDF file. |
| Which "what we do not keep" claims may we make (card numbers, UPI details)? (Q4) | Hide the line until the payment mock is checked and the owner confirms; each claim backed by a setting. |
| Is a staff request queue already built? (Q1) | Assume not; S8.5e is its own story (8 SP), Sprint 9. |
| Benchmarks for Swiggy, Tata Starbucks India, Domino's India (Q7) | Owner optional: paste sections from a browser; no story is blocked. |
| Highlight capitalize vs sentence case (UI) | Sentence case. |
| Design approval (S7.D2) | Direction recorded 2026-10-28 (owner asked to implement the ChaiUI revamp). Open: highlight capitalisation. |

### Risks
- Sprint 7 may not close cleanly: S7.5, S7.6, S7.10 carry-over would add up to 18 SP and push Sprint 8 to about 60 SP. Then keep S8.1-S8.3 and S8.7, move S8.5a-S8.5d wholly or partly (S8.5c, then S8.5b) to Sprint 9, and re-plan.
- S8.5a-S8.5d all touch customer data and need safety review: four reviews serialised on one reviewer. Mitigation: review S8.5a early, share findings with later builders.
- S8.7 depends on an owner action (design approval) and a large merge; hold it until Sprint 7 case-page stories have landed.
- Neon free-tier flakiness and the 2-heavy-process cap limit parallel test runs.

## Daily Scrum 2026-10-31 (live, called by the owner)

Evidence checked in git at the time of writing: local `test` head 4a462df; `origin/test` ef33ab8 (S8.3); local is 4 commits ahead (S7.5 merge db1768b, migration 0025; eval harness fix ef4dbb8; Sprint 9 plan 4a462df; plus 3006e74). Ready branches exist: feature/S8.5d-erasure bb61f94, feature/S8.5c-readable-export dbb4885, feature/S8.5b-consent-benefits df3a697. Test counts below are as reported by the coordinator; I did not run them.

| Participant | Done (evidence) | Next | Blocked |
| --- | --- | --- | --- |
| Main session / Opus coordinator | Merged and pushed Sprint 8: UI revamp f11eaca, S8.1, S8.2 a0f1f61, S8.3 ef33ab8, S8.5a d71ff3b, S8.6 ee6cfce. Merged locally S7.5 db1768b and eval harness fix ef4dbb8. Wrote Sprint 9 plan 4a462df. Mistake owned: put an eval run and a builder on the same DB (s8a), so the first eval crashed | Finish S7.5 merged-head tests, push; merge S8.5d, then S8.5c, then S8.5b (needs 0026 first), targeted tests after each | Machine memory 1.6-2.2 GB free; background runs killed twice |
| Builders S8.5d / S8.5c / S8.5b (Sonnet) | S8.5d bb61f94 (migration 0026; 40+40+26 passed); S8.5c dbb4885 (28+40+20 passed, vitest 150); S8.5b df3a697 (migration 0027, renumbered after 0026) | Wait for merge order; S8.5b re-test after 0026 lands | Merge order; usage limits interrupted builders several times |
| Builders S7.5 / S8.1-S8.6 / S8.7 (Sonnet) | All merged (see coordinator row) | no activity until Sprint 9 | none |
| safety-reviewer (Sonnet) | Reviews of S7.5, S8.5a, S8.5b-d, S8.3 each found real bugs fixed before merge (e.g. a44f65a four eyes and no staff auto-approve; 0ba2fe4 legal ceiling and provisional label) | Re-review S8.5b after rebase if the migration or consent logic changed | none |
| test-runner (Haiku) | S7.5 merged-head run in progress, 10+ min, restarted after a low-memory kill. No full suite on test head yet | Report S7.5 result; targeted runs per merge | Memory; max 2 heavy processes |
| eval-runner (Haiku) | No completed eval this sprint or Sprint 7: run 1 crashed (shared DB), run 2 on resolvedesk_eval killed for memory | Re-run on dedicated resolvedesk_eval once memory is free and no builder test is running | Memory |
| business-analyst (Sonnet) | S8.4 privacy research fecf31c (earlier). No activity since | No activity; owner benchmark paste optional | none |
| scrum-master | This stand-up; Sprint 9 planning was done earlier; no ticks | Sprint 8 Review when DoD evidence exists | none |
| Owner (human) | Gave `.env` access verbally; deferred Neon password rotation (keep current DB) | Lift the `.env` deny rule in .claude/settings.json or paste values; answer decisions below; do browser walkthroughs or approve them being run | `.env` still denied by settings; decisions pending |

### Honest status
Zero stories meet the full Definition of Done today, so nothing is ticked in EPICS.md. Missing for every merged story: browser walkthrough (none done), completed eval run (none), full suite on the test head (not run), CI on the pushed branch for the unpushed commits. S7.7 (O0005779) is not cleared. Sprint 7 and Sprint 8 dates have both passed (7 ended 2026-10-29, 8 planned to end today 2026-10-31); everything unticked is at risk and carries over.

### Burndown (SP; "done" means ticked, which needs full DoD)
| Sprint | Planned | Merged (code) | Ready, not merged | Not merged / not started | Ticked (done) |
| --- | --- | --- | --- | --- | --- |
| 7 | 60 (47 code + 13 design) | 47 code (39 + S7.5 8, merged locally; S7.5 not pushed) | 0 | Design S7.D1 + S7.D2 13: no repo evidence | 0 |
| 8 | 42 (39 core + 3 stretch; includes S7.9 5 carry-over) | 31 = S7.9 5 + S8.7 5 + S8.1 5 + S8.2 5 + S8.3 3 + S8.5a 5 + S8.6 3 | 11 = S8.5d 5 + S8.5c 3 + S8.5b 3 | 0 | 0 |
Note: S7.9 is counted in both Sprint 7 (47) and Sprint 8 (carry-over); the true unique code total is lower by 5.

### Today's plan (in order)
1. Finish S7.5 merged-head tests, then push test (S7.5, harness fix, Sprint 9 plan).
2. Merge S8.5d (0026), targeted tests; then S8.5c; then S8.5b with a re-test; one merge at a time.
3. When memory allows: eval run on resolvedesk_eval (nothing else heavy), then one full suite on the test head.
4. Browser walkthroughs (light, dark, 375px, both tenants) for UI stories; clear O0005779 via S7.4 and verify in the UI.
5. Then Sprint 7 and Sprint 8 Reviews and ticks, only for verified stories. Sprint 9 does not start until Sprint 8 is merged.
6. Proposed re-scope if the day runs out: nothing new started; carry unticked stories forward; never drop tests, evals or safety review.

### Owner decisions pending (the three that matter most)
1. Refund option fit to policy, "no remedy is due" wording, and the second-person rule on the S7.10 switch: all change money behaviour in shipped code.
2. Privacy figures and labels: retention (12 months messages, 7 years payments), 30-day target, "privacy contact" label, the "not kept" claims, and the completion message after erasure.
3. Lifting the `.env` deny rule (or pasting values) so the portal and evals can run for real; also needed for the real walkthrough.
Others: highlight case (default sentence case), S7.5 defaults (four eyes, no staff auto-approve), campaign dual approval, Sprint 8 dates, customers seeing other brands' policies, real Reset demo, JSON export case ids, Hindi/Hinglish native review.

## Retro, Review
(To be added at Sprint 8 close.)
