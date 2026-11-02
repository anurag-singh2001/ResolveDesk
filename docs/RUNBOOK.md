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

## Demo (about 15 minutes)

Follow [DEMO-SCRIPT.md](DEMO-SCRIPT.md): five support steps (refund approved and confirmed, voucher
auto-approved, outlet scope, payment timeout shown honestly, the AI asks and the customer answers),
then a short tour per role (customer, location manager, franchisee owner, HQ owner, platform
operator) on both tenants. Growth is on for both tenants; the full campaign walk is proven on
BrewCo only.

Before showing the timeout or the growth verdict, rehearse once. Reset the Demo controls clock
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
| Lint | `make lint` | `ruff check` and `ruff format --check` |
| Unit | `uv run pytest tests/unit` | no DB needed (also runs in CI) |
| Unit and integration | `make test` | **Not a full run.** Excludes the isolation, chaos and live tests (`-m "not isolation and not chaos and not live"`). Needs Neon |
| Isolation | `make test-isolation` | |
| Chaos | `make test-chaos` | |
| Web | `make web-test` | vitest; `cd web && npx tsc --noEmit -p .` for types |
| Evals | `make eval` | needs LLM keys and a **scratch** DB (it refuses to reseed the demo DB) |
| Full run, in batches | `scripts/run_test_batches.py` | see below |

Point tests at a separate database (`TEST_DATABASE_URL`), never the demo one.

### Full run in batches (`scripts/run_test_batches.py`)

One pytest process over everything takes over four hours against the remote database, and a network
drop spoils what is left. The runner splits `tests/unit` (one batch) and the `chaos`, `integration`
and `isolation` folders (about 60 tests per batch) into named batches, runs them in parallel, saves
each result as it finishes and retries a batch up to 3 times if it was lost to the network. A batch
with no output for 15 minutes is treated as hung and killed. It does not run vitest or `tests/live`.

```bash
uv run python -m scripts.run_test_batches --env a.env --env b.env    # start, or resume
uv run python -m scripts.run_test_batches --env a.env --rerun-failed # rerun only failed files
uv run python -m scripts.run_test_batches --status                   # print progress
uv run python -m scripts.run_test_batches --fresh --env a.env        # forget saved results
uv run python -m scripts.run_test_batches --env a.env --only unit    # chosen batches
```

- **One `--env` file per database; one worker per file.** Each file has that database's settings as
  `KEY=value` lines. Two workers must never share a database, so give each its own. Keep the files
  out of git and do not paste them anywhere.
- **Where to look:** `.test-runs/status.md` (a table of batches: status, passed, failed, time, and
  the failing tests with a short reason), `.test-runs/state.json` and `.test-runs/logs/` (one log and
  junit file per try). Database addresses in reasons are replaced with `<hidden>`. The folder is
  git-ignored.
- **Resume:** run the same command again; batches that passed are skipped. `--rerun-failed` reruns
  only the files that failed, and keeps the earlier passed count.
- **`--fresh`** forgets saved results. Results belong to one commit: after you commit or pull, the
  runner refuses with "use --fresh". Use `--fresh` for a final run on the latest code.
- A run is green only when every batch says `passed`. `make test` passing is not that.

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

## Platform portal (S9.5)

Open `http://localhost:5173/platform` (the web app). It has its own sign in (the platform admin email and password from the section above), its own shell and no business navigation. The token is kept in `sessionStorage` under `resolvedesk.platform.session`, separate from the business token; a 401 or 403 clears it. If the platform admin is not set up, the sign in answers 404 and the page says "The platform portal is not enabled".

Pages: Health (businesses, cases, approvals, last system activity), Scheduled jobs (`GET /platform/jobs`, `GET /platform/scheduler-runs`; run history only, it cannot start or stop a job), Logs and alerts (`GET /platform/logs`, `/platform/alerts`), AI performance (`GET /platform/ai-usage`) and Scenario lab (below). Migration 0034 adds the views `platform_llm_usage_v` and `platform_job_runs_v` (sums and counts by business slug, day, provider, model, purpose, outcome, job, status; no ids, no text, no error class), granted only to `resolvedesk_platform`. Cost shows as an estimate (micro-paise rounded down to whole paise).

### Scenario lab (S10.1)

Scenario lab edits the scenario files in `tenants/<slug>/scenarios/` (checked against the same rules the evals use) and runs a few chosen ones, one run at a time, with the real models, against a **scratch database**, never the demo data. With no scratch database set up the page says so and you can still edit. Held-out scenarios are shown read-only and cannot be saved. A run compares with the last full eval report. The last real run (S10.1) stalled and is still to be retried, so treat running from the lab as unproven.

### Demo rows in the portal

