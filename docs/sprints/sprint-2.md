# Sprint 2 · 2026-10-24 → 2026-10-31 (started early; Sprint 3 still starts 2026-11-02)

## Planning (2026-10-24, scrum-master)
Goal: an LLM-driven case flows classify -> investigate/policy -> propose -> human approval -> safe execution -> honest message, for both tenants, with the chaos suite proving no duplicate money.

Dates: Sprint 1 finished on 2026-10-24, so Sprint 2 starts today. EPICS.md had 2026-10-29 -> 2026-10-31; the end stays 2026-10-31 (8 days incl. the weekend, about 6 working days) and Sprint 3 keeps 2026-11-02. This gives slack for the Neon-slow suites (~18 min).

### Already built (from Sprint 1, not redone here)
E2.3b/E2.3c delivered `app/engine/{executor,eligibility,approvals,proposals,cases,case_status}.py`, `execute_refund`, `reconcile_refund`, quarantine, audit, `domain_events` table, case/approval API, and the `add-action`/`add-connector` skills. There is no `app/llm`, `app/rag`, `app/agents`, `app/modules/support`, and no `policies/` folder under `tenants/` yet.

### Stories (in order)
| # | Story | Owner | Done when | Est | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | E3.2 Policies + RAG ingest/retrieve | main (+ business-analyst for policy wording if wanted) | version/override/isolation/missing tests pass | L | No keys needed (local bge-small). Start first. Needs new deps (sentence-transformers, pgvector, a migration for the vectors table with RLS: safety-reviewer). Retrieved text is untrusted (rule 9). |
| 2 | E4.2 remainder: verifier, tickets, honest messages, domain-event subscribers | main + safety-reviewer | rejection + expiry tests pass | M | No keys. Left to build: verifier (read back state after execute, section 10), ticket creation/closing, customer message templates that keep submitted/processing/succeeded/failed/unknown distinct, event subscribers wired to `domain_events`. Already done by E2.3b: executor, `unknown` reconciliation (`reconcile_refund`), quarantine, audit, rejection and expiry blocking at decision/execute time. Confirm exact gap against PROJECT.md section 10 when starting. |
| 3 | E4.5 Sweeper for approved-but-never-executed refunds | main + safety-reviewer | test kills the task after commit; sweeper completes it exactly once | S | No keys. Small, same stable key. |
| 4 | E4.4 Operator release of quarantined refunds | main + safety-reviewer | release never frees money the provider later applies (late-landing test) | M | No keys. Money-critical; hq_owner only, audited. |
| 5 | E3.1 LLM provider factory | main | fake-model tests pass; `make llm-smoke` returns JSON | M | Tests with fakes need no keys; `llm-smoke` is blocked until the human puts GEMINI and GROQ keys in `.env`. |
| 6 | E4.1 Approve node with `interrupt()`, Postgres checkpointer (schema `lg`), auto-approve rules, resume | main + safety-reviewer | interrupt/resume tests pass | M | Needs langgraph + checkpointer deps and a migration for schema `lg` (app role grants, safety review). Can use a fake model, so no keys. Needs E4.2 pieces for what happens after approval. |
| 7 | E3.3 Agents + LangGraph classify -> investigate/policy -> propose | main | routing tests pass; `pytest -m live -k proposal` passes 3 scenarios per tenant | L | Depends on E3.1, E3.2, E4.1. Live part blocked on keys. Agents read tools only (rule 4). |
| 8 | E4.3 Chaos suite | main + safety-reviewer | `make test-chaos` zero duplicates; safety clean | L | Last: needs the full path (E3.3, E4.1, E4.2, E4.5). Timeout 0.3, double submit, worker kill, two managers, 50 cases per tenant. |

Size: 2 S/M-small, 4 M, 3 L-ish (E3.2, E3.3, E4.3). Roughly 3 L + 4 M + 1 S in about 6 working days with 5 safety reviews and slow Neon suites. Tight but plausible because the order lets no-key work run first.

### Blockers and dependencies
- Human: put `.env` in place with GEMINI and GROQ keys. Blocks `make llm-smoke` (E3.1) and the live tests of E3.3. Without it E3.3 can only be verified with fakes, so its done-when stays [~].
- Human: `.env` also needed for `make db-check` and browsing `make api` (E0.3 still [~]); rotate `neondb_owner` password.
- Dependencies: new packages (sentence-transformers/torch, pgvector, langgraph and its Postgres checkpointer) need human OK per PROMPTS.md. PROJECT.md section 4 lists embeddings (bge-small via sentence-transformers) and pgvector, so this is likely already approved; langgraph is in the stack in CLAUDE.md. Ask once, up front, so E3.2 is not stalled. Download size of torch/bge model is a practical risk on this machine.
- Infra: Neon drops connections and suites take ~18 min; budget for reruns, run narrow test selections during development.
- Merge: `main` still awaits the human's test -> main review of Sprint 1.

