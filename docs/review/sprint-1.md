# Review guide: test -> main (Sprint 0-1 so far)

Open the PR: https://github.com/anurag-singh2001/ResolveDesk/compare/main...test?expand=1

Most worth your eyes (money, tenancy, approvals):
1. `migrations/versions/0009_engine_hardening.py`: what the DB itself refuses (approvals immutable, execution needs an APPROVED approval of the same proposal, one refund reservation per proposal matching its amount).
2. `migrations/versions/0010_maintenance_role.py` + `docs/DECISIONS.md` (2026-10-24): Neon's owner bypasses RLS; reseeds now run as `resolvedesk_maint` (NOBYPASSRLS).
3. `app/engine/proposals.py`: payload hash + params must belong to the case.
4. `app/core/tenancy.py` `visible_orders()` and `app/api/deps.py`: who sees what; tenant only from the token.
5. `mocks/base.py`: idempotency contract the refund executor will rely on.

Results at merge: make lint clean, make test 297 passed, make test-isolation 149 passed.
Not yet done: E2.3b (refund executor), E2.3c, E2.4 (moved to Sprint 2), Day 3+ (LLM, RAG, UI, evals).
