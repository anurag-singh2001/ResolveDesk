# ResolveDesk — Project Specification

This file is the single source of truth for the project. Read the section you need before building anything. If code and this file disagree, stop and ask the human which one is right; do not silently pick one.

---

## 1. What we are building

ResolveDesk is a multi-tenant platform where:

- **Customers** raise problems (late order, wrong item, double charge, refund request) and track them.
- **Business users** (HQ owners, franchisee owners, outlet managers) set policies and limits, approve risky actions, and see insights.
- **An AI engine** investigates each case, finds the applicable policy, proposes an action, waits for approval when needed, executes it safely, verifies the result, and records everything.

The same engine runs two modules:

- **Support** (build first): resolve customer complaints.
- **Growth** (stretch): detect an underperforming outlet or metric, propose a campaign with a holdout group, launch after approval, measure real lift.

**Core principle:** the LLM proposes; code validates and executes; a human approves anything risky; the system tells customers only what a tool has confirmed.

This is a portfolio POC for AI engineer and Forward Deployed Engineer roles. It must be runnable by another developer from the README, with reproducible test and eval results.

---

## 2. Scope

### In scope (v1)
- Two tenants: **Spice Route Foods** (cloud kitchen) and **BrewCo** (coffee franchise, 5 outlets).
- One currency: INR, stored as integer paise.
- Human approval for every refund. Low-value vouchers may be auto-approved by tenant rule.
- Mocked external services: payment, POS, delivery app, messaging (WhatsApp-like).
- One issue per case.
- Synthetic data only.
- Simple UI in Streamlit.

### Out of scope (v1)
Real integrations, chargebacks, fraud decisions, partial returns spanning orders, multiple currencies, React frontend, production deployment.

---

## 3. Hard rules (never break these)

1. Every tenant-owned table has `tenant_id`. PostgreSQL row-level security (RLS) is enabled on those tables. Every DB session sets the tenant from the authenticated request (`SET app.tenant_id`), never from user or model input.
2. No tenant-specific branches in core code (`if tenant == "brewco"` is forbidden). Differences live in vertical packs, tenant settings, actions, connectors, feature flags or event subscribers.
3. Money is an integer in paise. Never float. Never Decimal for stored amounts.
4. LLM agents only get read tools. Only the executor step (plain code) calls write tools, and only for an approved proposal.
5. Every write to an external service carries a stable idempotency key. Never call a network service while holding a DB transaction open.
6. Approvals bind to a proposal's payload hash and have an expiry. If anything material changes, the old approval is invalid.
7. Customer-facing messages state only what a tool confirmed. Keep `submitted`, `processing`, `succeeded`, `failed`, `unknown` distinct.
8. Identity and access come from the auth token. Order IDs supplied by a customer or model never grant access; ownership is checked server-side.
9. Retrieved policy text is untrusted content. Instructions inside it are ignored.
10. Every change ships with a test.

---

## 4. Tech stack

| Area | Choice |
| --- | --- |
| Language | Python 3.12 |
| API | FastAPI, Pydantic v2 |
| Workflow | LangGraph (with Postgres checkpointer) |
| LLM access | LangChain chat model interface, provider chosen by env var |
| Database | PostgreSQL 16 + pgvector, SQLAlchemy 2.x, Alembic |
| Embeddings | Local: `BAAI/bge-small-en-v1.5` via sentence-transformers (384 dims) |
| Tests | pytest, pytest-asyncio, httpx |
| UI | Streamlit |
| Lint/format | ruff |
| Dev env | Docker Compose (postgres), `uv` for Python deps, Makefile |

### LLM providers (all free tiers / local)

| Use | Provider | Env |
| --- | --- | --- |
| Main agents (investigate, policy, resolve, diagnose) | Gemini Flash (Google AI Studio) | `GEMINI_API_KEY` |
| Classification, fallback on rate limit | Groq | `GROQ_API_KEY` |
| Offline / unlimited eval runs | Ollama (Qwen or Gemma small model) | `OLLAMA_BASE_URL` |

Config: `LLM_PROVIDER=gemini|groq|ollama`, `LLM_CLASSIFIER_PROVIDER=groq`, `LLM_FALLBACK_PROVIDER=groq`. All model names live in config, never in code. Retry with backoff on 429, then fall back. Cache LLM responses in dev (`LLM_CACHE=1`) keyed by prompt hash.

---

## 5. Repository layout

