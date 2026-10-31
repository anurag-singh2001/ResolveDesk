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

## Platform admin (S9.1)

The platform admin is one operator who sees cross-tenant counts and never a customer record. It is OFF until you set all four variables in `.env` (never commit them). With any one missing, blank, or the API restarted without them, every `/platform/...` route answers 404.

| Variable | What it is |
| --- | --- |
| `PLATFORM_ADMIN_EMAIL` | the operator's sign-in email |
| `PLATFORM_ADMIN_PASSWORD_HASH` | a bcrypt hash of the password (not the password) |
| `PLATFORM_JWT_SECRET` | signing key for platform tokens: at least 32 characters, random, and NOT the same as `JWT_SECRET` (never the dev secret). Without it the feature stays off. e.g. `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `PLATFORM_DATABASE_URL` | connection string for the DB role `resolvedesk_platform` (below) |

Optional: `PLATFORM_JWT_TTL_MINUTES` (default 30, token life is the smaller of this and `JWT_TTL_MINUTES`).

1. Make the hash (bcrypt hashes contain `$`; put it in `.env` between single quotes if your shell expands it): `uv run python -c "import getpass; from app.core.passwords import hash_password; print(hash_password(getpass.getpass()))"`.
2. Migration 0028 creates the role `resolvedesk_platform` as NOLOGIN with no table rights. Give it a login and a strong password as the DB owner (once per database, the password stays out of the repo): `ALTER ROLE resolvedesk_platform LOGIN PASSWORD '<strong password>';`. Build `PLATFORM_DATABASE_URL` from your existing app URL with that user and password (same host and database, pooled endpoint is fine).
3. Sign in: `POST /platform/auth/login` with `{"email", "password"}`; use the returned bearer token on `GET /platform/tenants`, `/platform/cases`, `/platform/approvals`, `/platform/activity`. A tenant token gets 403 there; a platform token gets 401 on every tenant route.
4. Five login attempts without a success in 15 minutes give 429. The counter is global (not per IP) and lives in one API process: an attacker can lock the operator out for 15 minutes, and a restart or a second process resets it. So use a long, random, high-entropy password. Failed logins and lockouts are logged (no email or password).
5. The DB role and its password are per database CLUSTER (roles are cluster-wide on Neon): the demo and test databases share one `resolvedesk_platform` and one password, so a password set for one applies to both.
6. Every read writes a row to `platform_audit_events` (actor and route only), readable by the DB owner.

The role can read only the `platform_*_v` aggregate views (counts by tenant slug, day and status code; no names, phones, messages or ids). Later stories add their views the same way.

## Clearing a case the AI could not handle (the stuck demo case O0005779)

A case whose reason reads "AI unavailable: MissingAPIKey" (or `ProviderFailed`) came to a person only because the models could not run. Order O0005779 is such a case in the demo data. Clear it with S7.4:

1. Put a working LLM key in `.env` (`GEMINI_API_KEY`, or `GROQ_API_KEY`; or set the providers to Ollama) and restart the API (`make api`).
2. Sign in as the owner (or a manager whose scope covers the order) and open the case from Cases (order O0005779). The side panel shows "The AI was unavailable" and a button.
3. Press **Run the AI again**. The case goes back to "investigating", is classified and a remedy is proposed (or a clarifying question asked); the page updates by itself. A double click starts one run.
4. Approve or decline the proposal as usual. If the keys are still missing, the case escalates again with the same reason and the button comes back; nothing else changes.

Without pressing anything, `make sweep` (or the running sweeper) retries such cases on its own once the providers can be built, at most 3 times per case, 5, 10 and 20 minutes after the last escalation. Audit trail: `case.ai_rerun_requested` and `case.ai_rerun_result` (codes only, no message text). Via API: `POST /cases/{id}/rerun-ai` (staff only; 409 if the case did not escalate for an AI failure). Never edit the demo database by hand to clear it.

## Cases showing Owner "Unassigned" (made before S7.2)

Cases that were escalated or awaiting approval before case ownership existed have no owner. `make sweep` (and the running sweeper) gives each one an owner by the same rule as new cases (outlet manager, else franchisee owner, else HQ) and writes a `case.owner_assigned` audit row per case. Only the owner fields change. It is idempotent: an owner already set, by the engine or by a person, is never replaced, and a second run reports `owners assigned 0`. Closed or resolved cases stay unowned on purpose.
## LLM usage and job runs (S9.2)

Two tables, filled automatically, nothing to switch on:

- `llm_usage`: after each agent run, one row per role, provider and model with calls, input and output tokens, summed latency (ms), failures, outcome (`ok`, `error`, `fallback_used`) and the failing exception class. Cost is `estimated_cost_micro_paise` (1 paise = 1,000,000), an ESTIMATE from `LLM_PRICES_PAISE_PER_MILLION` (JSON, `{"gemini/<model>": [input, output]}` in whole paise per million tokens). Unlisted models cost 0. Check the provider's invoice for real spend.
- `job_runs`: one row per tenant per job: `sweep`, `retention_dry_run` (or `retention_apply`), `growth_nightly`, with `running`, `ok` or `failed`, integer counts and the error class. A row stuck on `running` means the process died mid-job; the next start of the same job for that tenant marks any `running` row older than 6 hours as `failed` with error class `Abandoned`.
- A run killed before it finishes loses its token counters (written once, at the end of the run), so usage totals are a floor, not exact.
- Neither table holds prompt, reply or message text, and exception messages are not stored. Recording is best effort: if it fails, a warning with the exception class is logged and the run or job carries on.

## Job scheduler (S9.3)

The API can run the recurring jobs itself. It is OFF unless you set `SCHEDULER_ENABLED=true` (in `.env` or the host's environment); dev, test and prod all default to off, and tests never start it. Restart the API after changing any of these.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SCHEDULER_ENABLED` | false | master switch |
| `SCHEDULER_SWEEP_INTERVAL_SECONDS` | 300 | crash-recovery sweep (job `sweep`); 0 = off |
| `SCHEDULER_RETENTION_INTERVAL_SECONDS` | 86400 | retention check; 0 = off |
| `SCHEDULER_RETENTION_APPLY` | false | false = DRY RUN only (job `retention_dry_run`). true really redacts (job `retention_apply`), irreversible: run `make retention` and read the numbers first |
| `SCHEDULER_GROWTH_INTERVAL_SECONDS` | 86400 | growth nightly (job `growth_nightly`): stores signals only, sends nothing; 0 = off |
| `SCHEDULER_PACK_REFRESH_INTERVAL_SECONDS` | 0 | pack refresh (`pack_refresh`), off by default; runs only with `APP_ENV=dev` and `MIGRATION_DATABASE_URL`, otherwise it is recorded as skipped |
| `SCHEDULER_TICK_SECONDS` | 30 | how often the loop looks at the clock |
| `SCHEDULER_STARTUP_DELAY_SECONDS` | 60 | first run this long after boot |
| `SCHEDULER_SHUTDOWN_GRACE_SECONDS` | 20 | how long a stop waits for running jobs |

