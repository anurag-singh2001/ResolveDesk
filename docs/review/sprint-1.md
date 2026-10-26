# Review guide: test -> main (Sprint 0-1, complete)

Open the PR: https://github.com/anurag-singh2001/ResolveDesk/compare/main...test?expand=1

Most worth your eyes (money, tenancy, approvals):
1. `migrations/versions/0009_engine_hardening.py`: what the DB itself refuses (approvals immutable, execution needs an APPROVED approval of the same proposal, one refund reservation per proposal matching its amount).
2. `migrations/versions/0010_maintenance_role.py` + `docs/DECISIONS.md` (2026-10-24): Neon's owner bypasses RLS; reseeds now run as `resolvedesk_maint` (NOBYPASSRLS).
3. `app/engine/proposals.py`: payload hash + params must belong to the case.
4. `app/core/tenancy.py` `visible_orders()` and `app/api/deps.py`: who sees what; tenant only from the token.
5. `mocks/base.py`: idempotency contract the refund executor will rely on.

Added since the first version of this guide:
6. `app/engine/executor.py` (E2.3b): reserve, send with a stable key, then persist. Read the quarantine path (`pending_reconciliation` keeps the money held; a late success is still recorded) and forward-only status writes. This is where a double refund was found and fixed.
7. `app/engine/eligibility.py` and `app/engine/approvals.py` (E2.3b): deterministic eligibility, approval bound to the payload hash, expiry, one decision per approval.
8. `app/api` cases and approvals routes (E2.3c): `POST /cases` (no LLM), `GET /approvals`, `POST /approvals/{id}/decision`; other-tenant ids return 404, second decision returns 409. Try it with `make api` and open `/docs` once `.env` exists.
9. `.claude/skills/add-action` and `add-connector` (E2.4): docs only, written from the real code.

Results (main session, latest): make lint clean, make test 374 passed (1 Neon connection drop, passed on rerun), make test-isolation 149 passed.
Known gaps, tracked in Sprint 2: E4.4 operator release of quarantined refunds, E4.5 sweeper for approved-but-never-executed refunds, verifier and tickets (E4.2). Not started: LLM, RAG, UI, evals (Day 3+).
Not done by the human yet: `.env`, owner password rotation (E0.3).
