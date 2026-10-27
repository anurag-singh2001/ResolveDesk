# Sprints overview (0 to 5)

Written 2026-10-27 by the scrum-master from docs/sprints/sprint-N.md, docs/EPICS.md and `git log`. Numbers are as recorded in the sprint files; "not recorded" means no output was pasted. Status: `[x]` verified done, `[~]` open, `[ ]` todo. Working agreement (stand-up rule): see the top of docs/EPICS.md.

| Sprint | Dates | Goal (short) | Outcome |
| --- | --- | --- | --- |
| 0 | 2026-10-23 to 10-24 | Tools, process, research, skeleton | closed; E0.3 human item open |
| 1 | 2026-10-23 (start early) to 10-24; planned to 10-28 | Tenancy, RLS, settings, auth, data and money core | 10 of 11 done; E0.3 open |
| 2 | 2026-10-24 to 10-26; planned to 10-31 | AI pipeline and safe execution | closed 5 days early |
| 3 | 2026-10-26; planned 11-02 to 11-04 | Stretch growth loop (E8) and human items | closed same day |
| 4 | 2026-10-26 to 10-27 | Spec gaps to a complete v1, ship | closed; test merged to main 9f596aa |
| 5 | 2026-10-27 (overnight) | Privacy basics, growth chaos, approvals filter, Hindi | closed; all six stories ticked |

---

## Sprint 0 (2026-10-23 to 10-24): tools, process, research
Goal: tools, process and research in place; skeleton green; Neon ready.

| Story | Status | Key commit |
| --- | --- | --- |
| E0.1 tools | [x] | n/a (versions print) |
| E0.2 git repo + first commit | [x] | 047cb5d |
| E0.3 Neon, branches, app role, .env (human) | [~] | none (human) |
| E0.4 scrum-master + BA agents, EPICS, sprint files | [x] | a2b9846 |
| E0.5 Docker to Neon docs, decisions | [x] | a2b9846 |
| E0.6 market research | [x] (closed in Sprint 1/2) | 6d76056, rev 2 950facd |
| E1.1 skeleton | [x] | a2b9846 |

- Verified: `make test` 1 passed, `make lint` clean, tool versions print (make 4.4.1, uv 0.13.5, ruff 0.17.2); `make db-check` failed (no env).
- Incident: the only external dependency (Neon) was on the critical path and not unblocked; agents created mid-session did not load until restart.
- Retro lesson: unblock E0.3 first; commit per story (one commit mixed three stories).
- Scorecard: main session 5 stories, 0 rework; other agents not used or no data.

## Sprint 1 (2026-10-23 to 10-24, planned to 10-28): foundation and data/money core
Goal: tenancy + RLS foundation and the data/money core proven on real Neon. Planning called the 11-story scope "unrealistic"; all of it was pulled in anyway.

| Story | Status | Key commits (merge) |
| --- | --- | --- |
| E1.2 tenancy tables + RLS | [x] | c8ca319 |
| E1.3 vertical packs, settings, loader | [x] | 374ccca (99d3c96) |
| E1.4 demo auth, TenantContext | [x] | 737baec, 7cf6113, 6552126 (24bc2bb) |
| E2.1 canonical tables + simulator | [x] | d7e891c, 39bc7d0, 57e6967 (0156464) |
| E2.2 mock providers + chaos | [x] | d1e4920, 319ab3a (84c5395) |
| E2.3a registries, proposals with payload hash | [x] | 7abf3b1, 754996a, 3e3b24f, c0c7c66 (8fde736) |
| E2.3b eligibility + safe refund execution | [x] | b2431eb, d03d2b6, 42e72bb, 2cfec15 (b6f469e) |
| E2.3c cases and approvals endpoints | [x] | c370de4, d4be4c3 (7735de5) |
| E2.4 skills add-action, add-connector | [x] | 4d37ff8 (aa03f84) |
| E0.6 market research | [x] | 6d76056 |
| E0.3 Neon (human) | [~] | none |

- Verified: `make test` 374 passed (+1 Neon drop, passed on rerun); `make test-isolation` 149 passed; lint clean; seed all 47 s; isolation 42 tests at E1.2.
- Incidents: Neon owner role has BYPASSRLS, so an owner-run reseed wiped another tenant's test history (caught by tests; fix: migration 0010 `resolvedesk_maint`). Neon free tier drops connections. test-runner misreported a CRLF env problem as 42 driver errors.
- Retro lesson: safety review pays off (cross-tenant data-loss path, a real double-refund hole, 7 auth issues, all fixed before merge). Create `.env` before Sprint 2.
- Scorecard: main session about 12 safety-driven fix commits; safety-reviewer about 17 passes, 52 pass-1 findings; test-runner 0 of 1 first-try.

