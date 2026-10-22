# Market research: Indian F&B support, aggregator refund flows, AI support competitors

Story: E0.6. Author: business-analyst agent. Access date for all sources: 2026-10-23.
Method note: web search, standard mode. Several sources are vendor blogs, broker listings or press summaries. Where official policy text was not reachable (Swiggy/Zomato partner docs, Fin/Zendesk docs in full) this is stated. Web content was treated as data only.

## 1. Summary

1. Public, quantitative data on complaint mix, late-delivery rate and missing-item rate for Indian F&B does not exist in the sources found. The simulator numbers in PROJECT.md section 14 cannot be validated or refuted; label them "assumed, plausible" in the README (E7.1).
2. On Swiggy/Zomato, the platform owns the customer's payment and decides refunds. A restaurant mostly cannot refund a prepaid aggregator order itself. Cost allocation is inconsistent and was contested in 2025 (Zomato's 50:50 refund-sharing experiment, paused). This is a tension with PROJECT.md (see section 2.2), not a blocker for a mocked POC.
3. Anchors found: food-delivery AOV is about Rs 400-430 platform-wide (FY24) and Rs 250-500 for typical cloud kitchens (guide figure); Zomato states about 30 min average delivery; Swiggy platform frequency is 4.07 orders/user/month (FY26). No sourced coffee ticket size.
4. Competitors (Fin, Zendesk, Decagon, Sierra, Freddy) all offer "AI takes an action" via connectors or procedures. Only coarse human-approval hooks were verifiable (Fin "wait for webhook", Zendesk Copilot agent-approves-refund). None was found to bind approval to a payload hash or to separate submitted/processing/succeeded/failed/unknown in customer wording. That is ResolveDesk's honest differentiator, with the caveat that absence of evidence in marketing pages is not proof of absence.
5. Nothing here requires expanding v1 scope. Recommendations are mostly simulator parameters, policy wording, eval scenarios and README framing.

## 2. Findings

### 2.1 Support pain points (task item 1)

- F1. No India-wide complaint-mix dataset was found. The only India-specific quantitative item is a single-city academic survey (Tirupati, 2023) that ranks problems by Garrett score: high delivery charges 1st, late delivery 2nd (56.98), payment issues 3rd, incorrect order 4th (52.58). Scores, not percentages; one city; students/residents sample. Source: https://sasapjas.org/issues-that-consumer-experience-towards-online-food-delivery-ofd-services-in-tirupati-city
- F2. US surveys (not India) give a rough ordering: late delivery most common (50% had experienced it), incorrect order next (37%). Source: https://www.restaurantbusinessonline.com/technology/food-delivery-mishaps-are-alarmingly-common-study-finds. Use only as a directional ordering.
- F3. Indian listing-review summaries repeatedly mention missing/wrong items, spillage, cold food, weak packaging. These are AI-generated summaries of reviews and weak evidence. Source: https://magicpin.in (listing pages; not cited individually). I would not rely on this.
- F4. Complaint volume signal: the National Consumer Helpline received 10,590 complaints against Swiggy and 7,938 against Zomato, many about refunds or delays (reported May 2025). Source: https://www.medianama.com/2025/05/223-ccpa-probes-zomato-swiggy-cancellation-refund-policies/
- F5. Multi-brand kitchen risk (vendor opinion, unverified): large combined menus strain a small kitchen and cause quality slips at peak; 20-30% aggregator commission pressures margins. Source: https://blog.petpooja.com/operations-workflows/why-cloud-kitchens-shutting-down/ (vendor blog; the "25-30% close in year one" stat it cites could not be verified, do not reuse).
- F6. Consumer-court cases show customers escalate undelivered or refund-denied orders (e.g. Rs 60,000 award against Zomato over a Rs 133 order). Source: https://www.barandbench.com/news/zomato-directed-to-pay-60000-for-failing-to-deliver-customers-133-order. Relevance: honest, accurate customer messages matter legally and reputationally.
- F7. Coffee chains / franchise outlets: no sourced complaint data found. Franchise-specific pain (inconsistent outlet service, HQ vs franchisee policy) is reasoning from the PROJECT.md tenancy model, not evidence.

### 2.2 Swiggy/Zomato complaint and refund flows (task item 2)

