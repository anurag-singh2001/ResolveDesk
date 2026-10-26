# Sprint 5 · Privacy basics and growth hardening

Status: proposed, user to confirm scope. Dates: to be set after Sprint 4 closes (no earlier than 2026-10-28).

## Planning (draft, 2026-10-27)
Goal: close the biggest "needed before real customer data" gaps (DPDP), harden the new growth path under failure, and polish staff screens.

Sources: README "Limits"; docs/research/market.md (R9 deletion workflow left as stretch; grievance-officer display from F12; Q6 verify legal items against official text); open items in docs/EPICS.md (E0.3 and E7.2 are human-only; follow-ups demo seed refreshing packs and dev-panel reseed are not in this sprint).

| # | Story | Owner | Est | Research first? | Done-when |
| --- | --- | --- | --- | --- | --- |
| S5.1 | DPDP: retention setting plus purge job for case messages | Sonnet builder, main reviews | M | yes (business-analyst: retention norms, what DPDP requires, checked against official text) | per-tenant `message_retention_days` setting; job redacts or deletes older messages with an audit row; tests for both tenants; safety review clean |
| S5.2 | DPDP: consent records plus customer access/erasure request flow | Sonnet builder, main reviews | L | yes (same pass as S5.1) | consent stored per customer with timestamp; customer files an access or erasure request, HQ owner works it, outcome audited; erasure keeps money records (paise amounts) and redacts PII; isolation tests + safety review clean |
| S5.3 | Growth chaos test: campaign sends under messaging chaos | Sonnet builder | M | no | with messaging failures and timeouts injected, zero duplicate sends and consent re-checked at send; included in `make test-chaos`, green x3 |
| S5.4 | Approvals-queue filter and sort (status, amount, age, location) | Sonnet builder | S | no | server-side, tenant-scoped query params; web tests cover each filter/sort; `make web-test` green |
| S5.5 | Grievance-officer display and acknowledge/resolve SLA marker (market.md F12, R5) | Sonnet builder | S | maybe (confirm wording against official rules text) | officer name/contact is a tenant setting shown on the customer portal; overdue marker (48 h acknowledge, 1 month resolve) visible to staff; tests for both tenants |
| S5.6 | Hindi templates for customer-facing messages | Sonnet builder | M | yes (which strings, language per customer vs per tenant) | needed-info and status templates have `hi` variants chosen by a customer language field; verifier still checks facts in either language; English fallback; tests for both tenants |

Not a story, 30 minutes: check that the Insights and Growth sections already in docs/manual/{hq_owner,franchisee_owner,location_manager}.md match the screens during the sprint walkthrough.

Order by value: S5.1, S5.2 (README says they are needed before real data), S5.3 (safety), S5.5, S5.4, S5.6.
Drop first if short: S5.6, then S5.4. Never drop tests or safety review (S5.1, S5.2, S5.3 touch retention, PII and idempotent sends).

Does not fit: S5.1 + S5.2 are close to a full sprint on their own. If the research pass is slow, start S5.3-S5.5 in parallel, with at most 2 heavy processes at once (Sprint 4 retro).

Carried human-only: E0.3 (rotate Neon owner password), E7.2 (copy .env into the clean clone and see an AI proposal).

Entry rule: Sprint 4 closed (final full suite and chaos green, test to main confirmed).

## Stand-ups
(none yet)

## Review
(pending)

## Retro
(pending)

## Scorecard
(end of sprint)
