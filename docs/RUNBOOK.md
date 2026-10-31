# ResolveDesk runbook

How to start, demo, reset and troubleshoot the system on a dev machine (Windows + Git Bash, Neon
Postgres). For what the system handles, see [SCENARIOS.md](SCENARIOS.md); for setup from scratch,
the README "Setup" section.

## Start

```bash
make db-check            # Neon reachable; app role cannot bypass RLS
make migrate             # runs Alembic, then refreshes tenant packs (APP_ENV=dev)
make api                 # terminal 1: http://localhost:8000 (Swagger at /docs)
make web                 # terminal 2: http://localhost:5173
```

Recommended `.env` for a demo: `APP_ENV=dev`, `DEMO_AUTH=true` (login page lists demo accounts),
`ENGINE_MODE=agents`, `LLM_PROVIDER=groq`, `LLM_FALLBACK_PROVIDER=gemini`,
`MOCK_STATE_FILE=var/mock_state.json` (mock providers survive an API restart).

Check it is up: `curl http://localhost:8000/health` → `{"status":"ok"}`.

## Stop

Ctrl+C in both terminals. If a port stays busy, see "Port 5173 already in use" below.

## Demo (about 10 minutes)

Follow the README "Demo script" (steps 1–7): refund approved and confirmed; voucher auto-approved;
outlet scope; payment timeout shown honestly; repeat complainer; the AI asks and the customer
answers; insights and a win-back campaign. Extra Sprint 5 screens: customer **Privacy & data**
(consent switch, download, erasure request) and the reply language (it follows what the customer writes).

Before showing step 4 (timeout) or the growth verdict, rehearse once. Reset the Demo controls clock
afterwards.

## Reset

| Goal | Command |
| --- | --- |
| Finish or reconcile interrupted payouts | `make sweep` (or Demo controls → Run sweeper) |
| Clear mock provider records | delete `var/mock_state.json` and restart the API |
| Reload tenant settings/policies only | `make refresh` (dev) |
| Reload all demo data (destructive) | `make seed TENANT=all` |
| Simulated clock back to now | Demo controls → Reset clock (Reset demo there is disabled on purpose; use `make seed`) |
| Retention job | `make retention` (dry run, counts only); `make retention APPLY=1` redacts |

## Tests

| Suite | Command | Notes |
| --- | --- | --- |
| Lint | `make lint` | |
| Unit | `uv run pytest tests/unit` | no DB needed (also runs in CI) |
| Everything except chaos | `make test` | needs Neon; ~75 min |
| Isolation | `make test-isolation` | |
| Chaos | `make test-chaos` | ~13 min |
| Web | `make web-test` | |
| Evals | `make eval` | needs LLM keys and a **scratch** DB (it refuses to reseed the demo DB) |

Point tests at a separate database (`TEST_DATABASE_URL`), never the demo one.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Login page shows one giant icon, no styling | a stale Vite dev server is still running (often on 5173 while the new one took 5174) | stop all `node ... vite` processes, delete `web/node_modules/.vite`, `make web` again |
| Port 5173/8000 already in use | an old server is still running | find it: PowerShell `Get-NetTCPConnection -LocalPort 5173`, stop that process |
| Every customer reply returns 500 | code mismatch after merging parallel branches | pull the latest `test`/`main`; this was fixed in 59a711e |
| Refund shows "provider has no record" after a restart | mocks were in-memory | set `MOCK_STATE_FILE`, or finish a demo flow before restarting |
| Growth page shows no signals | demo history ends before today | fixed: the job measures up to the latest order (eb51a70); pull latest |
| Many tests error at setup with "server closed the connection" | Neon dropped the connection | re-run; use a different scratch DB if it repeats |
| Background runs get killed | the machine ran low on memory | run at most ~2 heavy processes (pytest, servers) at once; split long suites into batches |
| A case stuck on "Waiting for your reply" after replying | the reply's background resume was lost | `make sweep` resumes it or hands it to a person |
| A case says "needs a check" | approval expired, provider mismatch, or a refused/stuck payout | staff: Approvals / case events; `make sweep`; release a quarantined refund only after the provider confirms no record |
| `make eval` refuses to run | DATABASE_URL points at the demo DB | point it at a scratch DB |
| `make retention` exits 2 | APP_ENV not set in the process environment | `APP_ENV=dev make retention` |

## Clearing a case the AI could not handle (the stuck demo case O0005779)

A case whose reason reads "AI unavailable: MissingAPIKey" (or `ProviderFailed`) came to a person only because the models could not run. Order O0005779 is such a case in the demo data. Clear it with S7.4:

1. Put a working LLM key in `.env` (`GEMINI_API_KEY`, or `GROQ_API_KEY`; or set the providers to Ollama) and restart the API (`make api`).
2. Sign in as the owner (or a manager whose scope covers the order) and open the case from Cases (order O0005779). The side panel shows "The AI was unavailable" and a button.
3. Press **Run the AI again**. The case goes back to "investigating", is classified and a remedy is proposed (or a clarifying question asked); the page updates by itself. A double click starts one run.
4. Approve or decline the proposal as usual. If the keys are still missing, the case escalates again with the same reason and the button comes back; nothing else changes.

Without pressing anything, `make sweep` (or the running sweeper) retries such cases on its own once the providers can be built, at most 3 times per case, 5, 10 and 20 minutes after the last escalation. Audit trail: `case.ai_rerun_requested` and `case.ai_rerun_result` (codes only, no message text). Via API: `POST /cases/{id}/rerun-ai` (staff only; 409 if the case did not escalate for an AI failure). Never edit the demo database by hand to clear it.

## Cases showing Owner "Unassigned" (made before S7.2)

Cases that were escalated or awaiting approval before case ownership existed have no owner. `make sweep` (and the running sweeper) gives each one an owner by the same rule as new cases (outlet manager, else franchisee owner, else HQ) and writes a `case.owner_assigned` audit row per case. Only the owner fields change. It is idempotent: an owner already set, by the engine or by a person, is never replaced, and a second run reports `owners assigned 0`. Closed or resolved cases stay unowned on purpose.

## Safety reminders

- Never run tests or evals against the demo/production database.
- Never print or commit `.env` or database URLs.
- `make retention APPLY=1` is irreversible; run the dry run first.
- Merging `test` into `main` needs the owner's go-ahead.