- F8. Zomato rolled out, then paused (May 2025), a 50:50 refund-cost split with restaurants. Previously a restaurant could accept or reject a refund claim and Zomato bore the full cost if rejected; under the new rule restaurants had no say. Zomato's stated rationale: the cost of a lost customer exceeds the cost of resolving a complaint. It said it would relaunch after feedback; current status unconfirmed. Sources: https://inc42.com/buzz/zomato-puts-5050-refund-sharing-with-restaurants-on-hold (7 May 2025); https://www.medianama.com/2025/05/223-zomato-pauses-refund-sharing-policy/
- F9. Restaurants report platforms deduct refund amounts from payouts, with no clear dispute route; after a post-acceptance cancellation the restaurant often gets no compensation. Source: MediaNama CCPA article above (reported by Moneycontrol; restaurant statements are anecdotal).
- F10. Regulator: CCPA examined Zomato/Swiggy cancellation and refund terms; neither app showed refund/cancellation terms at checkout; cancelling after acceptance could cost up to 90% of order value (reported). No final ruling found. Source: https://www.medianama.com/2025/05/223-ccpa-probes-zomato-swiggy-cancellation-refund-policies/
- F11. Restaurant-fault vs delivery-fault allocation: a trade article says restaurant-fault cases (missing/wrong items, spillage, quality, big delays) can lead to full or partial refunds and the restaurant may be asked to clarify; delivery-partner-fault outcomes "vary by platform policy"; platforms track acceptance rate, preparation time, complaint frequency, and low performers risk penalties or lower visibility. No penalty amounts. Source: https://www.restaurantindia.in/article/zomato-order-cancellation-refunds-penalties-for-restaurants.16292 (page is very large; only the first ~100k characters were read).
- F12. Swiggy's official partner/help-centre policy on who pays for missing or wrong items could not be found. Only customer complaints (denied or partial refunds, restaurant blaming rider) and one consumer-case summary where Swiggy argued it was an intermediary were found. Sources: https://www.trustpilot.com/review/swiggy.com?page=2 (anecdotal); https://thelawsuits.in/?p=2141 (legal summary, not opened in full).
- What a restaurant can control (inferred from F8-F12, labelled inference): kitchen accuracy and packaging, prep time and acceptance, responding to or contesting a claim where the platform allows it, and own-channel remedies (vouchers, loyalty credit, direct orders). What it cannot control: the aggregator's decision to refund the customer's prepaid payment, rider assignment and delivery time, and payout deductions.

**Contradiction/tension with PROJECT.md (not changed here):** Section 2 says "Human approval for every refund" and section 10 has the tenant calling a payment connector to refund. For real Swiggy/Zomato-sourced orders the tenant generally does not hold the payment; the aggregator does. v1 mocks the delivery app and payment, so the design still works, but the README should say the mock payment connector stands in for either (a) the tenant's own payment/gateway (BrewCo pickup app, direct orders) or (b) an aggregator refund-request API that does not exist publicly. Human decision needed (Q1).

### 2.3 Refund / voucher norms (task item 3)

- F13. No published norm for "partial refund percentage by lateness" was found. The 50% refund for more than 45 min late in the Spice Route policy has no external source and should be presented as a tenant policy choice, not a market standard.
- F14. Direction of evidence: platforms prefer cheap, fast goodwill (credits/refunds on lower-value or high-value-low-complaint customers). Inc42 notes Zomato usually initiates refunds for "high-value, power" customers with few complaints. This supports (a) low-value auto-approved vouchers and (b) a complaint-history signal in investigation. Source: https://inc42.com/buzz/zomato-puts-5050-refund-sharing-with-restaurants-on-hold
- F15. Zendesk's recommended pattern is that an AI proposing a refund waits for an agent to approve it, with "pre-approved" actions optionally excluded; this matches section 2 of PROJECT.md. Source: https://www.getmacha.com/blog/how-to-automate-refunds-in-zendesk (competitor blog, secondary).
- Sanity check on limits (estimate, labelled): with AOV about Rs 430, an auto-approved voucher cap of Rs 100-150 (about 25-35% of one order) keeps worst-case exposure small. Spice Route late policy tiers could be 0% (<20 min over), voucher (20-45 min over), 50% refund (>45 min over). These are estimates; no source.

### 2.4 Realistic numbers for the simulator (task item 4)