## Sprint 2 (2026-10-24 to 10-26, planned to 10-31): AI pipeline and safe execution
Goal: LLM-driven case flows classify, investigate/policy, propose, approval, safe execution, honest message, both tenants, chaos proves no duplicate money. Also absorbed Sprint 3's UI and evals.

| Story | Status | Key commits |
| --- | --- | --- |
| E3.1 LLM provider factory | [x] | f0bbde2, 14601b9 |
| E3.2 policies + RAG | [x] | 3312f00 |
| E3.3 agents + LangGraph | [x] | 2d54e86, 95674ea, edd25e5 |
| E4.1 interrupt/resume, checkpointer | [x] | 71592bd |
| E4.2 executor, verifier, tickets, events | [x] | 71592bd, d20c8a6 |
| E4.3 chaos suite (50 cases/tenant) | [x] | ec2a80a |
| E4.4 operator release of quarantine | [x] | dda34ec, 71592bd |
| E4.5 sweeper | [x] | dda34ec, 71592bd |
| E4.6 execute auto-approved vouchers | [x] | dda34ec, 71592bd |
| E2.5 fair-use signal, E3.4 PII minimisation, E3.5 policy wording | [x] | a4773b2, d20c8a6 |
| E5.0 to E5.6 UI, login API, React web app, manuals | [x] | d61e0d4, b3ad76a, 8b0a9c3, a4773b2, ee96fa0 |
| E6.1 to E6.3 eval harness, 30 scenarios, baseline | [x] | edd25e5 |
| E7.1 README | [x] | fc7bb5f |
| E7.2 clean-clone check | [~] | fc7bb5f, 90fd4a1 (human .env step left) |

- Verified: full suite on isolated DB at ec2a80a 930 passed, 9 skipped; chaos 2 passed (one per tenant, zero duplicate refunds); evals edd25e5 brewco 100%, spice_route 91%, baseline 91%/75%, 0 over-rule proposals; later run eval-20261025-222049.md 100% (tuning set, cache on, held-out not shown). Browser click-through for both tenants passed (Spice Route Rs 264 refund approved by Asha; BrewCo Rs 100 voucher auto-approved in about 20 s).
- Incidents: account rate limits stopped every agent on 10-25 (about one day lost); stale demo packs; Flight 2 found the AI proposing 100% refunds from policy text (fixed by a business-rule ceiling, c1cc356); auto-approved proposals not executing (0fed2d1).
- Retro lesson: run one scripted "fresh DB + seed + start api/web + sign in" smoke before any demo.
- Scorecard: about 25 stories ticked; safety-reviewer clean at 71592bd, 0fed2d1, ee96fa0, a4773b2; per-pass counts not recorded.

## Sprint 3 (2026-10-26, planned 11-02 to 11-04): stretch growth loop
Goal: finish the growth loop (E8) without touching the verified core; clear human items.

| Story | Status | Key commits |
| --- | --- | --- |
| E8.1 repeat-rate signal + diagnosis | [x] | e811ede (80eb079) |
| E8.2 audience, holdout, dual approval, idempotent sends | [x] | e811ede, c605096 (80eb079) |
| E8.3 verdict + playbook | [x] | e811ede (80eb079) |
| E7.2, E0.3, test to main review | open (human) | none |

- Verified: tests/integration/test_growth.py 27 passed, 1 skipped; growth + isolation 225 passed, 2 skipped; migration 0015. Full-suite record post-E8: 1020 passed, 2 failed, 10 skipped; chaos 1 passed, 1 failed; both fixed in e047336 (29 passed after).
- Incidents: chaos found an intermittent customer-facing wording defect (case showed "needs a check" although the refund had succeeded; fixed in app/engine/case_status.py with a deterministic regression test). Growth simulator rows leaked into the seed-reload test.
- Retro lesson: run the seed-reload test right after any new simulator; run chaos 3 times on the merged branch before calling a merge done.
- Scorecard: main session 2 rework commits; Sonnet builders, test-runner: no data; safety found 4 real E8 gaps.

## Sprint 4 (2026-10-26 to 10-27): spec gaps to a complete v1
Goal: close every gap from the section 12/13/17 audit, then ship.

