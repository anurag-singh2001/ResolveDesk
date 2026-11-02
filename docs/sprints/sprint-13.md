# Sprint 13: hardening

**Dates:** 2026-11-03. **Planned:** 28 SP. **Goal:** prove the unmerged work, close privacy and money gaps found in review and pen testing.
Owner decisions (2026-11-03): phone and email stay visible to staff for now; if the customer on O0005931 does not answer, do nothing; reseed approved; main session checks S12.7, S12.8 and S12.11.

## Stories

| Story | SP | Done when |
|---|---|---|
| S13.1 Full regression, flaky chart tests, merge to main | 5 | full batches green, chart tests preload the lazy chunk, merged |
| S13.2 Contact view audit and privacy reject | 8 | one audit row per person, case and hour with no personal content; HQ rejects with a fixed reason, nothing erased, customer told in their language and can ask again; both tenants |
| S13.3 bc-wrong-002 and voucher limit note | 5 | scenario passes; rules summary says when a brand or outlet has a lower limit, 3 languages |
| S13.4 Reseed, Spice Route ROI, staff pages at 375px | 5 | after the O0005931 offer expires: demo reseeded, ROI checked, staff pages checked |
| S13.5 Queue sort, risk and action; order card language; sweeper | 5 | restored on Cases to handle; order card follows the customer's language; sweeper run once on the demo |

## Pen test

Static review by safety-reviewer, then live attacks on localhost against the eval database (never the demo).

| Finding | Severity | Result |
|---|---|---|
| Parallel wrong passwords outran the login lockout | Medium | Fixed: attempt slot taken before bcrypt under an advisory lock. Live: 30 parallel tries, 5 reached the password check, 25 got 429 |
| Five bad logins locked the platform operator out everywhere | Medium | Fixed: limit per source address, plus 50 across all sources |
| A second report on an order could earn a second voucher | High | Fixed: one voucher per order, in the action's own checks |
| refund_max_percent applied per refund, so two refunds could double it | High | Fixed: the limit counts earlier refunds on the order |
| Repeat reports queued another paid AI run and grew the case without limit | Medium | Fixed: only a new case starts a run; 50 customer messages per case |
| `$` in id patterns accepted a trailing newline | Low | Fixed |
| Public dev JWT secret with predictable ids | High if exposed | Not changed: APP_ENV defaults to prod, which refuses the dev secret. Never expose dev or test to a network |
| Dev clock is process-wide | Low | Not changed: dev and test only |
| Account lockout can be used to deny one user | Low | Accepted: a per-IP limit needs a real proxy setup |
| /auth/businesses lists tenants without login | Low | Accepted: the login page needs it |
| Safety review: a reject and an old approval could both win | High | Fixed: a rejected request is final for approve and withdraw |
| Safety review: two approved vouchers at once could both issue | High | Fixed: the executor locks the order row first |

## Found in end-to-end testing

- Scenario flows on the scratch DB: voucher to Confirmed, AI asks then customer replies, privacy reject, campaign proposed by a manager, approved by HQ and a franchisee, sending.
- The demo script had the HQ owner propose then approve, which can never send with one HQ owner. Script corrected, and HQ now gets a warning before proposing.
- A 403 hid the server's reason on Growth, and "2 of 2" showed while HQ approval was missing. Both fixed.
- Spice Route's default campaign was over the Rs 10,000 budget limit, so none could be proposed. `growth_campaign_budget_paise` for cloud kitchens is now Rs 60,000. Owner to confirm the figure.
- Signing in while the demo clock was moved gave a token dated in the future, refused on use. Tokens now use real time.
- All staff pages fit 375px with no page overflow.
- Not clicked through: the payment timeout path (no suitable order on the scratch data; covered by the chaos batch), the Spice Route measure step, a campaign with real calendar warnings (none overlapped; covered by web and backend tests).

Held under live attack: forged, tampered, unsigned and garbage tokens; tenant token on platform routes; customers on staff routes; customer and cross-tenant IDOR on orders; staff opening customer cases; bad switch amounts; parallel approval and replay (one refund confirmed); SQL text in a filter; oversized message.

## Open for review

New Hindi and Hinglish text was not in the approved review: `rules.narrower`, `erase.reject.*`, `erase.stage.rejected*`, the Order card labels.