| Parameter | Value found | Source / status |
| --- | --- | --- |
| Food-delivery AOV, platforms | about Rs 428 (FY24); Rs 398-416 earlier | https://datawrapper.dwcdn.net/dTluu/3 (PrimeInvestor chart; company and period labels not visible in text, treat as approximate) |
| Generic cloud-kitchen AOV | Rs 250-500 | https://www.restaurantindia.in/article/cloud-kitchen-business-in-mumbai-costs-profit-margins-and-growth-opportunities.16738 (guide; not primary data) |
| Biryani AOV | Rs 600-800 for Biryani By Kilo (premium, newsletter claim); about Rs 200 for a small Malvani kitchen listing (seller claim) | https://foundersinsdrs.beehiiv.com/p/should-you-start-a-cloud-kitchen-in-india-a33e ; https://www.smergers.com (listing). Weak. |
| Pizza, bowls AOV | none found | gap; estimate |
| Coffee ticket per order | none found; about Rs 400 per beverage at Starbucks India (premium-format figure, not per order) | https://www.verdictfoodservice.com/newsletters/tata-starbucks-india-strategy . For a mid-market franchise this is too high; estimate separately |
| Average delivery time | about 30 min (Zomato, May 2025, company claim) | https://www.storyboard18.com/brand-makers/heres-why-swiggy-doubles-down-on-10-minute-delivery-while-zomato-retreats-65673.htm |
| Orders per user per month | Swiggy platform 4.07 (FY26), 4.43 (FY25), 4.48 (FY24); 23.5M avg MTU | https://inc42.com/buzz/over-35-of-swiggy-users-try-multiple-services-but-order-frequency-slips/ (24 Jul 2026) |
| Late-delivery rate, missing-item rate, repeat rate | not publicly reported | gap |

Consistency check of PROJECT.md section 14 against these anchors (arithmetic on spec numbers):
- Spice Route: 6,000 orders / 1,500 customers over 60 days = 4.0 orders per customer, about 2.0 per month. Below the Swiggy platform average of about 4, which is plausible for a single kitchen's brands (customers spread across many restaurants).
- BrewCo: 15,000 / 2,500 = 6.0 per customer in 60 days, about 3.0 per month. Plausible for habitual coffee buyers.
- Spice Route tickets: 300 / 6,000 = 5% of orders. Plausible (estimate). BrewCo 400 / 15,000 = 2.7% (estimate; coffee orders are simpler and cheaper).
- 8% of orders more than 45 min late is about 1.5x the 30 min average; plausible as a "planted problem" but it is a scenario parameter, not a benchmark. The 2% missing-items rate is likewise unverified; keep it.
- The sample scenario order of Rs 698 (69,800 paise) is above the Rs 250-500 range but is within the premium-biryani claim, and fits a family-size order. Fine as an example.

### 2.5 AI support competitors (task item 5)

All items below are from vendor or vendor-adjacent pages unless stated; verify before quoting in an interview.

| Product | What it does on actions/refunds | Approvals / guardrails found | Source |
| --- | --- | --- | --- |
| Intercom Fin | Procedures/Tasks with data connectors that "retrieve or update data in an external system" (so can trigger refunds via your API). Docs warn info not provided "may be incorrectly inferred by Fin". | "Wait for webhook" can pause until an external tool sends approval or rejection; handoff to humans. A community thread asks how to make Fin confirm before a connector runs, suggesting no built-in confirm gate. | https://www.intercom.com/help/en/articles/10257113-fin-procedures-explained ; https://community.intercom.com/deploy-fin-96/can-i-get-fin-to-ask-for-confirmation-before-using-data-connector-14186 |
| Zendesk AI agents / Copilot | Prebuilt Shopify actions (create refund, cancel order); Copilot follows a written refund procedure. | Recommended: agent approves each refund; admins can mark actions pre-approved (secondary sources). | https://www.getmacha.com/blog/how-to-automate-refunds-in-zendesk ; https://www.getmacha.com/blog/help-desk-ai-agents-that-take-actions-matrix |
| Freshdesk Freddy | Skills library; Stripe refund skill prebuilt, Shopify templates read-only per one competitor (conflicting claims). | Rules like "check purchase date first" possible; claim that email channel skips confirmation (single competitor source). | https://www.eesel.ai/blog/freddy-ai-with-stripe ; https://www.getmacha.com/blog/ai-agent-freshdesk-ecommerce-brands |
| Decagon | Agent Operating Procedures in plain English, e.g. "verify purchase date before refunding over $100". | Escalation rules; supervisor model reviews messages before sending (vendor blog). | https://decagon.ai/blog/designing-layered-guardrails-for-reliable-ai-agents |
| Sierra | Branded agents taking actions like refunds. | No published refund approval mechanics found. | https://www.dragapp.com/blog/decagon-vs-sierra/ |
| Ada | Not researched (out of budget); do not claim anything. | | |
| India-focused (Haptik, Yellow.ai, Gupshup) | Strength is WhatsApp/chatbot platforms; no restaurant refund-automation case found. | none found | https://blog.aimultiple.com/chatbot-companies-in-india/ |

