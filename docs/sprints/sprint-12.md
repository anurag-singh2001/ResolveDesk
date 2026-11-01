# Sprint 12

## Sprint Planning -- 2026-11-01

**Goal:** Finish the UI revamp, close the known findings, walk both tenants end to end, and merge `test` into `main` with evidence.
**Dates:** 2026-11-02 -> 2026-11-03 (2 days). **Capacity:** about 40 SP nominal; memory is tight, so plan 30 SP core with 4 SP stretch.
**Planned:** 34 SP total = 30 core + 4 stretch (S12.4, S12.7). Nothing over 8 SP.

### Scope finding (checked against web/src)
All 22 page files under web/src/pages already import the shared ChaiUI components, and S7.D1/S7.D2 are waived (ChaiUI is the design of record, DECISIONS latest entries). So there is NO page-restyle story. "Revamp completion" reduces to the polish, performance and consistency items below. `App.tsx` has no `lazy`/`Suspense`, which is the cause of the single 850 kB bundle.

### Stories

Common Definition of Done for every story: tests for both tenants (never naming a tenant), `make lint` clean, docs updated where relevant, browser walkthrough for UI stories, CI green. Safety review only where tagged.

**S12.1 Support contact in the no-remedy closing message (2 SP, Sonnet builder, Safety: customer text)**
- As a customer whose complaint gets no remedy I want a real support contact in the closing message so that I can dispute it with the right people instead of the Privacy desk.
- AC: Given a case closed with no remedy, When the closing message is rendered, Then it names the tenant's support contact (new setting, falls back to a neutral line, never the privacy contact). Given the language is hi or hi-Latn, Then the same contact appears in that language. Given a privacy request, Then the Privacy contact is still used.
- Done when: closing message tests for en/hi/hi-Latn pass on both tenants; safety-reviewer clean on customer text. Deps: none.

**S12.2 One language per customer Privacy page (2 SP, Sonnet builder, Safety: customer text)**
- As a Hindi-speaking customer I want the Privacy page in one language so that I can understand my rights.
- AC: Given a language of en, hi or hi-Latn, When the Privacy page renders, Then all labels, benefit wording and status text come from one locale with no mixed fragments. Given a missing key, Then a test fails (no silent English fallback inside Hindi).
- Done when: key-coverage test for all three locales plus web test for the page; browser check in each language on both tenants. Deps: S12.9 (shared strings).

**S12.3 Find and fix slow pages (3 SP, Sonnet builder)**
- As a staff member I want Policies (rules panel 5-9 s) and the case lists to load fast so that I can work without waiting.
- AC: Given the Policies rules panel, When it loads on the demo DB, Then the cause is recorded (query count, N+1, repeated resolver calls, or Neon round trips) and the panel loads in under 2 s warm. Given the case lists, Then the same measurement is recorded and no list issues per-row queries.
- Done when: before/after timings in DECISIONS.md or the sprint file; a query-count regression test on both tenants; no behaviour change (existing API tests pass). Deps: none.

**S12.4 Route-level code splitting (2 SP, Sonnet builder) -- STRETCH**
- As any user I want the app to load only the page I open so that first load is quick.
- AC: Given the build, When pages are lazy-loaded with `Suspense` and a loading state, Then the entry chunk is well under the current 850 kB (target under 500 kB) and the Recharts and platform portal code are separate chunks.
- Done when: `npm run build` size output pasted; web tests pass; every route still opens (walkthrough in S12.12). Deps: none.

**S12.5 Timeline and status must agree after a verification mismatch (3 SP, Sonnet builder, Safety: money, customer text)**
- As a staff member I want the case timeline and status to tell the same story so that I never see "refund confirmed" next to "needs a check".
- AC: Given an order like O0003646 where verification mismatched after a refund, When the case is shown, Then the timeline records "needs a check" (unknown, not confirmed) and no event or message says confirmed. Given the customer message, Then it states only verified facts and keeps submitted/processing/succeeded/failed/unknown distinct (hard rule 7).
- Done when: regression test reproducing the O0003646 sequence on both tenants; safety-reviewer clean. Deps: none.

**S12.6 Spice Route campaign flow end to end (5 SP, Sonnet builder, Safety: consent, messaging)**
- As an HQ owner on Spice Route I want the campaign flow tested end to end so that growth is proven on both tenants, not one.
- AC: Given the seed, When a repeat-rate drop is planted and a third staff user added for Spice Route, Then a campaign is proposed, approved, sent to consented customers only and shows in ROI with a holdout. Given the golden files, Then they are refreshed and reviewed.
- Done when: test_growth_roi_api and campaign flow tests run (no skips) for both tenants; goldens refreshed with the diff noted; safety-reviewer clean. Deps: none. Removes the S11.3 skips.

