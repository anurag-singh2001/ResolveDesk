# Web frontend ↔ API contract (v1)

The React app (`web/`) talks only to this HTTP API. Every business rule stays in the API; the
frontend only displays what the API returns. Money is integer paise in JSON; the frontend formats
it as ₹ with 2 decimals. Times are ISO 8601 UTC; the frontend shows them in the browser's local
time. Tokens are bearer JWTs, kept in memory and `sessionStorage` (never `localStorage`).

`NEW` = to be added by the backend story E5.4; everything else exists today.

## Auth
| Method | Path | Who | Body / query | Response |
| --- | --- | --- | --- | --- |
| GET | `/auth/businesses` NEW | public | – | `[{slug, name, vertical}]` |
| GET | `/auth/demo-accounts` NEW | public, **dev only** (404 when `APP_ENV=prod`) | – | `[{tenant, email, name, role, password}]` |
| POST | `/auth/login` | public | `{tenant, email, password}` | `{access_token, token_type, expires_at}` (`expires_at` NEW). 401 `invalid credentials` (same for unknown user and wrong password). 429 NEW after 5 failures for one tenant+email in 15 min |
| GET | `/me` | any | – | `{user_id, name, email, role, location_ids, brand_ids, tenant: {slug, name, vertical}}` (`tenant` NEW) |

Roles: `customer`, `location_manager`, `franchisee_owner`, `hq_owner`. 401 on any call → token is
gone or expired: clear it and go to the login page with "Your session has ended".

## Meta
| GET | `/meta/categories` | any | – | `{categories: [slug], free_text: bool}` |

## Orders (customers: their own; staff: in scope)
| GET | `/orders?limit=` | any | – | `[{id, external_ref, brand_id, location_id, brand_name, location_name, placed_at, total_paise, status}]` (`brand_name`, `location_name` NEW) |
| GET | `/orders/{id}` | any | – | the above + `items: [{sku, name, quantity, quantity_fulfilled, total_paise}]`, `promised_at`, `completed_at`. 404 if not visible |

## Cases
| POST | `/cases` | customer | `{transaction_id, category: slug or null, message}` | case (201). `category: null` only when `free_text` |
| GET | `/cases?limit=` | any | – | `[case]` newest first |
| GET | `/cases/{id}` | any | – | case. 404 if not visible |
| GET | `/cases/{id}/timeline` NEW | any who can see the case | – | `[{at, stage, title, text}]` oldest first: customer-safe steps (received, investigating, question asked, proposed, approved/declined, refund confirmed, escalated). Text comes from code templates, never from a model |
| GET | `/cases/{id}/events` | staff | – | raw audit events (redacted) |

`case` = `{id, transaction_id, order_ref, category, stage, message, action, amount_paise, proposal_id, created_at}` (`order_ref`, `created_at` NEW).

Stages (show as a stepper; the happy path is received → investigating → awaiting_approval →
processing → confirmed): `received`, `investigating`, `awaiting_info`, `awaiting_approval`,
`processing`, `confirmed`, `declined`, `escalated`, `closed`. `message` is the text to show the
customer for the current stage.

## Approvals (staff)
| GET | `/approvals?limit=` | staff | – | `[pending]` |
| POST | `/approvals/{proposal_id}/decision` | staff | `{decision: approved or rejected, note}` | `{proposal_id, decision, expires_at, execution}`. 403 out of scope / over the role's limit, 409 already decided |

`pending` = `{proposal_id, case_id, category, action, risk, amount_paise, order_ref, order_total_paise, reason, checks, eligible, errors, created_at, customer_message, location_name, citations: [{section_ref, doc_key, version}]}` (`created_at`, `customer_message`, `location_name`, `citations` NEW). `checks` is a flat map of check name → bool; `errors` explain why `eligible` is false.

## CORS
NEW: the API allows the origins in `WEB_ORIGINS` (default `http://localhost:5173`), methods GET/POST,
header `Authorization`, `Content-Type`.
