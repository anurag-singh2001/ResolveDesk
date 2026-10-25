# Decisions

One entry per design choice. Newest first.

Format:
## YYYY-MM-DD · Title
- Decision:
- Why:
- Alternative rejected:

## 2026-10-25 · Operator release of quarantined refunds waits out the provider's request lifetime
- Decision: `POST /approvals/{id}/release` (hq_owner only) frees a refund held as `pending_reconciliation`, or `reserved` and never confirmed. The request checks, from the DB only, that the row is still held, that its approval can no longer be executed (otherwise the sweeper should finish it), and that the window has passed. The window is the later of the ledger's last change and the approval's expiry, plus the payment connector's `request_lifetime`, plus a 5-minute margin. Workers only send while the approval is usable, so the approval's expiry bounds the last send. A background task then asks the provider by key. If the provider has the refund, it is recorded and never freed. If not, the ledger moves to a new status, `released` (migration 0014), by compare-and-set on the status seen, and the execution becomes `failed` with the error "released by operator". The release is audited with the operator's user id. The mock provider now models late landings: a timed-out request may still be applied up to `request_lifetime_s` after it was sent, and never after that.
- Why: "the provider has no record yet" is not proof while a request may still be in flight. The provider's request lifetime is what turns it into proof. `released` stays distinct from `failed` (the provider declined), as rule 7 requires. The compare-and-set means a late landing recorded by a concurrent reconcile wins over the release.
- Residual risk (accepted): the window assumes the provider honours its lifetime, and that no worker stalls for longer than the margin between its usability check and its send.
- Alternative rejected: releasing on the first "no record" (could double-pay); releasing to `failed` (it would merge two different facts); a per-send `last_sent_at` column (adds a write before every send, and still can't see a stall after the write).

## 2026-10-25 · A sweeper finishes approved work and escalates dead agent runs
- Decision: `app/engine/sweeper.py` (`make sweep`) runs per tenant, under RLS, for every tenant folder. It does three things. (1) It executes approved, unexpired proposals that have no execution, through the same executor and stable key. (2) It reconciles executions left `submitted`/`unknown`/`processing` by key; this also records a quarantined refund's late landing. (3) It escalates cases stuck in `investigating` whose agent run died or never started, and marks the dead run failed. Fresh work (under 1 minute old) is left to its background task. The agent's propose step now locks the case and adds nothing if the case is no longer `investigating`, so a run that outlives its TTL can't add a proposal after the sweeper escalated the case. The sweeper does not run on API startup; it is a cron-style command.
- Why: in-process background tasks die with the process. The executors already serialise on the proposal and resume by key, so a sweep racing a live task still writes once. Escalating instead of re-running keeps a maintenance job from spending LLM budget, and a person sees the case at once.
- Alternative rejected: re-running the agent graph from the sweeper (it costs LLM budget, and the customer's message would need replaying); an external queue (Celery/RQ) for v1 (more infrastructure for the same guarantee).

## 2026-10-25 · Vouchers are executed like refunds, through a voucher connector
- Decision: an approved `free_item_voucher` (auto-approved on either path, or approved by staff) is issued by `app/engine/voucher_executor.py` through a `vouchers` connector chosen by the `vouchers_connector` setting (mock: `mock_vouchers`). It follows the refund recipe: a short transaction inserts the execution under the stable key `P-<proposal_id>:voucher:1`, the provider is called outside any transaction, status writes only move forward, and a resume asks the provider by key before sending again. There is no money ledger, because a voucher holds no refundable balance. The customer reference comes from the case row, never from params. The case becomes `resolved` only when the provider confirms the voucher (`escalated` if it declines), and `case_status` says "issued" only then. `app/engine/dispatch.py` maps each action to its executor. The deterministic path and staff approvals queue it as a background task after commit; the agent path runs it after the graph run is recorded.
- Why: E4.6. An auto-approved voucher used to sit in `executing` with nothing issuing it. Reusing the refund recipe gives the same exactly-once guarantees.
- Alternative rejected: issuing vouchers inside the decision transaction (a network call inside a transaction, rule 5); treating approval as issuance (rule 7).

## 2026-10-25 · React web frontend and email + password login
- Decision: the product UI is a React + TypeScript + Tailwind app in `web/` (built with Vite), talking only to the HTTP API through docs/api/frontend-contract.md. Login is email + password, checked against a bcrypt hash stored per user. Login failures get one uniform 401 and a lockout after 5 failures. Dev demo accounts get known passwords, which the login page lists in dev only. The Streamlit app stays as a debug UI until the React app reaches parity.
- Why: the human tested the Streamlit demo and found it too basic to follow the flow or show as a product, and chose a real web frontend. A shared demo password isn't a login. A written contract lets the backend and frontend be built in parallel.
- Alternative rejected: polished Streamlit (the human chose the React option); server-rendered Jinja/HTMX (a second web layer inside the API); self sign-up now (an abuse surface, not needed for the demo).

## 2026-10-24 · The tenant's business rule caps what the AI can propose
- Decision: in agents mode, `decide_remedy` (the deterministic rule engine) sets the ceiling for each case. The model is offered only that rule's action and may propose an amount at or below the rule's amount, or escalate. A category with no automatic rule escalates without calling the model. Policy text never raises the ceiling. A provider error that isn't a rate limit falls back to the next provider.
- Why: Flight 2 (real LLM) proposed 100% refunds at one tenant. Two were for a prompt-injection message on an order 8 minutes late, and one was for a quality complaint whose configured remedy is a voucher. The model cited a refund policy's "up to the amount paid", and code checked only the refund cap. Policy text is untrusted (rule 9), so the money decision has to come from configured rules.
- Residual risk (accepted): a customer's text can steer the classifier toward a more generous category. `decide_remedy` reads facts (line items on record, real delivery timestamps), not text, so the worst case is the auto-approve voucher for a category that doesn't fit the complaint. That is the same trust level as the customer picking a category on the form.
- Alternative rejected: letting the model set amounts within the refund cap (shown unsafe in Flight 2); a second LLM call to judge the first (it can be fooled the same way).

## 2026-10-24 · Agent case loop: code writes everything the customer sees and every proposal
- Decision: free-text cases (`ENGINE_MODE=agents`, no category) run a LangGraph graph: classify → investigate (read tools scoped to the case's customer) → policy (retrieval by order date, brand, location) → resolve (model drafts) → propose (code calls `create_proposal`). Code checks every draft before storing it: an enabled action, strict params, the case's own order, eligibility limits, and at least one citation from what retrieval returned. A rejected draft gets one repair, then the case is escalated. Clarifying questions are fixed templates chosen by code. A model answering "none" escalates for a person to confirm. A low-confidence or unknown classification asks the customer. Any exception escalates. A run claims the case under a row lock, so a resubmitted report can't start a second run. The query is embedded before the DB transaction opens. Customer and policy text are HTML-escaped inside their fences. `create_proposal` takes a tenant id rather than a role-bearing context. The deterministic path (customer picks a category) is unchanged and stays the default.
- Why: the model only chooses among options that code then verifies (hard rules 4, 7, 8, 9). Model-written customer text could promise a refund after prompt injection. A model-closed case would never be seen by a person. A background task has no caller, so an uncaught error would leave the case in "investigating" forever.
- Known gap: an auto-approved voucher puts the case in `executing`, but nothing issues the voucher yet, on either path. Refunds are never auto-approved. Tracked as E4.6. A `running` workflow run older than 10 minutes counts as dead, and the next claim takes the case over.
- Alternative rejected: an LLM-written clarification filtered by a deny-list (a deny-list can't cover every promise); auto-resolving on "none" (no human check on a decline); `with_structured_output` tool calling (JSON prompting works the same on all three providers).

## 2026-10-24 · LLM hardening: no cache in prod, secret keys, two budget caps
- Decision: settings refuse `LLM_CACHE=true` when `APP_ENV=prod` (same validator as the demo-auth/JWT rule). `GEMINI_API_KEY`/`GROQ_API_KEY` are `SecretStr`, unwrapped with `.get_secret_value()` only where `app/llm/providers.py` hands them to the SDK; settings use `hide_input_in_errors=True`. `RunBudget` has two caps: `llm_max_calls_per_run` (8) counts logical calls (each invoke, repairs and cache hits included; retries and fallbacks not) and `llm_max_provider_requests_per_run` (24) counts every request actually sent (retries and fallbacks included; cache hits send none). Either raises `BudgetExceeded`. Rate-limit detection now trusts an HTTP status attribute when present and otherwise matches phrases, never a bare "429". The UI takes identity from `GET /me` and categories from `GET /meta/categories`.
- Why: the cache writes full prompts and replies, customer text included, to local disk with no retention or tenant scoping. `SecretStr` keeps keys out of `repr`, logs and tracebacks, and pydantic otherwise echoes the bad input in a ValidationError. The logical cap keeps routing identical with and without the cache, but on its own one call could fan out to (retries+1) x providers requests; the second cap bounds that cost. "429" in text matched ports and request ids.
- Alternative rejected: one cap counting provider requests (cache on/off would change when a run escalates, so evals would differ); scrubbing keys from error text by pattern (misses formats; hiding input is total).

## 2026-10-24 · Policy retrieval: versioned, scoped, fastembed
- Decision: policies are markdown with front matter (`id, title, topic, version, effective_from, effective_to, scope`); each numbered heading is a chunk with `section_ref` like `late_delivery_v3#2.1`, embedded with BAAI/bge-small-en-v1.5 (384 dims) via **fastembed** (ONNX) and stored in `policy_documents` / `policy_chunks` (RLS, HNSW cosine index). Retrieval filters by effective date on the *order* date and by scope, keeps only the most specific scope per topic (location > brand > org), reports conflicts and "missing" explicitly, then ranks by cosine similarity. Every citation is marked untrusted. Tests use a deterministic hashing embedder (no download); `make seed` uses the real model (`--hash-embeddings` for offline).
- Why fastembed over sentence-transformers (the spec's name): same model and dimensions without PyTorch (~100 MB vs ~1 GB, much lower RAM); the dev machine already had a test run killed for low memory. Human chose it.
- Observed with the real model: similarity doesn't understand numbers ("over an hour late" ranked the "under 20 minutes" section first; the right document and version were still chosen). Callers take the top few sections, and minutes/amounts are always decided in code (`app/engine/resolver.py`, eligibility), never from similarity.
- Alternative rejected: one "latest" policy per topic regardless of order date (an order is judged by the policy in force when it was placed).
## 2026-10-24 · LLM provider factory: one client, our own backoff, JSON + one repair
- Decision: agents call models only through `app/llm/providers.LLMClient`. `get_chat_model(role, provider)` builds a LangChain chat model (Gemini/Groq/Ollama) with the model name from settings (`llm_<role>_model_<provider>`, `llm_ollama_model`); a missing key raises `MissingAPIKey` naming the env var. Provider SDK retries are off (`max_retries=0`): the client retries rate limits (429 / "rate limit" / RESOURCE_EXHAUSTED, detected generically) with exponential backoff, then switches to `LLM_FALLBACK_PROVIDER`; any other error is raised at once. A fallback with no key is skipped with a warning rather than breaking the primary.
- Structured output is prompt-based: a system message carries the Pydantic JSON schema, the reply is validated with `model_validate_json`, and on failure the validation errors (field + message, never input values) go back exactly once; a second failure raises `StructuredOutputError` for the engine to escalate.
- `RunBudget` counts logical calls (each invoke and each repair, cache hits included) and raises `BudgetExceeded` past `llm_max_calls_per_run` (8). Retries and fallbacks are counted separately and don't use up the limit. Tokens are counted from real calls only; cost is an integer-paise placeholder (0 on free tiers).
- Dev cache (`LLM_CACHE=1`): one JSON file per sha256 of (provider, model, messages, schema name) under `.llm_cache/`.
- Why: SDK retries plus ours would multiply wait time and hide 429s from the fallback logic; prompt-based JSON behaves the same on all three providers (small Ollama models included) and makes the repair message simple. Counting cache hits keeps routing identical with and without the cache, so evals don't change when the cache is on.
- Alternative rejected: `with_structured_output` (tool-calling/JSON-mode support and failure shapes differ per provider and model, and the repair turn is harder to build); LangChain `with_fallbacks` (falls back on any exception, not only rate limits, and doesn't count attempts).

## 2026-10-24 · Case + approval API (no-LLM path)
- Decision: `POST /cases` (customers, on their own orders only) stores the message in a ticket thread and runs a deterministic remedy chosen by the vertical pack's `remedies` map (late-delivery tiers, refund of missing items, voucher; unmapped categories escalate). The proposal goes through the same `create_proposal` + `auto_decide` path the LLM pipeline will use. `GET /approvals` lists undecided proposals in the caller's scope with the code checks; `POST /approvals/{proposal_id}/decision` records the decision and queues an approved refund as a background task; `POST /approvals/{proposal_id}/reconcile` queues a by-key reconcile (202). `GET /cases/{id}` shows only verified states: "confirmed" needs a provider-confirmed success; a timeout is "processing".
- The request session uses `Depends(..., scope="function")`: it commits as soon as the endpoint returns, before the response and before background tasks. Found by test: with the default request scope, the background refund ran before the decision was committed and saw no approval.
- Why: the money call never runs inside a request transaction (hard rule 5), and the customer is never told more than the provider confirmed (hard rule 7).
- Alternative rejected: executing the refund inline in the decision request (provider call inside an open transaction; slow request; a client retry could race the executor).
- After safety review: auto-approved refunds are queued too (none exist today; refunds are never auto-approved); missing-items refunds are capped by the percent limit; a refund approved but stuck (expired with no execution, or quarantined) is shown as "needs a check by our team", not "being processed"; non-refund remedies say "we will confirm once it is ready" (no executor yet); one open case per customer+order (a retry returns it). Known gap: a crash between committing the decision and running the in-process background task leaves an approved proposal with no execution. The key is stable, so retrying is safe; story E4.5 adds a sweeper.

## 2026-10-24 · Refund execution: lock, reserve, call outside, reconcile by key
- Decision: `execute_refund` follows PROJECT.md section 10 exactly. A short transaction locks the order row (`SELECT … FOR UPDATE`), re-checks the approval (`check_usable`) and eligibility against the refundable balance (captured payments − refunds reserved/submitted/succeeded/unknown/pending), then inserts the execution and the `reserved` ledger row under `P-<proposal_id>:refund:1` and commits. The connector call happens with no transaction open. The outcome is written in a second short transaction; a timeout is stored as `unknown`, never as success. Re-running for an existing execution never mints a key: it asks the provider by key first and re-sends with the same key only if the provider has no record (timeout before accept) or was temporarily unavailable. Amounts come from the hashed params, never a separate column.
- Eligibility is pure: `Action.validate(ctx, inp, facts)` gets a `Facts` object (effective settings, order total, refundable balance) built by the engine. This extends the spec's `validate(ctx, inp)` so actions stay deterministic and unit-testable with no DB.
- Decisions (`decide`): staff only, in scope (otherwise "not found"); eligibility re-checked when approving; refunds above `refund_without_escalation_paise` need an hq_owner; expiry from `approval_expiry_minutes`; a second decision → `AlreadyDecided`. `auto_decide` never approves refunds; vouchers up to `voucher_auto_approve_max_paise`.
- Why: the lock serialises reservations per order (two refunds that fit alone can't both pass), the DB constraints from 0009 back every step, and the same-key rule makes retries and crashes safe.
- Alternative rejected: calling the provider inside the reservation transaction (holds locks across the network; a crash leaves no record of the attempt).
- After safety review: resuming an existing execution first asks the provider by key. If the provider has it, it's recorded even if the approval has since expired (money already moved). If the lookup itself is unavailable, nothing is sent (reconcile later). Only if the provider has no record is a send allowed, and then the approval must still be usable. Otherwise the refund is quarantined: ledger `pending_reconciliation` (still holds the balance), execution `unknown`, nothing sent. "No record yet" is not proof that an earlier in-flight request won't land, so money is never freed automatically (a second refund could otherwise double-pay); a late success is still recorded. Releasing a quarantined refund is an operator action after a window longer than the provider's request lifetime (not automated in v1). Outcome writes only move forward (stale answers can't overwrite newer states) and never erase a provider reference; events are emitted only by the write that changed state. `decide` checks scope before anything else (all earlier failures look like "not found"), refuses a proposal whose hash isn't intact, and a proposal with no order is hq-only by design. Audit redaction matches key fragments case-insensitively and covers free-text notes.

## 2026-10-24 · Engine least privilege, and the Neon owner bypasses RLS
- Finding: Neon's `neondb_owner` has `rolbypassrls = true` (via `neon_superuser`). `FORCE ROW LEVEL SECURITY` does not constrain it. Moving the dev reseed to the owner role made one tenant's reseed delete every tenant's history in the test database (caught by tests before any merge; the main database was last reseeded as the app role).
- Decision: every statement run as the owner (reseed, test cleanup) filters on `tenant_id` explicitly, and a test proves reseeding tenant A leaves tenant B unchanged. Runtime code never uses the owner.
- Decision (migration 0009, after the E2.3a safety review): the app role can't delete engine rows; proposals, approvals and verifications are insert+read only; executions and refund_operations may only change status columns; audit_events append-only, and the migration fails if the app role is missing. Executions must reference an approved approval of the same proposal (composite FK including `decision`), one per proposal; refund reservations must match their proposal's amount and order (trigger), one per proposal; `amount_paise` must equal the param it came from (check); approval expiry capped at 7 days; a proposal's run must belong to its case; `create_proposal` refuses order/customer/case ids that don't belong to the case.
- Why: these are exactly the invariants the executor (E2.3b) relies on; making them structural means a bug or a race can't violate them.
- Alternative considered: a separate NOBYPASSRLS maintenance role for reseeds (RLS would protect the reseed too). Deferred: needs another role and URL in `.env`; explicit filters plus the cross-tenant test cover the dev-only path.
- Accepted risk (pending the human's decision): with explicit filters, a forgotten `WHERE tenant_id = ...` on an owner-run statement is not caught by RLS. The re-review found one such miss (`load_refs`, fixed; composite FKs would have rejected the cross-tenant ids, so it failed closed). Mitigations: owner engine used only by `scripts/seed.py`, `simulator/load.py` and test cleanup; two tests cover it (cross-tenant reseed counts, colliding slugs). The maintenance role remains the recommended hardening.

## 2026-10-24 · Proposals, approvals and the refund ledger are enforced by the database
- Decision: `action_proposals` are immutable (UPDATE rejected by trigger) and unique on `(tenant_id, id, payload_hash)`; `approvals` reference that triple (so an approval can only exist for the exact hash) and are unique per proposal (two managers can't both decide); a human approval needs `decided_by`, an auto one must not have it, and `expires_at > decided_at`. `executions` and `refund_operations` have unique idempotency keys per tenant; refund amounts are `bigint > 0`. `audit_events` is append-only for the app role (no UPDATE/DELETE/TRUNCATE). The payload hash is sha256 of canonical JSON of `{action, case_id, params}`, floats refused; params are validated in JSON mode against the action's strict `Input` (`extra="forbid"`, ints stay ints).
- Connectors are chosen per tenant by settings (`payment_connector`, `messaging_connector`, `orders_connector`), always addressed with `merchant_id_for(ctx.tenant_id)`; they translate provider exceptions into outcomes (`unknown` after a timeout, `unavailable` for transient errors) and never decide retries.
- Reseeding history (dev only) clears engine tables before commerce tables; audit rows stay.
- Why: the executor (E2.3b) will re-check all of this in code, but the database is the last line of defence against a bug, a race between two approvers, or a replayed approval.
- Alternative rejected: storing approval state on the proposal row (mutable proposal, approval not bound to a hash).

## 2026-10-23 · Mocks: in-process fakes with one idempotency core
- Decision: `mocks/` holds in-process fakes (payment, messaging, POS, delivery app) shared through a process-wide registry. Payment and messaging share `IdempotentMock`: one stored operation per (merchant, idempotency key); same key + same canonical-JSON payload hash → the stored operation (never re-applied, even after a decline); same key + other payload → `IdempotencyConflict` (HTTP 409); `get_by_key` for reconciliation is never subject to chaos. Seeded chaos: timeout before accept (nothing applied), accept-then-timeout (applied, caller can't tell), decline, processing-then-settle, delay. `/admin/chaos` (hq_owner) is only mounted when `APP_ENV` is not prod.
- Why: fast, deterministic contract and chaos tests with no extra processes (the dev machine has little headroom); keys scoped per merchant mirror real providers, so two tenants can never collide.
- Alternative rejected: standalone FastAPI mock services (extra processes and ports for the same contract); random unseeded chaos (flaky tests).
- After safety review: chaos is per merchant (`merchant_id_for(tenant_id)`), so an hq_owner only affects their own tenant; `/admin` mounts only for `APP_ENV` in {dev, test} (allow-list; unknown env names fail settings validation). Each chaos outcome comes from `Random(seed:merchant:key:attempt)`, so seeded runs reproduce regardless of thread order or other tenants' traffic. Calls return snapshots taken under the lock. Failure taxonomy for the executor: `ProviderTimeout` = unknown → reconcile by key, then retry with the same key; `ProviderUnavailable` (5xx/429 before accept) = nothing applied → retry with the same key; a `failed` operation (decline) is final for that key → a new attempt needs a new approval and a new attempt-scoped key, never a silently minted one.

## 2026-10-23 · Simulator: config-driven, fixed calendar, replace-on-reseed
- Decision: volumes, planted problems (late / missing_item / wrong_item / repeat_drop with location, hour and weekday filters) and messy-data rates live in each tenant's `simulation:` block; the generic simulator reads them plus the vertical pack (`fulfilment_kinds`). The window ends on a configured `end_date`, not today. Ids are uuid5 of the tenant + row number; reseeding deletes and reinserts the tenant's commerce rows in one transaction. The loader now prunes only config tables (`CONFIG_MODELS`).
- Why: no tenant names in code (hard rule 2); same seed → byte-identical data on any day; delete+insert is simpler and faster than upserting ~80k rows. Measured: full seed of both tenants 47 s on Neon.
- Rate tolerance: planted rates must match within ±1 point, or 3 standard errors for narrow slices (e.g. one outlet's weekday mornings, ~300 orders, where ±1 point is below sampling noise). Averaged over 6 seeds every planted rate is on target (bias check).
- Alternative rejected: hard-coding the spec's planted problems per tenant in Python; dates relative to `now()` (non-reproducible).

## 2026-10-23 · Order visibility as one SQL predicate
- Decision: `TenantContext.visible_orders()` returns a WHERE clause used by both list and detail routes: hq_owner all; scoped roles by location, narrowed by brand when the membership has brands (closes the E1.4 brand-scope gap); customers only orders of the customer row linked to their own user id. Not visible → 404.
- Why: one rule for list and detail means they can't disagree; filtering in SQL avoids loading other customers' rows into Python.
- Alternative rejected: per-row Python checks after a broad query (easy to forget on a new route, and fetches data the caller may not see).

## 2026-10-23 · History safety after E2.1 review
- Decision: `load_history` refuses to run when `APP_ENV=prod`; a catalog test fails if any non-commerce table gets an FK into commerce tables (so E2.3's cases/refunds must extend the reseed path deliberately). Removing a login user unlinks their customer (`ON DELETE SET NULL (user_id)`, PG15+; Neon runs 18); removing a brand/location that orders reference aborts the whole load with `TenantLoadError`. Money consistency (line items = order total, payments ≤ total) is asserted on DB data by a test.
- Next for E2.3b (refunds): the refundable balance is enforced in code inside one short transaction with `SELECT … FOR UPDATE` on the transaction row (PROJECT.md section 7), against `payments` minus `refund_operations` in reserved/submitted/succeeded/unknown; not as a DB check constraint, because it spans rows.
- Why: reseeding must never destroy live data, and config edits must fail loudly instead of half-applying.
- Alternative rejected: `ON DELETE CASCADE` from brands/locations to orders (silent history loss).

## 2026-10-23 · Demo auth: thin token, scope from the DB, fail closed
- Decision: `POST /auth/login {tenant, email, password}` with one demo password for seeded users (`DEMO_AUTH` can switch it off). The HS256 JWT holds only `tid` + `sub` + `exp` (secret must be ≥ 32 bytes). Every request re-reads role and location/brand scope from the DB inside the token's tenant session. Only `hq_owner` sees the whole org; scoped roles with no scope rows see nothing. Out-of-scope and other-tenant records both return 404; a customer on a staff route gets 403 (the route exists for everyone, the record question doesn't arise).
- Why: a role or scope in the token could be replayed after it was revoked; reading the user under RLS means a token pairing tenant A with a user of tenant B finds no user (401). Failing closed avoids "empty scope = everything".
- Alternative rejected: role/scope claims in the JWT (stale after changes); 403 for out-of-scope records (confirms they exist).
- Hardening after safety review: `DEMO_AUTH` defaults to off and `APP_ENV=prod` refuses demo auth or the dev JWT secret; tokens carry and verify `iss`/`aud`, TTL 60 min; one membership per user (unique constraint, and the lookup fails closed on more than one); login runs the same queries whether or not the tenant/user exists and checks the password last; the caller's context and the route's data share one transaction per request.
- Known gaps, deliberately deferred: brand scope (`membership_brands`) is loaded but not enforced, because no data is keyed by brand yet; E2.1 (first brand-keyed data: orders) must enforce it and test it. No login rate limiting or token revocation list (demo; per-request DB re-read already cuts off deleted users and changed roles).

## 2026-10-23 · Git branches: feature → test → main
- Decision: GitHub `origin`; `main` = deployed/stable, `test` = integration, `feature/<story-id>-<name>` cut from `test`. A story merges into `test` only after `make lint`, `make test`, `make test-isolation` (and safety-reviewer where required) pass; `test` is promoted to `main` at sprint review. Merges use `--no-ff` so one `git revert -m 1 <merge>` undoes a whole story.
- Why: the human reviews remotely; every story is isolated and revertible, and `main` only ever holds verified work.
- Alternative rejected: committing straight to `main` (no safe rollback point, unreviewed work deployed).

## 2026-10-23 · Remedy rules are tenant settings, not code or fixed spec values
- Decision: late-delivery tiers, voucher auto-approve cap (default ₹150 = 15000 paise), refund channel (`tenant_gateway` | `aggregator_only`) and money limits are vertical-pack settings that a tenant overrides at org/brand/location. Settings have a kind: `limit` (integer ceiling; lower levels may only lower it) or `value` (replaced). Refunds always need human approval: that stays a hard rule, not a setting.
- Why: the human asked that business answers (tiers, caps, aggregator handling) be configurable from the platform, not decided in code. Overrides live in `tenant_settings`, so a future admin UI/API can change them without a deploy.
- Alternative rejected: hard-coded tiers and caps (BA research found no market norm to justify one fixed value).

## 2026-10-23 · Deterministic tenant IDs for the loader
- Decision: tenant and child IDs are `uuid5` of slugs; the loader upserts by id and only rewrites a row when a value differs (`IS DISTINCT FROM`). Packs are stored in `vertical_packs` (platform-wide, no RLS). The seed CLI sets the tenant from the folder it loads; this is an admin path, not a request path.
- Why: with RLS the loader can't look an org up by slug before the tenant is set; deterministic ids make reruns a no-op (`updated_at` unchanged), which the idempotency test checks.
- Alternative rejected: lookup-then-insert as owner (bypasses RLS on the write path).

## 2026-10-23 · Test database instead of a Neon test branch
- Decision: tests use a second database `resolvedesk_test` on the same Neon branch; the app role is cluster-wide so it works in both. Bootstrap (role, vector, `lg` schema, grants) runs in both databases.
- Why: creating a branch needs the Neon CLI/console login; a database needs only the owner URL. Same isolation for tests.
- Alternative rejected: Neon `test` branch (extra setup step; can revisit for CI resets).

## 2026-10-23 · Tenancy schema: forced RLS + composite foreign keys
- Decision: RLS is ENABLED and FORCED on every tenant table with policy `tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid` (USING + WITH CHECK). Child tables reference parents by `(tenant_id, id)`. `organizations.tenant_id = id` (check constraint). Brand/location many-to-many via `location_brands`.
- Why: FORCE makes the owner role obey RLS too (correction 2026-10-24: not for a role with BYPASSRLS, which Neon's owner has; see the entry of that date); unset tenant → NULL → no rows. Composite FKs stop a row in tenant A pointing at a row in tenant B even though FK checks bypass RLS.
- Alternative rejected: single-column FKs (cross-tenant links possible), RLS without FORCE (owner bypasses).

## 2026-10-23 · Sprints with scrum-master and business-analyst agents
- Decision: 5 sprints (0–4) tracked in docs/EPICS.md + docs/sprints/; a `scrum-master` agent runs meetups, ticks stories only after verifying done-when, and keeps an evidence-based agent/model scorecard; a `business-analyst` agent writes sourced research into docs/research/.
- Why: visible progress against deadlines and a record of which agent/model performed well; research keeps policies, data and scenarios realistic.
- Alternative rejected: following the day-by-day plan with no status tracking (progress claims unverified).

## 2026-10-23 · GNU make on Windows
- Decision: keep the Makefile; install make via `winget install ezwinports.make`. Recipes are single `uv run ...` / `echo` commands so they work under cmd or sh.
- Why: matches the spec and is what other developers expect from the README.
- Alternative rejected: a Python task runner (diverges from spec and CLAUDE.md commands).

## 2026-10-23 · Two DB roles, transaction-local tenant
- Decision: migrations run as the Neon owner on the direct endpoint; the app and tests connect as `resolvedesk_app` (created by SQL, NOBYPASSRLS, DML grants only). Tenant is set with `set_config('app.tenant_id', x, true)` inside each transaction.
- Why: table owners and neon_superuser members bypass RLS; Neon's pooled endpoint is PgBouncer transaction mode, so a session-level SET could leak to another client.
- Alternative rejected: one owner URL for everything (RLS silently not enforced).

## 2026-10-23 · Neon instead of Docker Compose
- Decision: hosted Neon Postgres 16 + pgvector, with a `main` branch for dev/demo and a `test` branch for pytest.
- Why: no Docker Desktop on the dev machine; Neon is free, supports pgvector and RLS, and branches give a cheap, resettable test DB.
- Alternative rejected: Docker Compose Postgres (not available); local Windows Postgres install (harder for others to reproduce).

## 2026-10-22 · LLM proposes, code executes
- Decision: Agents only get read tools; the executor is plain code acting on an approved, hash-bound proposal.
- Why: money and customer messages must be deterministic and auditable.
- Alternative rejected: giving the resolution agent a refund tool (unbounded risk, hard to test).

## 2026-10-22 · Row-level security for tenancy
- Decision: one database, `tenant_id` on every tenant-owned table, Postgres RLS with a session variable.
- Why: isolation enforced by the database even if application code has a bug.
- Alternative rejected: schema per tenant (heavier migrations, harder to demo onboarding).

## 2026-10-22 · Free LLM stack
- Decision: Gemini Flash main, Groq classifier + fallback, Ollama offline, local embeddings.
- Why: zero cost for a POC; provider switch shows production readiness.
- Alternative rejected: one paid provider.

## 2026-10-24 · Demo UI talks only to the HTTP API
- Decision: the Streamlit UI (`ui/`) calls the API through a small httpx client and never touches the DB; httpx moves from dev to runtime dependencies. Tenant YAML is read only for the dev login picker.
- Why: the UI exercises the same auth, scope and RLS checks a real client would, and holds no business logic to drift from the engine.
- Alternative rejected: importing engine/DB code into Streamlit (faster to write, but bypasses the API's access checks).