- Where to look: tenant jobs write `job_runs` (one row per tenant per run: `ok`, `failed`, `skipped`); pack refresh and any failure that is not tied to a tenant write `platform_job_runs` (the platform role sees counts through `platform_jobs_v`). Rows hold counts and an exception class, never text.
- No overlap: if a run is still going when the next one is due, the tick is recorded as `skipped`. With two app instances, a Postgres advisory lock lets only one run a given job at a time; the other records `skipped`. If that database connection drops mid-run the lock is lost, so two instances could briefly run the same (idempotent) job.
- Catch-up after sleep: the scheduler only exists while the app process is awake. A free-tier host that sleeps when idle runs NOTHING while asleep, so daily jobs can be skipped for days. When the app wakes, the first run of each job comes `SCHEDULER_STARTUP_DELAY_SECONDS` after boot, then every interval; a long gap costs one run, never a burst of missed runs. For guaranteed timing use a host that stays up, or call `make sweep` / `make retention` from an external cron.
- Stopping the app waits up to the grace period for running jobs; any tenant row still `running` after that is closed as `failed` with error `Shutdown`. A row left `running` by a killed process is closed as `Abandoned` after 6 hours by the next run of that job.
- If the scheduler cannot start (for example no database URL) the API still starts and logs `job scheduler not started: <error class>`.
## Safety reminders

- Never run tests or evals against the demo/production database.
- Never print or commit `.env` or database URLs.
- `make retention APPLY=1` is irreversible; run the dry run first.
- Merging `test` into `main` needs the owner's go-ahead.
