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

## Review
_to fill at sprint end_

## Retro
_to fill at sprint end_

## Scorecard
_to fill at sprint end_