**S12.7 Manual spend form (2 SP, Sonnet builder) -- STRETCH**
- As an HQ marketer I want a form to enter manual spend so that ROI reflects offline spend.
- AC: Given the Growth/ROI screen, When I enter an amount in rupees, Then it is stored as integer paise through the existing API, bounded, and appears in ROI. Invalid or negative amounts are rejected with a message.
- Done when: web test and API test on both tenants; browser check. Deps: none.

**S12.8 Calendar warnings on approval screen and correct nav highlight (3 SP, Sonnet builder)**
- As an approver I want calendar clashes shown where I approve so that I do not send overlapping campaigns.
- AC: Given a growth proposal with calendar warnings, When I open its approval screen, Then the warnings show. Given I am on /growth/calendar, Then the side nav highlights Calendar, not Growth.
- Done when: web tests for both; one backend test that warnings are in the approval payload on both tenants; browser check. Deps: none.

**S12.9 Apply the owner's Hindi review corrections (2 SP, Sonnet builder, Safety: customer text)**
- As a Hindi-speaking customer I want natural, correct Hindi so that messages are trusted.
- AC: Given each correction in docs/HINDI-REVIEW.md, When templates and UI strings are updated, Then every item is applied or recorded as declined with a reason in the sprint file.
- Done when: checklist in this file ticked item by item; template tests pass on both tenants; safety-reviewer clean. Deps: confirm docs/HINDI-REVIEW.md has the owner's corrections.

**S12.10 In-app Help and manuals up to date (3 SP, Sonnet builder)**
- As a new user I want Help to cover every screen so that I can use them unaided.
- AC: Given Dashboard, Segments, Brand signals, Calendar, Scenario lab and ROI, When I open Help, Then each has a short section, per role. Given the manuals, Then they match the shipped screens (including S12.7/S12.8 if landed).
- Done when: HelpPage test asserts all six sections for each role; browser check. Deps: S12.7, S12.8 (soft).

**S12.11 README, RUNBOOK, SCENARIOS, demo script (2 SP, main session / scrum-master review)**
- As the owner I want current docs and a demo script so that I can run and show the product.
- AC: README, RUNBOOK and SCENARIOS match the code and counts; a demo script lists steps for both tenants and each role.
- Done when: owner reads the demo script and follows it once. Deps: S12.1-S12.10.

**S12.12 Final walkthrough on both tenants (3 SP, main session + Haiku test-runner)**
- As the owner I want a full walkthrough so that the merge to main is trustworthy.
- AC: Every page and role on both tenants, light and dark, 375px, en/hi/hi-Latn on customer pages, console clean; `make test`, `make test-isolation`, `make lint`, `make web-test`, web build, `make eval` results recorded.
- Done when: evidence table in this file. Deps: all functional stories.

**S12.13 Merge test into main with evidence (2 SP, main session, process)**
- As the owner I want `test` merged to `main` with proof so that main is releasable.
- AC: Given S12.12 passed, When `test` is merged to `main`, Then the merge commit, CI result and evidence table are recorded, and unfinished items (S10.1 real lab run, S8.5e approve/reject click, S7.12 Hindi-script eval) are listed as known gaps.
- Done when: merge hash in EPICS.md; CI green on main. Deps: S12.12. Needs the owner's go-ahead.

### Totals
| Group | Stories | SP |
| --- | --- | --- |
| Core | S12.1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 13 | 30 |
| Stretch | S12.4, S12.7 | 4 |
| Total | 13 stories | 34 |

### Build order (max 2 builders; run one at a time if memory is tight)
1. Builder A: S12.9 (Hindi) -> S12.1 -> S12.2 (all customer text, chained so strings do not conflict).
2. Builder B: S12.3 (slow pages) -> S12.8 -> S12.5.
3. Whichever frees first: S12.6 (heaviest; run its tests alone, not beside the full suite), then stretch S12.7, S12.4.
4. S12.10 after S12.7/S12.8 merge; S12.11 next; S12.12 with at most 2 heavy processes; S12.13 last.
Merge one story at a time, targeted tests after each merge, safety review before merging S12.1, 2, 5, 6, 9.

### At risk
Not yet (sprint not started). If time runs short: drop S12.4 and S12.7 first, never tests or safety review. S12.6 is the main schedule risk (seed changes touch goldens).

### Open items for the owner
Confirm docs/HINDI-REVIEW.md is ready; approve the final merge (S12.13).
