# What HQ marketing needs, and how S11.2 to S11.4 should deliver it

Story S11.1. Prepared 2026-10-28. Not legal advice.
Method: web search plus a read of the repo (docs/PROJECT.md section 17, docs/ROADMAP.md, docs/EPICS.md E18, app/modules/growth/, app/core/models.py, app/api/routes_growth.py, verticals/*.yaml, docs/research/privacy-page-needs.md).
Limits: for the web sources below I read search summaries, not the full pages. I could not open the Swiggy or Zomato partner portals, Meta's rate card, or any TRAI primary text. Vendor blogs are marked as vendor claims. Nothing in section 2 is an audited benchmark. Estimates are marked "estimate".

## 1. Summary

1. What exists is a single-location win-back loop: one repeat-rate signal per location, one lapsed-customer audience, a 10% holdout, dual approval, WhatsApp send, and a repeat-order verdict. It is solid on safety (hash-bound approvals, consent filter, idempotent sends) but has no HQ view: no list of campaigns, no brand cut, no segments, no revenue or cost in the verdict.
2. HQ marketing teams in Indian F&B need five things: who our customers are (segments and cohorts), what is planned and what already went out (calendar with overlap and fatigue warnings), whether an offer paid for itself (incremental, not raw, return), which brand or outlet is slipping, and how much of the base they can legally contact at all.
3. The biggest realism finding: spice_route has one kitchen, so location-level signals are meaningless for it. Its only useful cut is by brand (Transaction already carries brand_id). Brand-level signals (S11.4) are therefore not a nice-to-have for that tenant, they are the only signal.
4. The second: holdout verdicts will mostly say "inconclusive" at these tenant sizes. A 10% holdout of a few hundred lapsed customers cannot detect a realistic lift (rough power sums in section 2.5). ROI screens must show required audience size and say "not enough people to tell", never a flattering raw difference. The existing verdict code already does this; S11.3 must not weaken it.
5. All three build stories fit v1 scope as extensions of the existing growth module. No new Python or web dependency is needed (Recharts is already approved). Two schema changes are needed (brand-level signals and campaigns; a revenue/cost field for ROI) and need owner-run migrations and safety review. One contradiction with PROJECT.md is flagged in 2.7.

## 2. Findings

### 2.1 What HQ marketing teams do (and what the Indian chains show)

| Topic | What I found | Source (accessed 2026-10-28) | Use for ResolveDesk |
|---|---|---|---|
| RFM for restaurants | Score customers 1 to 5 on recency, frequency, spend over about 12 months; groups such as Champions, Loyal, At-Risk, Recent, Lost. Suggested actions: rewards for Champions, reactivation for At-Risk, win-back for Lost. | https://www.spoonity.com/llms-docs/rfm-marketing-loyalty.md (vendor) | Use a small named segment set, not 125 RFM cells. |
| India RFM thresholds | Fixed rules like "no order in 30 days = at risk" misfire because QSR guests order weekly while fine dining guests visit rarely; vendor recommends percentile (quintile) scoring per brand so thresholds adapt. | https://www.uengage.io/spotlight/rfm-analysis-for-restaurants-in-india (vendor, directional) | Compute thresholds per brand from its own data, not one fixed 28 days. |
| Lapsed champions | High frequency and spend, low recency, are the prime reactivation targets; a larger offer plus a nudge for a second order is a common pattern. | https://metricgate.com/docs/customer-segmentation-rfm/ ; https://spotler.com/en-gb?p=123033 (vendor) | A "lapsed regulars" segment fits the existing PROJECT.md audience wording. |
| Repeat benchmarks | Vendor blogs: QSR repeat 30-40% within 90 days; aggregator-acquired first-time customers return in 30 days only 18-25%; acquisition costs 5-7 times a retention action. All unsourced to primary studies. | https://reelo.io/blog/retention-benchmarks-for-restaurants-in-india ; https://restro-logic.pages.dev/blog/restaurant-customer-analytics-repeat-orders-india.html (vendor) | Use only as sanity ranges for the simulator, label "estimate". |
| Rebel Foods / EatSure | Company-reported: 80% of orders on its own app are repeat (no definition or window given). Points-based EatSure Elite unlocks at 1000 points; management targets for loyal users are 20% higher retention and 40% higher frequency (projections, not results). Multi-brand "food court on an app" lets one order span brands. A tracker shows one brand paused for low repeat, so retention differs a lot by brand. | https://india.entrepreneur.com/?p=867 ; https://startupwired.com/2024/10/09/eatsure-elite-redefining-loyalty-programs/ ; https://blog.privatecircle.co/?p=58199263 | Multi-brand kitchens must compare brands side by side, and a customer can belong to more than one brand. |
| Domino's India | About 15 million app MAU and 37 to 40+ million loyalty members (sources differ), Cheesy Rewards said to drive over 50% of orders (third-party). A MoEngage case study quotes CRM reaching customers 4-5 times a day, tied to points-to-free-item nudges. | https://www.alphaspread.com/security/nse/jublfood/investor-relations/earnings-call/q1-2026 ; https://info.moengage.com/hubfs/Dominos%20MoEngage%20Case%20study%202024.pdf | Shows the fatigue risk: big chains message heavily. Our frequency cap (30 days between campaigns) is deliberately far stricter; HQ should see cap hits. |
| Starbucks India (Tata) | June 2026 revamp: tiers Green, Gold (1,000 Stars within a year), Reserve (5,000+ Stars); 1 Star per Rs 10; Gold earns 1.2x, Reserve 1.3x; birthday rewards, double-star days. | https://www.restaurantindia.in/news/restaurant-india-news-tata-starbucks-launches-new-starbucks-rewards-program-with-reserve-tier.n16568 (search summary) | Tiered loyalty by spend over a rolling year. Tiers should be a segment view first, a loyalty product later. |
| Third Wave Coffee | One third-party blog (not official): coins as 10% cashback, redeem from 50 coins, tiers by transaction count (15 in 90 days, 45 in 180 days), referral reward. Official app listing confirms Wave Coins and subscription packs. | https://www.theflyy.com/blog/how-third-wave-coffee-roasters-use-gamification ; https://apps.apple.com/app/id1479552487 | Frequency-based tiers suit a coffee franchise. Treat thresholds as unverified. |
| Aggregator ads | Zomato and Swiggy sell sponsored listings, banners and discounts; billing is per click or impression; a trade article says weekly spend of Rs 18,000-20,000 can be needed just to stay visible. Restaurants allege ads and discounts were applied without consent and deducted from payouts (one example: Rs 27,500 billed against a Rs 6,700 authorised budget). I found no official dashboard or API documentation. | https://www.restaurantindia.in/article/zomato-ads-cost-is-restaurant-advertising-worth-it.16009 ; https://www.outlookbusiness.com/start-up/news/restaurants-allege-zomato-swiggy-charge-them-for-ads-discounts-without-consent | Aggregator ad spend cannot be pulled by code in this POC. HQ needs a place to record it by hand, and a warning that platform-applied discounts exist. |
| WhatsApp cost | Marketing template in India about Rs 0.86 per message after a roughly 10% rise on 1 Jan 2026; utility about Rs 0.11-0.15, free inside an open 24-hour service window. Third-party figures disagree (BSP markups, GST). Confirm against Meta's rate card. | https://developers.facebook.com/docs/whatsapp/pricing ; https://authkey.io/blogs/?p=1840 ; https://m.aisensy.com/blog/whatsapp-business-pricing/ | Cost per send is a tenant setting in paise (estimate default 86 paise), included in ROI. Marketing is not free, and win-back messages are marketing, not utility. |

Channel mix reality for the POC: the code sends only on WhatsApp (consents.channel allows whatsapp, sms, email). SMS for promotions in India also sits under TRAI rules (sender and template registration on DLT, mandatory for commercial SMS since 2019 per a vendor guide) and push needs an app that neither tenant has. I could not read TRAI primary text. Recommendation: treat WhatsApp as the only live send channel in v1; show SMS, push and aggregator ads as "not connected" rows in the channel view, with manual spend entry for aggregators. Source for the SMS point: https://www.messagecentral.com/en-in/sms-guideline/india (vendor, secondary).

### 2.2 Consent limits on marketing messages (DPDP)

All items below reuse docs/research/dpdp-and-hindi.md and docs/research/privacy-page-needs.md (sources there accessed 2026-10-27/28); the vendor guide above agrees.
- Consent must be free, specific, informed and a clear affirmative act, and withdrawing must be as easy as giving it (s.6). https://dpdpa.com/dpdpa2023/chapter-2/section6.html
- Consent for one purpose (delivery updates) does not carry over to promotions. Our reading: help messages need no marketing consent, promotions do. Verify with counsel.
- The fiduciary must be able to prove consent. ResolveDesk already keeps append-only `consent_events` with notice version, channel and source, plus the current-state `consents` table.
- Duties start 13 May 2027 per trackers (https://legismith.com/dpdp-rules-2025-timeline/), so building now is early, which suits a portfolio POC.
- The one existing safe rule: `lapsed_audience()` requires a `consents` row for channel whatsapp, purpose marketing, granted; no row means no consent. This is the right default.
- Implication for segments: counting and describing customers from order history is analysis. Contacting them is marketing. So a segment should show two numbers, "in segment" and "contactable on a channel", and only the contactable set can ever become an audience. (Design view, estimate of legal position: confirm with counsel.)

### 2.3 Metrics that matter by hierarchy level (synthesis, not a surveyed standard)

The only direct source found was one anecdote of a QSR giving brand and franchise owners daily, weekly or monthly outlet reports (https://medium.com/hashtag-loyalty/how-a-leading-qsr-leveraged-a-rewards-program-via-hashtag-loyalty-to-increase-repeat-purchases-and-23ff010658f4, vendor case study). The split below is my synthesis and should be treated as an estimate.

| Level | Question they ask | Metrics | Notes |
|---|---|---|---|
| HQ (hq_owner) | Which brand or region is slipping, and did our spend pay back? | Active customers, new vs repeat share, 30/60/90-day repeat by cohort, brand repeat rate, share of base contactable, campaign cost, incremental orders and revenue, ROI, offer budget used | Tenant-wide and by brand. Can approve campaigns. |
| Franchisee owner | Is my group of outlets worse than the network, and should I join a campaign? | Same, restricted to their locations; outlet vs network gap | Customers belong to the tenant, so a franchisee must see aggregates only for their locations, never the customer list from other outlets. |
| Location manager | What do I do this week? | Repeat rate vs own baseline, lapsed regulars count, open signal, running campaign result | Read only; no money decisions. |

Small-number rule (design suggestion): hide any segment or cohort cell under 10 customers for non-HQ roles, so an outlet view cannot be used to identify a person. Estimate for the threshold; product decision.

### 2.4 What exists today (read from the repo)

- `signals.py`: repeat-rate drop per location only. Windows 21 days recent vs 28 days baseline; flag if drop is 5 points or more, 30+ orders in each window, one-sided z of 1.64. Rates in basis points. Idempotent per location and window. Template diagnosis, optional LLM summary.
- `campaigns.py`: one campaign per signal (unique constraint), win-back only, lapsed means no order at that location for 28 days, WhatsApp marketing consent required, one customer per phone, 30-day frequency cap through `campaign_members`, holdout percent from setting `growth_holdout_percent` (default 10), budget cap setting `growth_campaign_budget_paise` (default Rs 10,000), offer and window as parameters, dual approval (two different staff, one hq_owner), proposal TTL 48h and approval TTL 24h, payload hash covers the audience.
- `executor.py`: sends through the messaging connector with one stable key per member; holdout members are never contacted (also a DB check constraint); timeout is `unknown`, not sent.
- `verdict.py`: share of treatment who ordered at that location in the window vs the share of the holdout; intention to treat; needs 20 per arm; two-sided z at 1.96; writes a playbook entry.
- API (`routes_growth.py`): list signals, refresh, propose, get one campaign, approve, verdict. There is no "list campaigns" endpoint.
- Data: `transactions` has brand_id, location_id, source, total_paise, placed_at, status; `customers` is tenant-level with home_location_id and attributes jsonb; `brands` and `location_brands` exist; settings can be scoped to brand or location.
- The web Growth page is a table of signals and campaigns (docs/ROADMAP.md says "no charts, no hierarchy views, no HQ marketing module").

### 2.5 Statistical reality for holdouts

- Vendor guidance: holdouts of 5 to 20%, tests of 4 to 12 weeks, size by power analysis from baseline rate and expected lift (80% power, 5% alpha); contamination and underpowered tests are the main failures; one vendor example needs about 5,000 per group to see a 20% relative lift on a 2% baseline. Sources: https://agilebrandguide.com/wiki/methods/holdout-campaign/ ; https://hyros.com/updates/incrementality-testing ; https://metricgate.com/docs/incrementality-test (vendor, heuristics).
- My arithmetic (estimate): to see a 5-point lift on a 20% repeat rate with 80% power and 95% confidence needs roughly 1,100 customers per arm. At a 10% holdout that means an audience of about 11,000 lapsed customers. A single BrewCo outlet will not have that. The existing floor of 20 per arm only stops nonsense; it does not make a result trustworthy. Brand-wide or all-outlet campaigns, a larger holdout (20%), and a longer window are the realistic levers. S11.3 should show "people needed to detect a 5 point lift" next to the audience size.
- Cost side (estimate, from the code): campaign cost today is the budget cap (offer x treated). Real cost is offers redeemed, which the data model does not record. See open question 2.

### 2.6 Gap map

| Need | What exists | Gap | Covered by |
|---|---|---|---|
| Customer segments (new, active, loyal, at risk, lapsed, lapsed regulars, one-and-done) | Only the single lapsed rule inside `lapsed_audience` (28 days, one location) | No reusable segment definitions, no per-brand thresholds, no counts, no contactable split | S11.2 |
| Cohorts (first-order month, M1/M2/M3 return) | Nothing; repeat rate is windowed per location | No first-order cohort retention table | S11.2 |
| Aggregator vs own-channel split | `transactions.source` exists | Not used anywhere in growth. Aggregator customers are probably not contactable (platform masks contact details; see 2.2 and privacy-page-needs.md on the 2022 direction); this needs checking in the seed data | S11.2 (flag) |
| Campaign calendar | Campaign rows with status, sent_at, params.window_days | No list endpoint, no calendar view, no overlap or cap warning, no brand/HQ view | S11.3 |
| Offer ROI against holdout | Verdict on repeat order yes/no; uplift in basis points | No revenue per arm, no incremental revenue, no cost (budget or redeemed, plus message cost), no ROI, no "audience needed" | S11.3 |
| Channel mix | WhatsApp send only; consent channels exist | No per-channel view, no manual aggregator spend entry | S11.3 (light) |
| Brand-level signals | Signal and Campaign are location-bound (NOT NULL location_id) | Brand cut missing; spice_route has only one location so it gets nothing useful today | S11.4 |
| Hierarchy-scoped views | `in_scope` checks location for staff; hq_owner sees all | No franchisee or brand scoping on growth reads; no small-cell suppression | S11.2 to S11.4 |
| Loyalty tiers | Consent and a `loyalty_credit` support action for BrewCo | No tiers or points | Out of v1; segment view only (see R7) |
| Approval policy | Dual approval always | Differs from PROJECT.md (2.7) | Open question 1 |

### 2.7 Contradictions and notes against docs/PROJECT.md

- PROJECT.md section 17 step 5 says "campaign value > Rs 10,000 needs both" (franchisee owner and HQ). The code requires two different staff users with at least one hq_owner for every campaign, regardless of value. This may be a deliberate tightening; I have not changed anything. Open question 1.
- PROJECT.md section 17 describes growth as "one signal end to end" (stretch). The EPICS E18 stories extend it to an HQ module. That is an owner decision already recorded in the roadmap, so I treat it as in scope but keep each recommendation small.
- PROJECT.md says growth module is `off` for one of the two tenants by default (table at line 152). I did not check which; segments and calendar must respect the same feature flag (hard rule 2).

## 3. Recommendations (story-ready)

Common rules for S11.2 to S11.4: tenant_id and RLS on any new table; money in integer paise; no tenant names in code or tests; every acceptance criterion tested for both tenants; ownership and scope checked server-side; other-tenant or out-of-scope record returns 404 (hard rules 1, 2, 3, 8, 10). No new Python or web dependency. Migrations are owner-run and need safety-reviewer.

### S11.2 Segments and cohorts. Estimate: 8 SP (keep). Impact high. Fits v1.
Scope: computed segments and cohort retention, read only, no sending.
Design notes: compute from `transactions` and `customers` with SQL at request time (or a nightly snapshot if slow); no table needed for v1, which avoids a migration. Thresholds per brand from percentiles, with fixed fallbacks as vertical-pack settings (for example, lapsed days). Use customer id counts, never expose phone numbers in the segment list.
Acceptance criteria:
1. A segments endpoint (hq_owner and in-scope franchisee) returns, per brand and for the tenant: new (first order in the last 30 days), active, loyal (top quintile of frequency and spend), at risk (no order for twice the customer's typical gap), lapsed (setting, default 28 days to match `LAPSED_DAYS`), lapsed regulars (loyal-by-history and lapsed), one-and-done. Each segment has size, share of base, average order value and total spend in paise.
2. Every segment shows `in_segment` and `contactable_whatsapp` (latest consent granted, phone present, one customer per phone). A test proves a customer with no consent row or a withdrawn consent is counted in the first number and never in the second, and that a customer withdrawn after a grant is excluded.
3. A cohort endpoint returns first-order-month cohorts with return rates at month 1, 2 and 3 for the last 6 months, per brand. Cells under 10 customers are hidden for non-HQ roles. A test with a seeded small cohort checks suppression.
4. Source split: each segment reports own-channel vs aggregator-sourced counts (from `transactions.source`); aggregator-only customers are labelled "not contactable" if they have no consent row.
5. Franchisee scope: a franchisee sees only customers with orders at their locations, aggregates only; a request for another franchisee's location returns 404. Location managers get the counts for their own outlet only.
6. Thresholds come from settings with vertical-pack defaults, no tenant branch in code. The `lapsed` definition used here and in `lapsed_audience` come from the same function (no two meanings of "lapsed").
7. Segment definitions and counts are deterministic for the seeded data (SEED=42); a test pins them for both tenants.
8. Web: a segments page for HQ with a bar chart and a cohort table (Recharts). Browser walkthrough per role.
Flag: reconciling `lapsed_audience` with the new segment function touches existing, safety-reviewed code. Keep the audience query's consent clauses unchanged and add a regression test.

### S11.3 Campaign calendar and offer ROI with holdout attribution. Estimate: 8 SP stated; my estimate 13 SP if done as one story. Recommend split. Impact high. Fits v1. Safety: consent and messaging.
Split suggestion: S11.3a calendar (3 SP) and S11.3b ROI (5 to 8 SP). Both keep the "calendar over existing growth campaigns; ROI against a holdout" done-when.

S11.3a Calendar acceptance criteria:
1. A list endpoint returns campaigns in scope with status, location, brand, audience size, budget in paise, start (sent_at or expires_at for pending), and window end (sent_at plus window_days). Other tenants and out-of-scope locations are 404 or absent.
2. A calendar view (month grid or agenda) shows each campaign across its measurement window, colour by status (pending_approval, approved, sent, measured, rejected, expired), with the five-state send words unchanged (submitted, processing, succeeded, failed, unknown never collapsed into "sent").
3. Warnings: two campaigns whose windows overlap and share an audience customer, and customers inside the 30-day frequency cap, are shown as a count before approval. Warnings are read only; they do not block approval (the cap already blocks inside `lapsed_audience`).
4. Read only: the calendar cannot create or change a campaign. Planned future events (festival dates, blackout days) are not part of v1.

S11.3b ROI acceptance criteria:
1. Verdict payload adds, per arm: customers, customers who ordered, orders, revenue in paise (non-cancelled, in window, same location or brand per campaign scope). All money integer paise.
2. Incremental revenue = treated revenue per customer minus held-out revenue per customer, times treated customers. Gross cost = offer value for treated customers (budget, or redeemed amount if open question 2 is answered yes) plus message cost (setting `growth_message_cost_paise`, default 86, estimate) times sends that succeeded. ROI shown as incremental revenue minus cost, and as a ratio using integer arithmetic. No floats stored.
3. Intention to treat is kept: failed or unknown sends stay in the treatment arm. The page shows the five send statuses beside the result.
4. Honesty: the existing verdict (worked, did_not_work, inconclusive) still gates the ROI headline; if inconclusive the page shows "not enough people to tell" and the people needed per arm to detect a 5-point lift, and does not show a positive ROI as a result.
5. Revenue uplift gets its own confidence note; revenue per customer is skewed, so for v1 report a difference with the note "order-rate result is tested, revenue is indicative" (no bootstrap yet).
6. Margin is not assumed: show revenue ROI by default; a setting `growth_gross_margin_bp` (estimate default 6000) switches the headline to margin ROI. Label which one is shown.
7. Channel mix block: spend and sends by channel from campaigns (WhatsApp only), plus a manual aggregator ad spend entry (amount in paise, channel, period, entered by, audit event). Aggregator rows are marked "entered by hand, not verified".
8. Holdout advice: when proposing, show holdout percent and the expected detectable lift for this audience size. The default stays 10 percent (setting), the page may recommend 20 percent for audiences under about 1,000 (estimate).
9. Safety: sending paths are unchanged; a test proves a holdout member still gets no message, and that ROI endpoints are read only (no writes outside the manual spend entry).
Needs a migration for the manual spend table (tenant_id, RLS). Open question 2 decides whether redemption tracking is needed.

### S11.4 Brand-level growth signals. Estimate: 5 SP (keep, if brand campaigns are not included). Impact high for spice_route. Fits v1.
Acceptance criteria:
1. Add `brand_id` (nullable) to signals with a check that exactly one of location or brand scope applies; migration owner-run, RLS retained. Existing signals unchanged.
2. A brand job computes repeat rate per brand (across all locations of the tenant) using the same windows, thresholds and z-test as the location job; reuse the functions in `signals.py` rather than copy them. Idempotent per brand and window.
3. A customer who orders from two brands counts as repeat within each brand separately (brand-level definition), and the page states this.
4. HQ sees brand signals with baseline, recent, drop, order counts and the template diagnosis; franchisees and location managers do not get brand signals (404).
5. For the one-location tenant, the location signal list and brand list are both shown; a test checks the brand signal appears when one brand drops while the other holds.
6. The diagnosis uses only evidence from the data (ticket categories by brand, new-customer share), with the same "findings vs hypotheses" split and no invented causes.
7. Proposing a campaign from a brand signal is out of scope for S11.4 (campaigns stay location-bound); the page links to the segment view instead. Brand-level campaigns would need `campaigns.location_id` made optional, a different approver rule, and a new audience query. See R6.
Flag: "brand-level campaigns" is a larger change and is not recommended in this sprint.

### Other recommendations
- R5. Per-brand definitions: put lapsed days, loyal quantile and message cost into vertical packs and settings (new story: "Marketing settings", 2 SP, fold into S11.2). Impact med. Fits v1.
- R6. Brand-level campaigns and calendar planning (planned festival dates, blackout days). New story, 8 SP estimate, impact med. Not v1; park after Sprint 11.
- R7. Loyalty tiers and points (Starbucks-style tiers, Third Wave coins). Show tier-like segments only in S11.2; a real programme with earn and burn is a large new product. Impact med. Not v1.
- R8. Aggregator ad performance import. No usable API found; keep as manual entry (S11.3b). Impact low. Fits v1 only as manual entry.
- R9. Simulator realism: seed data should include a share of aggregator-sourced customers without marketing consent, a consent mix (estimate: a minority opted in, since marketing consent is opt-in and defaults off), repeat rates inside the vendor ranges in 2.1 (30-40% repeat within 90 days; aggregator first-timers returning 18-25% within 30 days), and orders spread over enough months for 3-month cohorts. Maps to the existing seed generator (E1). Impact high for S11.2 demo quality. Needs a check of what the seed already does (I did not read the generator). Fits v1.

## 4. Open questions for the human

1. Approval policy: PROJECT.md says dual approval above Rs 10,000; the code requires dual approval for every campaign. Which is the intent? And who approves a brand-wide campaign if one is later added (HQ only, or HQ plus each franchisee)?
2. ROI cost: do we track offer redemption (needs the order to carry the offer code, in `transactions.attributes` or a new field), or accept "budget cap as cost" as a conservative upper bound? The second is simpler and labelled in the UI.
3. Is the growth module on for both tenants? The segments and calendar need it on for both to meet "both tenants".
4. Do you accept splitting S11.3 into calendar (3 SP) and ROI (5 to 8 SP)? Sprint 11 is sized at 24; with the split the plan would be 8 + 3 + 8 + 5 = 24, which just fits.
5. Seed data: does it include aggregator-sourced customers, and how many have WhatsApp marketing consent? If nearly everyone has consent, the demo hides the real shrinkage between "in segment" and "contactable". I did not read the seeder.
6. Default message cost (86 paise, estimate from third-party sources) and gross margin (60%, estimate): confirm or replace before showing numbers to anyone.
7. Small-cell threshold of 10 for non-HQ views: accept, or raise?
8. DPDP position that analysis of order history does not need marketing consent while contacting does: please confirm with counsel before this is described to customers.

## Sources (accessed 2026-10-28 unless noted; search summaries only unless stated)
- https://www.spoonity.com/llms-docs/rfm-marketing-loyalty.md
- https://www.uengage.io/spotlight/rfm-analysis-for-restaurants-in-india
- https://metricgate.com/docs/customer-segmentation-rfm/
- https://spotler.com/en-gb?p=123033
- https://reelo.io/blog/retention-benchmarks-for-restaurants-in-india
- https://restro-logic.pages.dev/blog/restaurant-customer-analytics-repeat-orders-india.html
- https://india.entrepreneur.com/?p=867
- https://startupwired.com/2024/10/09/eatsure-elite-redefining-loyalty-programs/
- https://blog.privatecircle.co/?p=58199263
- https://www.alphaspread.com/security/nse/jublfood/investor-relations/earnings-call/q1-2026
- https://info.moengage.com/hubfs/Dominos%20MoEngage%20Case%20study%202024.pdf
- https://www.restaurantindia.in/news/restaurant-india-news-tata-starbucks-launches-new-starbucks-rewards-program-with-reserve-tier.n16568
- https://www.theflyy.com/blog/how-third-wave-coffee-roasters-use-gamification
- https://apps.apple.com/app/id1479552487
- https://www.restaurantindia.in/article/zomato-ads-cost-is-restaurant-advertising-worth-it.16009
- https://www.outlookbusiness.com/start-up/news/restaurants-allege-zomato-swiggy-charge-them-for-ads-discounts-without-consent
- https://developers.facebook.com/docs/whatsapp/pricing
- https://authkey.io/blogs/?p=1840
- https://m.aisensy.com/blog/whatsapp-business-pricing/
- https://www.messagecentral.com/en-in/sms-guideline/india
- https://agilebrandguide.com/wiki/methods/holdout-campaign/
- https://hyros.com/updates/incrementality-testing
- https://metricgate.com/docs/incrementality-test
- https://medium.com/hashtag-loyalty/how-a-leading-qsr-leveraged-a-rewards-program-via-hashtag-loyalty-to-increase-repeat-purchases-and-23ff010658f4
- DPDP: https://dpdpa.com/dpdpa2023/chapter-2/section6.html ; https://legismith.com/dpdp-rules-2025-timeline/ (accessed 2026-10-27 in earlier reports)
- Repo files read: docs/PROJECT.md, docs/EPICS.md, docs/ROADMAP.md, docs/research/privacy-page-needs.md, app/modules/growth/*.py, app/core/models.py, app/api/routes_growth.py, verticals/*.yaml