```
app/
  main.py                FastAPI app factory
  config.py              settings (pydantic-settings)
  core/
    db.py                engine, session, tenant session var
    tenancy.py           TenantContext, role checks, scope (org/brand/location)
    auth.py              simple JWT auth for demo users
    money.py             paise helpers
    audit.py             audit_events writer (redacted)
    events.py            domain event bus (in-process)
    settings_resolver.py effective settings: vertical pack -> org -> brand -> location
  engine/
    cases.py             case lifecycle
    proposals.py         immutable proposals + payload hash
    approvals.py         approval rules, binding, expiry
    executor.py          safe execution, reconciliation
    verifier.py          verification step
    graph.py             generic LangGraph loop
  modules/
    support/             support-specific nodes, tools, prompts
    growth/              signals, opportunities, campaigns (stretch)
  actions/
    base.py              Action base class + registry
    refund.py  free_item_voucher.py  loyalty_credit.py  send_campaign.py
  connectors/
    base.py              Connector interfaces + registry
    mock_pos.py  mock_delivery_app.py  mock_payment.py  mock_messaging.py
  agents/
    classifier.py  investigation.py  policy.py  resolution.py  diagnosis.py
  rag/
    ingest.py  retrieve.py
  llm/
    providers.py         provider factory + fallback + cache
  api/
    routes_*.py
mocks/                   standalone mock services (FastAPI apps) with failure injection
verticals/
  cloud_kitchen.yaml
  coffee_chain.yaml
tenants/
  spice_route/  tenant.yaml  catalogue.csv  policies/  scenarios/
  brewco/       tenant.yaml  catalogue.csv  policies/  policies/outlets/  scenarios/
simulator/              deterministic data + behaviour simulator
evals/                  harness, metrics, report
ui/                     Streamlit pages
migrations/             Alembic
tests/                  unit/ integration/ isolation/ chaos/
docs/                   PROJECT.md DECISIONS.md LEARNING.md
```

---

## 6. Tenancy model

Hierarchy: **Organization → Brand → Location**.

| | Spice Route Foods | BrewCo |
| --- | --- | --- |
| Vertical pack | `cloud_kitchen` | `coffee_chain` |
| Brands | Biryani Box, Midnight Pizza Co., Bowl Theory | BrewCo Coffee |
| Locations | Kharadi kitchen (serves all 3 brands) | Koregaon Park (HQ-owned), Baner + Viman Nagar (franchisee A), Aundh + Kothrud (franchisee B) |
| Order source | Mock delivery app | Mock POS + pickup app |
| Growth module | off | on |

### Roles

| Role | Scope | Can | Cannot |
| --- | --- | --- | --- |
| customer | own records | raise and follow cases, add info | see others' data or internal notes |
| location_manager | one or more locations | approve within the location limit, work the queue | change policy, see other locations |
| franchisee_owner | their locations | tighten location settings, approve campaigns for their locations | loosen org limits |
| hq_owner | whole org | set org policy and limits, see all analytics | skip approval rules on money actions |

### Settings inheritance
Effective setting = vertical pack default → org → brand → location override. For limits, a lower level may only tighten: `effective = min(parent, override)`. Implemented once in `settings_resolver.py` and unit-tested.

---

## 7. Data model

All tenant-owned tables: `id uuid pk`, `tenant_id uuid not null`, `created_at`, `updated_at`, RLS policy `tenant_id = current_setting('app.tenant_id')::uuid`. Money columns end in `_paise` and are `bigint`.

| Group | Tables | Notes |
| --- | --- | --- |
| Tenancy | organizations (= tenants), brands, locations, users, memberships | membership: user_id, role, scope (brand/location ids) |
| Canonical | customers, transactions, line_items, payments, fulfilments | `attributes jsonb` for tenant custom fields, validated by tenant schema |
| Config | vertical_packs, tenant_settings, feature_flags, policy_documents, policy_chunks | policy_documents: version, effective_from, effective_to, scope (org/brand/location), source_uri; policy_chunks: content, embedding vector(384), section_ref, metadata |
| Engine | cases, workflow_runs, action_proposals, approvals, executions, verifications | proposals immutable; payload_hash sha256 of canonical JSON |
| Money | refund_operations | unique(idempotency_key); amount_paise; status in (reserved, submitted, succeeded, failed, unknown, pending_reconciliation); provider_reference |
| Tickets | tickets, ticket_messages | message author: customer / system / staff |
| Growth | metric_snapshots, signals, campaigns, campaign_members, playbook_entries | campaign_members has `group` in (treatment, holdout) |
| Trust | audit_events, domain_events, consents | audit payloads redacted |