### Scope verdict
Fits only if the keys arrive by about 2026-10-28. If not, at that point E3.3 live tests and E4.3 move to Sprint 3 first; tests and safety review are never dropped, and E8 stays dropped. Note Sprint 3 already holds UI and evals, so a slip there threatens the 2026-11-06 ship; E4.3 has the least downstream dependency inside Sprint 2 but is a safety proof, so prefer cutting E4.4 (operator tool, not on the demo path) to Sprint 3 before E4.3.

### At risk
None yet (sprint just started). Watch: E3.3 (three dependencies plus keys), E4.3 (last in the chain).

## Stand-ups

### 2026-10-25 (scrum-master, evidence from main session and git log)
Day 2 of 8 (about 25% of time used). Plan order changed: E3.1, E3.2, E3.3 went first because keys arrived; E4 work is still ahead.

- E3.1 LLM factory: done [f0bbde2, 14601b9]. Live smoke returned JSON (groq, 1 call). Ticked.
- E3.2 Policies + RAG: done [3312f00]. Ticked.
- E3.3 Agents + LangGraph: in progress [2d54e86, 95674ea]. Routing 50 passed; Flight 2 (real Groq+Gemini) 18 cases passed. Next: add the `pytest -m live -k proposal` test (3 scenarios per tenant). Stays [~] until it exists and passes.
- Also done, unplanned: E5.0 minimal demo UI [d61e0d4], 24 UI tests passed; E5.1-E5.3 stay [ ] until a browser click-through.
- E4.2: partial (executor, reconciliation, honest case_status exist). Next: verifier, domain events, tickets. E4.1, E4.3, E4.4, E4.5, E4.6 not started. No blockers; E0.3 only needs the human to rotate the owner password.
- Suite before Flight 2 fixes: 520 passed (1 Neon drop, passed on rerun), isolation 157 passed. Not re-run at this stand-up (a run was in progress on the shared test DB).

Flight 2 findings (all fixed): AI proposed 100% refunds from policy text (business-rule ceiling c1cc356); retired model names; free-text POST /cases crash; provider-error fallback.

Risk assessment: 3 of 9 planned stories done (E3.1, E3.2, plus most of E3.3) with 25% of time used, but all the safety-critical work remains: E4.1, E4.3, E4.4, E4.5, E4.6 and the rest of E4.2, plus the E3.3 live marker. Keys are in, so the blocker named in planning is gone. Status: AMBER. E4.3 (chaos) depends on E4.1/E4.2/E4.5, so it is the story at risk. Re-scope trigger: if E4.1 and E4.5 are not done by 2026-10-28, move E4.4 to Sprint 3 first (not on the demo path), then E4.6. Never drop E4.3 or safety review; E8 stays dropped. Suggested order: E4.1, E4.5, E4.2 remainder, E4.6, E3.3 live marker, E4.3, then E4.4.

Scorecard note for this stretch: safety-reviewer found real issues on each pass (see E3.3 safety-review fix commit c72d56a and hardening 15304d9). The live flight found the over-refund gap that scripted-LLM tests missed (c1cc356), so keep live flights in the Sprint 2 exit criteria. Full scorecard at sprint end.

## Dispatch board (2026-10-26, scrum-master)
The main session dispatches exactly per this board and reports back for ticking. Sprint 2 ends 2026-10-31 (day 3 of 8 used, about 38%). No DB suites were run by the scrum master for this entry; statuses come from the main session.