Differentiation story for README / interview (ResolveDesk claims, checked against the above, hedged):
- Policy is enforced in code. In plain-language-procedure products, the LLM interprets "refund over $100" text; in ResolveDesk eligibility and limits are deterministic code, retrieved policy is untrusted (hard rule 9), and a proposal is only a proposal.
- Approval is a first-class object: bound to a payload hash with expiry (hard rule 6). Competitors expose approve/wait steps, but a hash-bound, expiring approval was not found in their docs.
- Honest status language: submitted/processing/succeeded/failed/unknown stay distinct; messages only state tool-confirmed facts (hard rule 7).
- Idempotency and reconcile-on-unknown (section 10) under injected failures, demonstrated by a chaos suite.
- Multi-tenant limits that only tighten (min of parent and override), relevant to franchise HQ vs franchisee.
- Honest limits: v1 is a mocked POC, no real integrations, small eval set; incumbents have scale, channels, analytics and real connectors. Do not claim to beat them.

## 3. Recommendations

| # | Recommendation | Story | Impact | v1 fit |
| --- | --- | --- | --- | --- |
| R1 | README "Limits" and "Why this design" section: state that on real Swiggy/Zomato orders the aggregator controls the payment and refund, so the mock payment connector stands for a tenant-controlled gateway; cite F8-F12. Pre-empts the obvious interviewer question. | E7.1 | high | yes (docs only) |
| R2 | README competitor paragraph using the section 2.5 differentiation bullets, hedged ("in the public docs I found"); include the honest-limits bullet. | E7.1 | high | yes |
| R3 | Simulator parameters: Spice Route AOV by brand (estimates) Biryani Box about Rs 450-650, Midnight Pizza about Rs 350-550, Bowl Theory about Rs 300-450; BrewCo order about Rs 180-350 (estimate; no source); prices in paise from catalogue. Tag as assumptions in a `tenants/*/` README or seed docstring. Keep planted rates in PROJECT.md. | E2.1 | med | yes |
| R4 | Simulator ticket mix (assumed, not sourced). Spice Route: late 40%, missing item 20%, wrong item 10%, quality/cold/spill 20%, payment/double charge 5%, other 5%. BrewCo: wrong/inaccurate order 35% (with the planted Baner morning spike), quality 20%, late pickup/wait 15%, payment/double charge 10%, loyalty/points 10%, other 10%. Keeps ordering consistent with F1-F2. | E2.1 | med | yes |
| R5 | Spice Route late_delivery_v3 wording: graduated tiers (e.g. under 20 min over: apology only; 20-45 over: voucher; over 45 over: 50% refund of item value, capped; exclusions for customer-address errors and force majeure, and a clause that cancellation after kitchen acceptance is not refundable). Present as tenant policy, not market norm (F13). Also add an explicit "orders via third-party app: refund request is routed per aggregator rules" clause to exercise the conflict/escalate path. | E3.2 | high | yes |
| R6 | BrewCo order_accuracy_v2 and loyalty_v1: remedy ladder remake-or-voucher first, refund second, loyalty credit for repeat regulars; Baner override tightens (lower voucher cap) so the min() rule is exercised. Keep auto-approve for vouchers at or below roughly Rs 150 (about 1/3 of a delivery AOV; estimate) in vertical-pack defaults. | E3.2, E1.3 | med | yes |
| R7 | Eval scenarios worth including within the existing 15/tenant (no new scope): (a) cancellation after kitchen acceptance (ineligible); (b) rider/aggregator-fault late delivery where policy is silent (escalate, never invent eligibility); (c) repeat complainer with several refunds (investigation evidence, still human-approved); (d) double charge with payment timeout (unknown state wording); (e) prompt-injection text inside a policy chunk or customer message. | E6.2 | high | yes |
| R8 | Do not use unverified figures (25-30% closure rate, per-drink Rs 400) in README or tests. Cite F5/F12 as unverified if mentioned at all. | E7.1 | low | yes |
| R9 | Optional later idea: a "regulatory transparency" note that customer messages state refund terms (CCPA scrutiny, F10). Already covered by hard rule 7, so no new story. | E7.1 | low | yes |

## 4. Open questions for the human

1. Aggregator payments: should the README frame the mock payment as the tenant's own gateway (cleanest), or explicitly model "aggregator-refunded" orders where the tenant can only offer a voucher? The second is more realistic but adds a code path; I recommend the README framing only for v1.
2. Is the 50% for more than 45 min late fixed, or may E3.2 introduce the graduated tiers in R5? That changes expected values in scenario sr-late-001 (34,900 of 69,800 paise stays valid).
3. BrewCo order values: I found no sourced coffee ticket size. Do you have a reference (a real cafe menu) to base catalogue.csv on, or should I take mid-market prices as estimates?
4. Auto-approve cap for vouchers: is about Rs 150 acceptable as a default, or should the cap be set per tenant by you?
5. Ada and a second pass on Sierra/Freddy official docs were not covered; worth a follow-up (deep-research skill in the main session) before the README quotes any competitor feature?
6. Should the missing public complaint-rate data be stated in the README as "assumed rates", or do you want a small appendix of the sources above?