DB constraints to implement:
- Sum of succeeded + reserved refunds per transaction ≤ paid amount (enforced in a transaction with `SELECT ... FOR UPDATE` on the transaction row).
- `approvals.proposal_id` + `payload_hash` must match the proposal at execution time.
- LangGraph checkpoint tables in a separate schema (`lg`), never used as the ledger.

---

## 8. The engine loop

Every workflow, support or growth, follows these steps:

| # | Step | Done by | Output |
| --- | --- | --- | --- |
| 1 | Signal | code (API request, or metric job) | case with category |
| 2 | Investigate | investigation agent + read tools | structured evidence |
| 3 | Policy | policy agent + retrieval, filtered by version/date/scope | citations + interpretation |
| 4 | Propose | resolution agent, then code validation | immutable proposal with payload hash |
| 5 | Approve | human via `interrupt()`, or auto-approve rule checked in code | approval record |
| 6 | Execute | executor (code only) | execution with idempotency key |
| 7 | Verify | verifier (code) | verified status |
| 8 | Learn | code | ticket update, audit, metrics, playbook entry |

Routing rules:
- Missing info → ask one targeted clarification question, pause for customer reply.
- No applicable policy, or conflicting policy → escalate to a human, never invent eligibility.
- Invalid model output → validate, one repair attempt, then escalate.
- Max steps per run: 12. Max LLM calls per run: 8. Exceed → stop and escalate.

### LangGraph state (suggested)
```python
class CaseState(TypedDict):
    tenant_id: str
    case_id: str
    run_id: str
    category: str | None
    evidence: dict | None
    citations: list[dict]
    proposal_id: str | None
    approval_status: Literal["none", "pending", "approved", "rejected", "expired", "auto"]
    execution_status: str | None
    verification: dict | None
    customer_message: str | None
    errors: list[str]
    step_count: int
    llm_calls: int
```

Interrupt/resume: use `interrupt()` in the approve node, Postgres checkpointer, resume with `Command(resume=...)` on the same `thread_id`. Code before the interrupt may run again on resume, so the approve node has no side effects. Execution is a separate node.

---

## 9. Agents

| Agent | Model | Tools | Output schema |
| --- | --- | --- | --- |
| classifier | Groq small | none | `{category, confidence, needs_info: list[str]}` |
| investigation | Gemini Flash | get_customer, get_transaction, list_customer_transactions, get_payment, get_fulfilment, get_case_history | `Evidence` |
| policy | Gemini Flash | search_policies(query, as_of, scope) | `PolicyFindings{citations[], interpretation, conflicts[], missing: bool}` |
| resolution | Gemini Flash | none (gets evidence + findings) | `ResolutionDraft{action, params, reason, citations}` |
| diagnosis (growth) | Gemini Flash | read-only metric queries | `Diagnosis{findings[], hypotheses[]}` |

All tools: typed inputs, structured outputs, structured errors (`{ok: false, error_code, retryable, message}`). Tenant and customer come from `TenantContext`, never from tool arguments. Investigation and policy may run concurrently when they don't depend on each other.

Start with a single tool-using agent baseline, then split into specialists. Keep the baseline runnable for comparison in evals.

---

## 10. Actions and connectors

### Action interface
```python
class Action(ABC):
    name: ClassVar[str]
    risk: ClassVar[Risk]            # LOW, MEDIUM, HIGH
    Input: ClassVar[type[BaseModel]]

    def validate(self, ctx: TenantContext, inp: BaseModel) -> ValidationResult: ...
    def execute(self, ctx: TenantContext, inp: BaseModel, idempotency_key: str) -> ExecutionResult: ...
    def verify(self, ctx: TenantContext, result: ExecutionResult) -> VerificationResult: ...
```
Registered with `@register_action`. Enabled per tenant via vertical pack + tenant settings.

v1 actions: `refund` (HIGH), `free_item_voucher` (MEDIUM), `loyalty_credit` (MEDIUM, BrewCo), `send_status_update` (LOW). Stretch: `send_campaign` (HIGH).

### Connector interface
Connectors translate a source system into canonical models (`Transaction`, `Payment`, `Fulfilment`, `Customer`). Registered with `@register_connector("<name>")`. The agent tools call connectors, never mock services directly.

### Safe refund execution
1. Load the approved proposal; check approval exists, not expired, payload hash matches.
2. Short DB transaction: lock the transaction row, recheck refundable balance, insert `refund_operations` (status `reserved`, stable key `P-<proposal_id>:refund:1`), commit.
3. Call the payment connector with the key (outside any transaction).
4. Persist the response. On timeout or ambiguous result: status `unknown` → reconcile by querying the provider by key before any retry.
5. Retry only with the same key.

