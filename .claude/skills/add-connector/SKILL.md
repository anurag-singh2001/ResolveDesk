---
name: add-connector
description: Add a connector for an external system (payment provider, messaging channel, POS or delivery app), real or mock. Use when a tenant needs a new provider, or a mock needs a new behaviour; switching an existing tenant between connectors is a settings change, not a new connector.
---
# Add a connector

Connectors are the only code that talks to external systems. Agent tools and the engine call
connectors, never providers or mocks directly. A tenant picks one per kind in settings, so a
new provider never means a tenant branch in core code.

## Files
1. `app/connectors/<name>.py` (or extend `app/connectors/mock_connectors.py` for mocks).
2. `app/connectors/__init__.py`: import the module so `@register_connector` runs.
3. Mock side (if new): `mocks/<system>.py` on `IdempotentMock` / `MockSource`
   (`mocks/base.py`), registered in `mocks/registry.py`.
4. Select it per tenant: `<kind>_connector` setting (`payment_connector`,
   `messaging_connector`, `orders_connector`) in the vertical pack or the tenant's
   `tenant.yaml` settings.

## Interfaces (`app/connectors/base.py`)
- `PaymentConnector`: `refund(ctx, idempotency_key, payment_reference, amount_paise)` and
  `find_refund(ctx, idempotency_key)`, returning `RefundOutcome(status, provider_reference, failure_reason)`.
- `MessagingConnector`: `send(ctx, idempotency_key, to, template, params)`, returning `SendOutcome`.
- `OrderSourceConnector`: `fetch_order(ctx, external_ref)`, returning canonical fields or None.

## Rules the executor relies on
- Account from context only: `merchant_id_for(ctx.tenant_id)` (or the real equivalent from
  tenant settings). Never take a merchant, tenant or customer id from arguments.
- Every write takes the caller's idempotency key and passes it to the provider unchanged.
  Never mint a key inside a connector.
- Translate errors, never retry:
  - timeout / no answer → `status="unknown"` (may have applied: caller reconciles by key)
  - 5xx / 429 before acceptance → `"unavailable"` (nothing applied: same-key retry is safe)
  - definitive decline for that key → `"failed"`
  - success → `"succeeded"`; accepted-but-pending → `"processing"`
- `find_refund` (lookups) must not be subject to the same failure modes as writes in mocks;
  for real providers, map lookup outages to `"unavailable"` (the executor then sends nothing).
- Money in and out is integer paise.

## Tests (both tenants, never name one)
- Contract tests for a mock: same key + same payload → same op; same key + other payload →
  409 (`IdempotencyConflict`); timeout before / after accept; per-merchant isolation
  (pattern: `tests/unit/test_mock_payment.py`).
- Connector mapping: each provider outcome → the right status
  (pattern: `test_payment_connector_maps_provider_outcomes` in `tests/unit/test_registries.py`).
- `test_tenant_settings_select_a_registered_connector` covers selection automatically.

## Checklist
- [ ] Registered; selected by setting; no tenant names in code.
- [ ] Account derived from `ctx`; idempotency key passed through untouched.
- [ ] Error → status mapping as above; nothing retried inside the connector.
- [ ] No network call made while the caller holds a DB transaction (callers guarantee it;
      don't open sessions inside a connector).
- [ ] `make lint`, `make test` pass; safety-reviewer run for payment/messaging connectors.