On the demo the portal's Scheduled jobs, AI performance, Logs and Alerts pages show **seeded demo rows** from `scripts/seed_portal_demo.py` (see "Job scheduler" below), labelled `demo`. They are not real activity; do not read them as results.

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
| `SCHEDULER_TICK_SECONDS` | 30 | how often the loop looks at the clock |
| `SCHEDULER_STARTUP_DELAY_SECONDS` | 60 | first run this long after boot |
| `SCHEDULER_SHUTDOWN_GRACE_SECONDS` | 10 | how long a stop waits for running jobs |

- Where to look: tenant jobs write `job_runs` (one row per tenant per run: `ok`, `failed`, `skipped`); a failure that is not tied to a tenant (for example the lease or the tenant list) writes `platform_job_runs` (the platform role sees counts through `platform_jobs_v`). Rows hold counts and an exception class, never text.
- No overlap: if a run is still going when the next one is due, the tick is recorded as `skipped`. Skipped rows are written at most once per job per hour. With two app instances, a lease row in `job_leases` (renewed every 40 s, expires after 120 s without a heartbeat, deleted when the job ends) lets only one run a given job at a time; the other records `skipped`. A dead instance's lease can be taken over after it expires. A job that outlives its lease (database unreachable for 2 minutes) could be started twice; all three jobs are safe to repeat.
- Catch-up after sleep: the scheduler only exists while the app process is awake. A free-tier host that sleeps when idle runs NOTHING while asleep, so daily jobs can be skipped for days. When the app wakes, the first run of each job comes `SCHEDULER_STARTUP_DELAY_SECONDS` after boot, then every interval; a long gap costs one run, never a burst of missed runs. For guaranteed timing use a host that stays up, or call `make sweep` / `make retention` from an external cron.
- Stopping the app waits up to the grace period for running jobs; any tenant row still `running` after that is closed as `failed` with error `Shutdown`. A row left `running` by a killed process is closed as `Abandoned` after 6 hours by the next run of that job.
- Pack refresh is not scheduled: it needs the owner database credential, so it stays `make refresh`.
- If the scheduler cannot start (for example no database URL) the API still starts and logs `job scheduler not started: <error class>`.
- Demo rows for the portal pages (dev only, run by hand): `APP_ENV=dev uv run python -m scripts.seed_portal_demo` writes job runs (`demo_sweep`), LLM usage (provider `demo`), one error count and one open alert (`demo_job_failed`) for every tenant, so Jobs, AI performance, Logs and Alerts show data. Safe to repeat; refuses unless APP_ENV=dev; touches no customer, order, case or money data. The failed demo job may also make the real `job_failed` rule fire at the next alert pass.

## Error log and alerts (S9.4)

- Error log (`error_logs`): the API installs a logging handler on start (`ERROR_LOG_ENABLED`, default true). It records, per service, level, event code (the logger name), exception class and day, only a COUNT. It never reads the log message, so a name, phone or token cannot land there. Writes are rate limited: the first occurrence is written at once, repeats are counted in memory and written at most every `ERROR_LOG_FLUSH_SECONDS` (10); more than 200 distinct error types in a day collapse into one `overflow` row. The request thread only puts a small key on a bounded queue (full queue: the event is dropped and counted in a `dropped` row); one background thread writes, through its own one-connection engine. A database failure there is swallowed (a warning with the class name), never raised into a request. The app role cannot read `alerts` or `error_logs`: read them as the owner role, or through the platform routes. Nothing deletes old rows yet: trim by hand with the owner role (`DELETE FROM error_logs WHERE day < current_date - 90`).
- Alerts (`alerts`): the scheduler job `alerts` (`SCHEDULER_ALERTS_INTERVAL_SECONDS`, 300, 0 = off; needs `SCHEDULER_ENABLED`) evaluates five rules: `job_failed` (the latest ok or failed run of a job is failed, within `ALERT_JOB_LOOKBACK_HOURS`), `provider_failure_rate` (failed calls over calls in the last `ALERT_WINDOW_HOURS` above `ALERT_PROVIDER_FAILURE_BPS`, with at least `ALERT_PROVIDER_MIN_CALLS` calls), `escalation_spike` (escalated cases opened in 24 h at least `ALERT_ESCALATION_MIN_COUNT` and above `ALERT_ESCALATION_RATIO_PCT` percent of the prior 7-day daily mean), `eval_regression` (latest `evals/reports/eval-*.md` against the previous: pass rate down by `ALERT_EVAL_DROP_POINTS`), `stuck_job` (a job `running` longer than `ALERT_STUCK_MINUTES`). One open alert per (rule, scope): it is refreshed while the condition holds and resolved when it clears. A rule that could not be read leaves its alerts as they are.
- Reading: `GET /platform/alerts` and `GET /platform/logs` (platform admin token, audited). Nothing is emailed or posted; look at the portal.

## Safety reminders

- Never run tests or evals against the demo/production database.
- Never print or commit `.env` or database URLs.
- `make retention APPLY=1` is irreversible; run the dry run first.
- Merging `test` into `main` needs the owner's go-ahead.