Mock payment contract: same key + same payload → same operation; same key + different payload → 409; configurable timeout rate, delay, and "accept then time out".

---

## 11. Policies and RAG

- Policies are markdown files with front matter: `id, title, version, effective_from, effective_to, scope (org|brand:<slug>|location:<slug>)`.
- Ingest: split by headings into sections, embed locally, store with `section_ref` like `late_delivery_v3#2.1`.
- Retrieve: filter by tenant, scope (location → brand → org), and effective date on the order date; then vector similarity; return top k with references.
- Location-level policy overrides org policy on the same topic.
- Report missing or conflicting evidence explicitly. Similarity scores are never proof of eligibility; eligibility is enforced in code.

Policies to write per tenant (see `tenants/*/policies/`):
- Spice Route: late_delivery_v3, refunds_v2, food_quality_v1, missing_items_v1.
- BrewCo: order_accuracy_v2, refunds_v1, loyalty_v1, outlets/baner.md (override).

---

## 12. API

| Method | Path | Who | Purpose |
| --- | --- | --- | --- |
| POST | /auth/login | all | demo login, returns JWT |
| POST | /cases | customer | create case from a message |
| POST | /cases/{id}/messages | customer | add info |
| GET | /cases/{id} | customer, staff | status, customer-safe message |
| GET | /cases/{id}/events | staff | redacted timeline |
| GET | /approvals | staff | pending approvals in scope |
| POST | /approvals/{id}/decision | staff | approve / reject |
| GET | /insights/outlets | hq_owner, franchisee_owner | metrics by location |
| POST | /admin/chaos | dev only | set mock failure rates |
| POST | /admin/clock | dev only | move the simulated clock |
| GET | /health | public | health |

Every route checks role and scope. Return 404 (not 403) for records in another tenant, so existence isn't leaked.

---

## 13. UI (Streamlit)

- **Customer portal:** login as a demo customer, order list, chat to raise a case, status bar (Received → Investigated → Awaiting approval → Confirmed), honest status text.
- **Manager queue:** pending approvals with evidence, policy citations, amount, code-check results, expiry, approve/reject.
- **HQ view:** outlet metrics, signals, campaign proposals (stretch).
- **Dev panel:** chaos toggles, clock, reseed.

Show structured events and short explanations, never raw model reasoning.

---

## 14. Data, onboarding and the simulator

Each tenant is a folder under `tenants/<slug>/`, loaded by `make seed TENANT=<slug|all>`. The loader is generic; it must never contain a tenant name.

| Kind | Source | Committed |
| --- | --- | --- |
| Config | `tenant.yaml` | yes |
| Catalogue | `catalogue.csv` (prices in paise) | yes |
| Policies | `policies/*.md` | yes |
| History | simulator, `SEED=42` | no, regenerated |
| Scenarios | `scenarios/*.yaml` | yes |

### Generated history

| | Spice Route | BrewCo |
| --- | --- | --- |
| Customers | 1,500 | 2,500 across 5 outlets |
| Orders (last 60 days) | 6,000 | 15,000 |
| Past tickets | 300 | 400 |
| Planted problems | 8% of orders > 45 min late; 2% missing items | Baner: 3× wrong orders 8–10 am weekdays; Baner repeat rate drops from day 35 |
| Messy data | duplicate phone numbers, orders outside window | multi-outlet customers, opted-out customers |

The simulator reads the vertical pack to decide which events to generate. Same seed → identical data. The simulator can also run forward on a simulated clock (`make sim DAYS=14 TENANTS=all`), sending complaints through the real API.

### Scenario file format
```yaml
id: sr-late-001
tenant: spice_route
category: refund_eligible
given:
  customer: {name: Riya M., orders: 14, disputes: 0}
  order: {brand: biryani_box, paid_paise: 69800, promised: "19:50", delivered: "20:42"}
message: "Order came almost an hour late and the biryani was cold. I want a refund."
reviewer_decision: approve
chaos: {}
expect:
  policy_cited: late_delivery_v3#2.1
  proposal: {action: refund, amount_paise: 34900}
  approval_required: true
  final_state: {refund: succeeded, ticket: resolved, refunds_count: 1}
  forbidden: [refund_over_50_percent, message_before_verification]
held_out: false
```

---

## 15. Testing

Both tenants are tested in every run.

| Layer | Proves | Command |
| --- | --- | --- |
| Unit | eligibility, settings inheritance, paise, hashing | `make test` |
| Tenant-parametrized integration | each feature works for both tenants | `make test` |
| Isolation | no cross-tenant or cross-location access | `make test-isolation` |
| Concurrency + chaos | no duplicate refunds/sends under timeouts, retries, restarts, both tenants at once | `make test-chaos` |
| Evals | end-to-end scenario outcomes, per tenant | `make eval` |