| Story | Owner agent | Branch | Test DB | Status | Done-when check | Gates before merge | Merge order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E5.4 login + API contract (migration 0013) | builder (general-purpose) | feature/E5.4-login-api | resolvedesk_test | running, near done | auth + contract API tests pass for both tenants | test-runner narrow then full; safety-reviewer (auth, lockout, tenancy); then scrum-master tick | 1 |
| E4.6 + E4.5 + E4.4 execution (maybe 0014) | builder | feature/E4-execution | resolvedesk_t1 | running | voucher issued exactly once with stable key; sweeper completes a killed task exactly once; release never frees money a late landing applies | test-runner narrow (executor, sweeper, release) then full; safety-reviewer (money, quarantine, hq_owner only); scrum-master tick | 2 |
| E4.1 + E4.2 workflow (maybe 0015) | builder | feature/E4-workflow | resolvedesk_t2 | running | interrupt/resume tests pass; rejection + expiry tests pass; R3 negative message test | test-runner narrow then full; safety-reviewer (approvals, schema lg, migration); scrum-master tick | 3 |
| E4.3 chaos suite | builder | feature/E4.3-chaos | resolvedesk_t4 | running | `make test-chaos` zero duplicates | test-runner (`make test-chaos`, full); safety-reviewer, run against the merged 4.5/4.4/4.1 code; scrum-master tick | 4 |
| E6.1-E6.3 evals + E3.3 live marker test | builder | feature/E6-evals | resolvedesk_t3 | running | `make eval` prints per-tenant table with baseline; `pytest -m live -k proposal` 3 scenarios per tenant | test-runner; eval-runner (first baseline after merge, repeat after any agent or prompt change); scrum-master tick | 5 |
| E5.5 / E5.6 React app + manuals | main session (Chrome) | merged b3ad76a | n/a | stays [~] | browser click-through: Spice Route refund and BrewCo voucher; manual steps match | after E5.4 merged: main session click-through, then scrum-master tick | after 1 |
| E7.1 README + demo script | main (+ business-analyst for domain wording) | feature/E7.1-readme | none | not started | README written, R6/R10/R13 included | scrum-master tick; start once evals give numbers | after 5 |
| E7.2 clean-clone check | main | none (fresh clone) | fresh | not started | fresh clone + README reaches working demo | test-runner full on the clone | last |
| Release candidate | main | test | resolvedesk_test | not started | full `make test`, isolation, chaos, eval, lint all green; every [~] resolved or carried | all gates; safety-reviewer final pass over the sprint's money/auth diff; eval-runner; scrum-master review, then human test -> main review | final |

Merge-order reasoning:
1. E5.4 first: nearly done, owns migration 0013, and unblocks the E5.5 click-through (the most visible remaining risk). Its safety review also covers the login everything else relies on.
2. Execution (E4.6/E4.5/E4.4) second: money-critical, smallest dependency surface, and chaos must test the sweeper and release code.
3. Workflow (E4.1/E4.2) third: it wires approve/resume around the executor, so it should rebase onto the final executor behaviour (voucher execution, sweeper) rather than the reverse. Re-chain its migration after execution's.
4. Chaos fourth: it needs the merged path (workflow + sweeper + release) to prove anything; building it on a branch is fine, merging early would test an incomplete system.
5. Evals last: independent of the others, but its numbers and the live marker only mean something on the merged agents/executor, and eval-runner then runs once on the final code.

Rules for every merge: main session re-chains Alembic revisions (0013 E5.4, 0014 execution if needed, 0015 workflow) and reruns the narrow suite after each rebase; one merge at a time on `test`; each branch uses its own DB so runs do not collide, and the full suite before a merge runs on resolvedesk_test only after the previous merge is in. A safety-reviewer finding blocks the merge until fixed and re-reviewed.

Re-scope triggers (unchanged): if E4.1 and E4.5 are not merged by 2026-10-28, move E4.4 to Sprint 3 first, then E4.6; E4.3 and safety review never move; E8 stays dropped.

### Triage of business-analyst recommendations (docs/research/market.md R1-R13)
ACCEPT = added to an existing story's notes in EPICS.md. NEW = new story added as [ ]. DEFER = later. H = needs the human's decision.

| R | Decision | Where | H? |
| --- | --- | --- | --- |
| R1 injection/escalation eval scenarios | ACCEPT | E6.2 (in flight; main session passes the list to the builder) | no |
| R2 injection scenario in live marker | ACCEPT | E3.3 | no |
| R3 message vs case_status negative test | ACCEPT | E4.2 | no |
| R4 fair-use signal | NEW E2.5, Sprint 3 | EPICS section E2b | yes (Q3) |
| R5 approval card fields + 48 h / 1 month SLA marker | ACCEPT | E5.5 (E5.2 click-through) | no |
| R6 README framing, competitor paragraph, assumed rates | ACCEPT | E7.1 | yes (Q1, Q7) |
| R7 graduated tiers, BrewCo ladder, voucher cap | NEW E3.5, Sprint 3 | EPICS section E2b | yes (Q2, Q4) |
| R8 double-charge policy wording citing bank timeline | NEW E3.5 (same story) | EPICS section E2b | yes (Q6) |
| R9 DPDP note + PII minimisation | NEW E3.4, Sprint 3; deletion workflow DEFER | EPICS section E2b | yes (accept as story) |
| R10 ops-head demo script | ACCEPT | E7.1 | no |
| R11 headline eval metrics | ACCEPT | E6.1 | no |
| R12 simulator parameter tags | DEFER (docs only, low impact, data already seeded) | none | yes (Q5) |
| R13 illustrative pricing slide | ACCEPT | E7.1 (first to cut) | no |

