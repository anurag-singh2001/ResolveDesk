# Web frontend ↔ API contract (v1)

The React app (`web/`) talks only to this HTTP API. Every business rule stays in the API; the
frontend only displays what the API returns. Money is integer paise in JSON; the frontend formats
it as ₹ with 2 decimals. Times are ISO 8601 UTC; the frontend shows them in the browser's local
time. Tokens are bearer JWTs, kept in memory and `sessionStorage` (never `localStorage`).

`NEW` = added by the backend story E5.4 (implemented); everything else existed before.

## Auth
| Method | Path | Who | Body / query | Response |
| --- | --- | --- | --- | --- |
| GET | `/auth/businesses` NEW | public | – | `[{slug, name, vertical}]` |
| GET | `/auth/demo-accounts` NEW | public, **dev only** (404 when `APP_ENV=prod` or `DEMO_AUTH` is off) | – | `[{tenant, email, name, role, password}]` |
| POST | `/auth/login` | public | `{tenant, email, password}` | `{access_token, token_type, expires_at}` (`expires_at` NEW). 401 `invalid credentials` (same for unknown user and wrong password). 429 NEW `too many failed logins, try again later` after 5 failures for one tenant+email in 15 min (even with the right password; unknown emails lock the same way). `expires_at` is ISO 8601 UTC |
| GET | `/me` | any | – | `{user_id, name, email, role, location_ids, brand_ids, tenant: {slug, name, vertical}, growth_enabled}` (`tenant` NEW; `growth_enabled` NEW: bool, the tenant's `growth` flag; show the Growth page only for staff when true) |
| GET | `/me/preferences` NEW | customer only (staff and users with no customer record: 404) | – | `{language}`: `en` (default), `hi-Latn` (Hinglish, Roman script) or `hi` (Devanagari). Web: a select on the Help page, customers only |
| PUT | `/me/preferences` NEW | customer only (404 otherwise) | `{language}`; any other value is 422 | `{language}`. Changes only the caller's own record (no id is accepted); audited as `customer.language_changed`. From then on `message` in `/cases` and `/cases/{id}`, and `title`/`text` in `/cases/{id}/timeline`, are in that language (fixed templates, never generated; a missing translation shows English). Amounts are always `₹1,00,000.00` style and dates `27 Oct 2026`. The web font stack includes `Noto Sans Devanagari` and `Nirmala UI`. The web app's own static labels stay English |

Roles: `customer`, `location_manager`, `franchisee_owner`, `hq_owner`. 401 on any call → token is
gone or expired: clear it and go to the login page with "Your session has ended".

## Meta
| GET | `/meta/categories` | any | – | `{categories: [slug], free_text: bool}` |
| GET | `/meta/privacy` NEW | any | – | `{name, email}`: the caller's tenant privacy contact (empty strings if unset). Web shows it in the footer ("Privacy contact", mailto link) and on the Help page |

`privacy_request` is a normal category slug in `/meta/categories`. A case opened with it is `escalated` at once, has no proposal, and its `message` is a template naming the privacy contact and an internal response date (never described as statutory). Staff `/cases/{id}/events` gain `grievance.due_soon` (payload `{target_days, internal_target_on}`) once the case is open past 75% of the target; customer text is unchanged.

## Orders (customers: their own; staff: in scope)
| GET | `/orders?limit=` | any | – | `[{id, external_ref, brand_id, location_id, brand_name, location_name, placed_at, total_paise, status}]` (`brand_name`, `location_name` NEW) |
| GET | `/orders/{id}` | any | – | the above + `items: [{sku, name, quantity, quantity_fulfilled, total_paise}]`, `promised_at`, `completed_at`. 404 if not visible |

## Cases
| POST | `/cases` | customer | `{transaction_id, category: slug or null, message}` | case (201). `category: null` only when `free_text` |
| POST | `/cases/{id}/messages` NEW | customer (own case) | `{message}` (1-2000 chars) | case (201). Answers the AI's needs-info question; only while stage is `awaiting_info`, else 409. Other customers'/tenants' cases 404, staff 403. The case resumes (stage goes back to `investigating`) and the timeline gains a "You replied" step |
| GET | `/cases?limit=` | any | – | `[case]` newest first |
| GET | `/cases/{id}` | any | – | case. 404 if not visible |
| GET | `/cases/{id}/timeline` NEW | any who can see the case | – | `[{at, stage, title, text}]` oldest first: customer-safe steps. `stage` uses the stage names below: `received`, `investigating`, `awaiting_info` (question asked), `awaiting_approval` (remedy proposed), `processing` (approved), `declined`, `confirmed` (refund confirmed by the provider), `escalated`, `closed`. Text comes from code templates, never from a model. 404 if not visible |
| GET | `/cases/{id}/events` | staff | – | raw audit events (redacted) |

`case` = `{id, transaction_id, order_ref, category, stage, message, action, amount_paise, proposal_id, created_at}` (`order_ref`, `created_at` NEW; `order_ref` is the order's `external_ref` or null; `created_at` is when the case was opened).

Stages (show as a stepper; the happy path is received → investigating → awaiting_approval →
processing → confirmed): `received`, `investigating`, `awaiting_info`, `awaiting_approval`,
`processing`, `confirmed`, `declined`, `escalated`, `closed`. `message` is the text to show the
customer for the current stage.

## Privacy and data rights (S5.2)
| GET | `/me/consents` | customer | – | `{notice_version, consents: [{purpose, channel, granted, updated_at}], history: [{purpose, channel, granted, source, notice_version, at}]}`. No row means `granted: false`. Staff get 403 |
| POST | `/me/consents/{purpose}` | customer | `{granted: bool, channel?}` (`purpose` is `marketing`; unknown purpose or channel 404) | same shape as GET. Granting and withdrawing are the same call; withdrawal applies to the next send |
| GET | `/me/data-export` | customer | – | `{generated_at, profile: {name, phone, email, reference}, orders: [{order_ref, placed_at, brand, location, total_paise, status}], cases: [{id, order_ref, category, opened_at, stage, message}], consents: {as above}, processors: [{name, role, data}]}`. Own data only |
| POST | `/me/erasure-request` | customer | – | `request` (201). One active request per customer: a second call returns it |
| GET | `/me/erasure-request` | customer | – | the latest `request`, or `null` |
| GET | `/data-requests` | hq_owner | – | `[request + customer_ref]`, newest first |
| POST | `/data-requests/{id}/approve` | hq_owner | – | `request`. The server re-checks the guards: `completed`, or `deferred` with a reason. Unknown id 404 |

`request` = `{id, kind: "erasure", status: pending_approval | deferred | completed, reason, deferred_until, requested_at, completed_at}`. `reason` is server template text, set when `deferred` (open case, refund in flight, legal hold, or inside the one-year minimum); show it as given.

## Approvals (staff)
| GET | `/approvals?limit=&location_id=&action=&sort=` | staff | – | `[pending]`. `sort` is `oldest` (default), `newest` or `amount_desc`; unknown sort or action gives 422; a `location_id` the caller cannot see (or another tenant's) gives 404 |
| POST | `/approvals/{proposal_id}/decision` | staff | `{decision: approved or rejected, note}` | `{proposal_id, decision, expires_at, execution}`. 403 out of scope / over the role's limit, 409 already decided |

`pending` = `{proposal_id, case_id, category, action, risk, amount_paise, order_ref, order_total_paise, reason, checks, eligible, errors, created_at, customer_message, location_name, citations: [{section_ref, doc_key, version}]}` (`created_at`, `customer_message`, `location_name`, `citations` NEW). `checks` is a flat map of check name → bool; `errors` explain why `eligible` is false. In `citations`, `doc_key`/`version` may be null. `customer_message` is the customer's first message on the case (or null); show it as plain text, never as HTML.

## Insights (hq_owner, franchisee_owner)
| Method | Path | Who | Response |
| --- | --- | --- | --- |
| GET | `/insights/outlets` NEW | `hq_owner` (all outlets), `franchisee_owner` (own outlets); 403 for other roles | `[{location_id, name, cases_opened, refunds_confirmed_count, refunds_confirmed_paise, vouchers_issued_count, vouchers_issued_paise, median_decision_minutes, orders, repeat_rate_bp}]` |

Last 30 days. Money is integer paise (format with the money helper). `median_decision_minutes` is
null when nothing was decided; `repeat_rate_bp` (basis points, 3125 = 31.2%) is null with no orders.

## Growth (staff, tenant `growth` flag on; 404 when off)
| Method | Path | Who | Notes |
| --- | --- | --- | --- |
| GET | `/growth/signals` | staff | `[{id, location_id, metric, baseline_bp, recent_bp, baseline_n, recent_n, drop_bp, status, diagnosis: {findings, hypotheses}, diagnosis_source, recent_end, campaign_id}]` (`campaign_id` NEW: the signal's campaign once proposed, else null) |
| POST | `/growth/signals/refresh` | `hq_owner` | runs the signal job now; same list |
| POST | `/growth/signals/{id}/campaign` | staff | `{}` body; 201 campaign; 422 text on refusal (budget, audience) |
| GET | `/growth/campaigns/{id}` | staff | campaign |
| POST | `/growth/campaigns/{id}/approve` | staff | `{decision: approved or rejected}`; 409 already decided, 410 expired, 422 not eligible; show the `detail` text |
| POST | `/growth/campaigns/{id}/verdict` | staff | measures the result; 409 when the window isn't over |

`campaign` = `{id, signal_id, location_id, status, payload_hash, params, budget_paise, expires_at, sent_at, treatment_n, holdout_n, approvals: [{decided_by, role, decision, expires_at}], fully_approved, playbook: {verdict, uplift_bp, treatment_n, holdout_n, confidence_note, lesson} | null}`.
Sending needs two different approvers, at least one `hq_owner`; the server enforces it. The UI
shows `diagnosis.findings` (facts) and `hypotheses` (labelled unconfirmed), never model reasoning.

## Dev panel (demo only)
Mounted only when `APP_ENV` is `dev` or `test`; **404 in prod**. `hq_owner` only (403 otherwise), and
always the caller's own tenant, taken from the token. The frontend shows the "Dev panel" nav item
only for an hq_owner whose `GET /admin/chaos` succeeds; a 404 hides it.
| GET | `/admin/chaos` | hq_owner | – | `{service: {timeout_rate, transient_error_rate, accept_then_timeout_rate, error_rate, processing_rate, settle_after_polls, delay_ms, seed}}` |
| POST | `/admin/chaos` | hq_owner | `{service, timeout_rate?, accept_then_timeout_rate?, transient_error_rate?, error_rate?, processing_rate?, settle_after_polls?, delay_ms?, seed?}` (rates 0..1; omitted = default, so `{service}` alone resets it) | the full chaos state, as GET. 422 for an unknown service or a rate outside 0..1 |
| POST | `/admin/sweep` | hq_owner | – | `{executed, reconciled, escalated_cases, verified: [id], pruned_threads, events_published}`. Runs the crash-recovery sweeper for the caller's tenant, outside any open DB transaction |

There is deliberately no reseed or clock endpoint: use `make seed` and `make sweep`.

## CORS
NEW: the API allows the origins in `WEB_ORIGINS` (default `http://localhost:5173`), methods GET/POST,
header `Authorization`, `Content-Type`.