- `tests/conftest.py` has a `tenant` fixture parametrized over all tenants in `tenants/`. Tests never name a tenant.
- Isolation matrix: every role of each tenant attempts read/approve/policy access on the other tenant and on out-of-scope locations; all denied, no detail leaked. Also: agent tool called with a forged order ID.
- Chaos: 50 cases per tenant concurrently, payment timeout rate 0.3, then reconcile; assert zero duplicates. Also: double approval submit, worker killed mid-execution, two managers approving the same proposal.

---

## 16. Evaluation

Harness: seed scenario → send message → play reviewer decision → wait for completion → assert DB + mock provider state against `expect`.

Target ~60 scenarios eventually (start with 30: 15 per tenant). Categories: status questions, eligible refunds, ineligible refunds, missing/ambiguous info, API failures and crashes, authorization/concurrency/adversarial. About 20% marked `held_out: true`, never used while tuning prompts.

Report per tenant:

| Metric | Target |
| --- | --- |
| Workflow correctness (all cases) | ≥ 85% |
| Verified resolution (resolvable cases) | ≥ 80% |
| Correct policy cited | ≥ 90% |
| Unauthorized actions | 0 |
| Duplicate refunds | 0 |
| Cross-tenant leaks | 0 |
| Median active time per case | < 10 s |
| LLM calls, tool calls, estimated cost per case | tracked |

Report human-assisted and fully automated resolutions separately. Measure reviewer wait time separately from active time. An LLM judge may score response wording only, never whether money moved. Also run the single-agent baseline and report the comparison.

---

## 17. Growth module (stretch, Day 7)

One signal end to end: BrewCo Baner repeat-customer rate drop.
1. Nightly job (code) computes `repeat_rate` per location vs its own 4-week baseline; flags drops > 5 points.
2. Diagnosis agent drills down (time of day, ticket categories) and links support tickets.
3. Code builds the audience: lapsed regulars, minus no-consent, minus frequency-capped.
4. Proposal: win-back offer, 10% holdout, budget cap from settings, success metric.
5. Approval by franchisee owner and HQ (campaign value > ₹10,000 needs both).
6. Send via messaging connector, one idempotency key per customer.
7. After the window, compare treatment vs holdout; verdict = worked / didn't work / inconclusive (sample too small); save to playbook.

---

## 18. Extension points (how future client needs are handled)

| Need | Where it goes |
| --- | --- |
| New business type | `verticals/<type>.yaml` (+ actions/connectors if needed) |
| New action | class in `app/actions/`, enabled in settings |
| New source system | connector in `app/connectors/` + mock |
| Extra data field | tenant custom field schema → `attributes jsonb` |
| Notification or side effect | event subscriber on a domain event |
| Turn a module on/off | `feature_flags` |

If a request fits none of these, discuss it before writing code.

---

## 19. Build plan

| Day | Build | Done when |
| --- | --- | --- |
| 0 | This spec, CLAUDE.md, .claude setup, DECISIONS.md | A fresh session can describe the project from docs alone |
| 1 | Repo, Docker Compose, Makefile, config, Alembic, tenancy tables + RLS, auth + roles, settings resolver, tenant YAML loader, both tenant folders (config + catalogue) | Both tenants load; isolation tests pass |
| 2 | Canonical tables, mock services with failure injection, connector + action registries, deterministic eligibility, simulator history | A refund resolves via API with no LLM, for both tenants |
| 3 | LLM provider factory, policy files, RAG ingest + retrieve, LangGraph classify → investigate → policy → propose | Cited, validated proposals for 3 scenarios per tenant |
| 4 | Approval interrupt/resume, executor, reconciliation, verifier, tickets, audit, events | Chaos tests show zero duplicate refunds |
| 5 | Streamlit customer portal, manager queue, HQ view, dev panel | Full demo click-through for both tenants |
| 6 | Eval harness, 30 scenarios, baseline comparison, report | `make eval` prints per-tenant table |
| 7 | README, architecture diagram, demo script; stretch growth signal | Another developer runs it from README |

---

## 20. Definition of done (any feature)

- Tests written first or alongside, passing for both tenants.
- No hard rule broken (safety-reviewer clean for money/tenancy/approval changes).
- `make lint` clean.
- Decision recorded in `docs/DECISIONS.md` if a design choice was made.
- Short entry in `docs/LEARNING.md` (the human writes this).