Capacity: E2.5, E3.4, E3.5 land in Sprint 3 (2026-11-02 to 11-04), which already holds the click-through and evals. All are S/M. If Sprint 2 slips, cut R13, then E3.4, before E2.5. E3.5 is blocked on human Q2 and Q4; E6.2 late-delivery scenarios stay on the current 50% rule until then.

### Decisions for the human (BA open questions)
1. Aggregator payments: frame the mock in the README as the tenant's own gateway plus a policy clause for aggregator orders (BA recommendation), or model aggregator-refunded orders? Recommend the former.
2. Keep the flat 50% for more than 45 min late, or allow graduated tiers (changes scenario sr-late-001)? Blocks E3.5.
3. Fair-use default 3 grants in 30 days as a tenant setting; accept R4 (E2.5) and R9 (E3.4) as stories?
4. Auto-approve voucher cap about Rs 150: vertical-pack default or per tenant? Blocks E3.5.
5. BrewCo order values: use the BA's mid-market estimates or supply a real menu? (R12 deferred pending this.)
6. Verify E-Commerce Rules, RBI TAT and the DPDP breach window against official texts before the README quotes them as law?
7. Run deep-research on Ada, official Sierra/Freddy docs, Yellow.ai/Haptik pricing before the README quotes competitor features or prices, or keep claims hedged?
8. RESOLVED by 950facd: the spec now says the React web app is the product UI (human decision 2026-10-25). No action.

## Risk assessment update (2026-10-26)
Interruption: on 2026-10-25 every agent stopped on an account rate limit; work resumed 2026-10-26 on a new account. Effective loss is about one working day. Day 3 of 8 (about 38% of time used).

Evidence: E3.1, E3.2, E0.6 ticked; E5.5/E5.6 merged (44 frontend tests, build, 292 backend unit tests pass) but not click-through verified; E3.3 [~]; five builders running in parallel on separate worktrees and DBs.

Status: AMBER, trending better thanks to parallelism, with new risks:
- Parallel branches converge on migrations and the executor/workflow code: high re-chain and conflict risk; mitigated by the one-at-a-time merge order.
- Safety review is the bottleneck: four of five branches need it (E5.4, execution, workflow, chaos). Queue in merge order; do not batch.
- Neon slowness (~18 min full suite) plus five concurrent DBs may cause connection drops; a single drop that passes on rerun is not a failure.
- Rate limits may recur on the new account: if agents stop again, hold a stand-up first, then resume in merge order.
- No story is formally at risk yet (more than 25% of time remains). Watch list: E4.3 chaos (provable only after three merges) and the E5.5 click-through (waits for E5.4). Both become at risk on 2026-10-29 if their predecessors are not merged.
- E7.1 must not wait for the very end because it needs eval numbers.

## Stand-up (2026-10-26, evening)
- Done: 71592bd merged E4.1/E4.2/E4.4/E4.5/E4.6 on one execution path (930 passed, 9 skipped, chaos 2 passed, ruff clean at ec2a80a; safety mediums fixed). Evals edd25e5: brewco 100%, spice_route 91% (baseline 91%/75%), 0 over-rule proposals. Browser click-through 2026-10-25 passed for both tenants. Ticked E4.1, E4.4-E4.6, E6.1-E6.3.
- Next: E7.1 README + demo script (main session, in progress); E7.2 clean-clone check; re-run make eval including sr-quality-002; test to main release review; finish E4.2 (subscribers, tickets) and E4.3 (50 cases/tenant).
- Blocked/user: rotate the Neon owner password.
- Follow-ups: replace error-prefix "never sent" detection in app/engine/verifier.py with an explicit flag; demo seed should keep packs current (click-through needed seed --no-history plus scripts.sweep).

- Update (same day): E7.1 README done (fc7bb5f), ticked. E7.2 clean clone at fc7bb5f mostly passes (make flight fixed in 90fd4a1 after it rejected confirmed auto-approved vouchers); stays [~] until API+web are started from the clone and clicked through.

## Review
_to fill at sprint end_

## Retro
_to fill at sprint end_

## Scorecard
_to fill at sprint end_