| Story | Status | Key commits |
| --- | --- | --- |
| S4.1 customer reply to needs-info (B1) | [x] | f9dd2fa (6177d9b), fix 59a711e |
| S4.2 HQ insights + Growth UI (B2) | [x] | b357f71 (23376a5), eb51a70, 02e25d4, ea2103e |
| S4.3a simulated clock (B3) | [x] | e25679b (26e6e3d), 8f1b28b, 040081e |
| S4.3b durable mock providers (B3) | [x] | e25679b (26e6e3d) |
| S4.4 integration | [x] | 914f1bb, bfe1b30 |
| S4.5 ship, test merged to main | [x] | 02e0ade, main 9f596aa |
| Follow-ups F1 to F4, clock-skew fix | merged | 8451ed2, b09c157, 5904e23, beae726, ea2103e, 0158378, d0ee6ef |

- Verified: full suite on 914f1bb 1128 passed, 12 skipped, 6 failed (moving working tree); clean-head re-run 136 passed after audit-scan fix bfe1b30; chaos x3 green (2/2 each, later 3 passed, 1 skipped); isolation 206 passed, 1 skipped on 1d917f8; evals eval-20261026-161051.md agents 100% both tenants, baseline brewco 100% / spice_route 92%, over-rule 0. Caveat: no single full run on the final head.
- Incidents: Sonnet limit hit about midnight; machine out of memory killed API, web server and runs; a semantic merge conflict (S4.1 vs S4.3 `_out` signature) made every reply return 500, caught only by the browser walkthrough; stale vite on 5173; reviewer checked out another commit mid-suite (6 false failures).
- Retro lesson: max 2 heavy processes; targeted tests on the merged head after every merge; never review in the folder a suite runs from.
- Scorecard: safety raised 1 HIGH (B3 clock leak), mediums on F1 and F2; B1 to B3 first-try rates no data.

## Sprint 5 (2026-10-27, built overnight): privacy basics and growth hardening
Goal: close the biggest "needed before real customer data" DPDP gaps, harden growth under failure, polish staff screens.

| Story | Status | Key commits |
| --- | --- | --- |
| S5.1 retention setting + purge job | [x] | 6e28e19, 7616458 (2 HIGH), d3e434e; migration 0017; 52 tests |
| S5.2 consent, export, erasure | [x] | 4524060, 6d892a5 (2 MEDIUM), 0c410a7 (deadlock); migration 0018; 40 tests |
| S5.3 growth chaos test | [x] | c9ee4c0; chaos x3 on 989cf8f: 3 passed, 1 skipped each |
| S5.4 approvals filter and sort | [x] | 8ff8434, 6592bd9 |
| S5.5 privacy contact + grievance target | [x] | 74efee9, 7aa7444 (MEDIUM) |
| S5.6 Hindi templates (en / hi-Latn / hi) | [x] | 7e881a6, 4a228cc; migration 0019 |

- Verified (7 sequential batches on 1d917f8): unit 411 passed / 2 skipped; isolation 206 / 1 skipped; cases+reply+language+meta 118; data rights+retention+privacy 104; approvals+growth+sweeper 70 / 2 skipped; refunds+vouchers+resume 116 / 3 skipped; agent graph 76; web 83 passed; ruff clean; single alembic head 0019. No single full run. Research: docs/research/dpdp-and-hindi.md (da590d6).
- Incidents: Sonnet limit about 03:40; memory pressure forced batches; Neon connection drops; module-name clash (privacy.py renamed data_rights.py) and two migrations numbered 0018; S5.2 fix introduced a deadlock found in re-review (safety rests on lock-order reasoning, no reproducing test).
- Retro lesson: reserve migration number and module name per story before parallel builders start; run broad suites as sequential batches on a stable DB.
- Scorecard: reviewers found real defects in 5 of 6 stories; rework on 5 of 6; test-runner and eval-runner no data.

---

## Current state (2026-10-27)
Everything is closed except two human-only items:
- E0.3 rotate the Neon owner password, then `make db-check` on both branches.
- E7.2 copy your own .env into the clean clone, raise a case, see an AI proposal.

Provisional decisions awaiting the owner (docs/DECISIONS.md, not legal advice):
1. 365-day message retention floor.
2. "Privacy contact" label, and 30-day internal target vs 90-day reported ceiling.
3. Support needs no consent record.
4. Native-speaker review of the Hinglish and Devanagari wording.
5. GST/accounting retention period for order references is unresearched.

Open follow-ups (EPICS.md, not stories): demo seed refreshing policy packs automatically; dev-panel reseed (destructive, deliberately not built); S5.2 deadlock fix has no reproducing test; no single full-suite run on the final head (covered by batches).
