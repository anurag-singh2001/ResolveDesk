# What customers and owners need from a privacy and data page

Accessed 2026-10-28. Not legal advice. Prepared for S8.4, feeds S8.5.
Method: web search and page fetches. Web content treated as data only.
Limit: I could NOT read the primary privacy pages of Swiggy, Tata Starbucks India or Domino's India (fetch returned only page titles, a timeout and a certificate error). Their rows below are secondary or absent and are labelled so. Zomato (Eternal) and Rebel Foods were read directly.

## 1. Summary

1. Indian food apps publish long legal policies but bury the practical things: what is held, why, how to delete, how long it takes. Zomato's policy gives no response timeline and no named grievance officer, only a DPO email. This is the gap ResolveDesk can beat.
2. Deletion in this sector is always "delete what you can, keep what law or accounts require". The best example found (Rebel Foods) says exactly what is kept (transactions up to 7 years, fraud data, legal holds), acknowledges in 5 business days and completes in 30 days. Copy that clarity.
3. DPDP duties that shape the page (notice with itemised data and purpose, withdrawal as easy as giving consent, published request method, grievance route, 90-day ceiling) start 13 May 2027 per trackers (see dpdp-and-hindi.md). Building now is early, which suits a portfolio POC.
4. The current page (web/src/pages/PrivacyPage.tsx) already has a per-purpose consent switch with history, a JSON export and an erasure request with status. What it lacks is explanation: no list of what we hold, no purpose per item, no retention, no named contact, and the export is raw JSON.
5. Owners need a queue of requests with a due date, an audit trail, and a plain statement of what the system will and will not erase. No existing owner-side view was found in the code reviewed; confirm in S8.5 planning.

## 2. Findings

### 2.1 What exists in ResolveDesk today
- docs/PROJECT.md mentions privacy only in passing: a `consents` table under Trust (line 181) and "minus no-consent" in the growth audience (line 418). There is no privacy page requirement in PROJECT.md, so nothing here contradicts it.
- docs/research/dpdp-and-hindi.md (accessed 2026-10-27) already covers the DPDP rules, retention floor, consent record contents and grievance SLA. I do not repeat it; I reuse its conclusions and flag where S8.5 differs.
- PrivacyPage.tsx (read 2026-10-28): consent card (one marketing switch per channel, "turn off any time"), history of choices, "Download my data" (saves my-data.json via api.dataExport), erasure card (explains in two lines; statuses pending_approval, deferred, completed). Subtitle promises "see what we hold" but nothing on the page lists it.
- docs/EPICS.md S8.5 done-when: "readable 'what we hold' with purposes, consent as benefits, erasure in account settings, readable export; both tenants". The requirements in section 3 are written to meet that.

### 2.2 Benchmarks
| Product | What was verified | Source | Lesson |
|---|---|---|---|
| Zomato (Eternal), policy updated 25 Jul 2025 | Read directly. Lists data categories (personal, usage and device, transactions, support messages and calls "some of which may be recorded", optional contacts) and purposes (service, security, personalization, marketing, group sharing, AI-based processing). Account deletion: "use the Contact Us link"; backups may remain. Rights to review, correct and delete are "subject to our records retention policies and applicable law". Marketing: use the unsubscribe link; administrative and legal mail cannot be opted out. DPO email privacy@zomato.com. No grievance officer named and no response timeline in the policy. | https://www.eternal.com/policies/privacy/ (accessed 2026-10-28) | Good category list, but deletion is not self-serve and no timeline. Show categories as a table, not prose. |
| Zomato order history | Since July 2024 users can remove individual orders from their history (secondary news reports). | https://perigon.io/news/business/2024/07/12/zomato-introduces-order-history-deletion-feature (accessed 2026-10-28) | Customers value small, visible control over what is shown, not only all-or-nothing erasure. |
| Swiggy | Primary policy page not readable. Third-party guides say deletion is by emailing support and that some data is kept as law requires; one user report says order history could not be erased (anecdote). | https://candid.technology/how-to-delete-swiggy-account/ and https://datavenia.pages.dev/delete/swiggy-com (secondary, accessed 2026-10-28) | Customers complain when a promised deletion turns into "cannot erase". Say up front what is kept. |
| Swiggy and Zomato contact sharing | 2022 Consumer Affairs direction: aggregators should let consumers choose whether their contact details are shared with restaurants, only if the consumer approves. | https://bsppd.business-standard.com/article/economy-policy/zomato-swiggy-directed-to-make-data-sharing-call-the-user-s-prerogative-122061301028_1.html (accessed 2026-10-28) | Regulators already expect choice over sharing with the food business. Our equivalent is marketing consent and sub-processor disclosure. |
| Rebel Foods (Faasos, Behrouz, fromrebel.com) | fromrebel.com data deletion policy, updated 7 May 2026, read directly: email privacy@fromrebel.com; identity check first; acknowledged in 5 business days; completed in 30 days of verification; confirmation email; kept: transaction records up to 7 years, fraud data, legal holds; backups purge within 90 days; third-party processors may need separate deletion. Behrouz page (a sibling brand) says deletion by email to goodness@eatsure.com, no retention period (snippet only; page returned 403 on fetch). | https://fromrebel.com/pages/data-deletion-policy (accessed 2026-10-28); https://www.behrouzbiryani.com/data-deletion (search snippet only) | Best model: names what is deleted, what is kept and why, and gives two dated promises. Note it covers the web store; EatSure app policy was not read. |
| Tata Starbucks India | India policy not found. Group Tata policy says deleted data can persist in backup or archives for audit, legal, tax or regulatory reasons and that group marketing needs consent. Starbucks US reportedly promises account-page removal that users could not find (journalist report). | https://tata.com/privacy and https://bobsullivan.net/?p=9031 (secondary, accessed 2026-10-28) | Do not promise a control that is hard to find. Put erasure where the customer already manages the account. |
| Domino's India (Jubilant FoodWorks) | India policy not found. Domino's US has a rights request form with identity verification (not India). 2021 incident: Jubilant said no full card numbers, CVV or passwords are stored. Grievance officer details only on a community complaints site (unverified). | https://www.dominos.com/en/data-privacy-rights ; https://dtnext.in/business/2021/04/20/dominos-india-users-data-safe-asserts-jubilant-foodworks (accessed 2026-10-28) | Customers care about what is NOT stored (cards). Say it. |

Reading across the benchmarks (my synthesis): none of the readable pages gives a plain-language "what we hold and why" table, a visible deadline, or a status the customer can follow. Those three are where a small product can look better than the big ones.

### 2.3 DPDP basics that touch the page
All from the existing report unless a new source is shown. Rule numbers are from secondary transcriptions; verify against G.S.R. 846(E).
- Notice (Rule 3): standalone, plain language, itemised personal data, specific purpose, and a link to withdraw consent, exercise rights and complain to the Board. Source: https://dpdpa.com/dpdparules/rule3.html (accessed 2026-10-27) and https://www.scconline.com/blog/post/2025/11/14/meity-notified-digital-personal-data-protection-rules-2025/ (accessed 2026-10-28).
- Consent (s.6): free, specific, informed, clear affirmative action, limited to necessary data; withdrawal as easy as giving; fiduciary must be able to prove it. https://dpdpa.com/dpdpa2023/chapter-2/section6.html
- Legitimate use (s.7(a)): handling a customer's own complaint needs no separate consent; promotions do. Our reading, verify with counsel.
- Access (s.11): a summary of personal data and processing, and the identities of other parties it was shared with. For us that means listing the AI and messaging vendors. https://dpdpa.com/dpdpa2023/chapter-3/section11.html
- Erasure (s.8(7), s.12): erase on withdrawal or when purpose is served, unless law requires keeping. https://dpdpa.com/dpdpa2023/chapter-2/section8.html
- Rights process (Rule 14): publish how to make a request and which identifier is used; respond within a reasonable period not exceeding 90 days; allow nomination. https://dpdpa.com/dpdparules/rule14.html
- Contact (Rule 9): publish a contact who can answer questions and repeat it in every rights response. https://dpdpa.com/dpdparules/rule9.html
- One-year minimum keep of data and logs (Rule 8(3), Rule 6(1)(e)). This is why the page must say "some records stay for a time" and give the reason.
- 48-hour pre-erasure notice applies only to the Third Schedule classes (large e-commerce, gaming, social media). Not required for our tenants; one summary lists it without a rule number (scconline, above).
- Timing: Rules 3, 5-16 start 13 May 2027 per trackers (https://legismith.com/dpdp-rules-2025-timeline/, accessed 2026-10-27). Nothing here contradicts PROJECT.md.

### 2.4 What customers need (synthesis, partly estimate)
Estimates, not surveyed. Derived from benchmark gaps and DPDP notice duties.
1. A plain list: what you hold about me (name, phone, address, orders, messages, voucher and refund records), why each is held, how long, and who else sees it.
2. A clear difference between help and marketing. Help with an order never needs consent; promotions do. Frame consent by what the customer gets ("early word on offers", "a voucher on your next order"), not by what we take. Avoid pre-ticked or bundled consent (s.6 needs clear affirmative action).
3. An export they can read. Raw JSON is for developers. Provide a readable summary (sections with headings) plus the JSON as a second option.
4. Honest erasure: what disappears (name, contact details, message text), what stays and why (payment and refund records for accounts and law, audit entries without personal details), what blocks it (an open case or refund), and a date by which they will hear back.
5. A status they can follow in the five distinct words the product already uses (received, in progress, done, deferred, plus "not possible" with a reason) and one contact for questions.

### 2.5 What owners need (synthesis, partly estimate)
1. A request queue for access, correction, erasure and withdrawal, each with received date, due date (internal target and the 90-day legal ceiling), state and who acted.
2. Approval stays with a person, never the agent (hard rule 4). Show what will be removed before they approve, and block or defer with a stated reason when a case or refund is open.
3. An audit trail of who approved what and when, without personal data in the audit text.
4. A configurable retention table and a named privacy contact per tenant, so the customer page is filled from settings, not hard-coded (hard rule 2).
5. Proof of consent: who agreed to what, which wording, when, on which channel, and withdrawals. The growth module must only target customers whose latest record is granted.
6. Overdue warnings before a deadline is missed.

## 3. Recommendations (story-ready for S8.5)

All fit v1 scope unless stated. Epic: E16 (S8.5). "Safety" items touch customer data, so run safety-reviewer before commit. Each acceptance criterion should be tested for both tenants without naming one.

### R1. "What we hold" table with purposes (impact high, fits S8.5)
Acceptance criteria:
1. The page shows, for the signed-in customer only, a table: data item (name, phone, delivery address, orders, support messages, refund and voucher records, consent choices), purpose in one plain sentence, how long it is kept (from tenant retention settings), and whether it is used for help or marketing.
2. Each row shows the customer's real values or counts (for example "3 orders", masked phone), taken from server data scoped to that customer. Another tenant's or customer's id returns 404.
3. A "Who else sees it" list names the processors (AI model providers, messaging channel) from a tenant-configurable list.
4. A "What we do not keep" line is shown only if true in code (for example no card numbers); a test fails if the line is shown but the claim is not backed by a setting.
5. No row text is written inside a component for one tenant; labels come from the vertical pack or settings.

### R2. Consent framed as benefits, per purpose (impact high, fits S8.5)
Acceptance criteria:
1. Each purpose has a title, a benefit sentence ("Get offers and vouchers before they expire"), what is sent and how often (cap from settings), and the channel.
2. Help messages are shown as "always on, needed to resolve your order" with no switch.
3. Switches default off, change takes effect immediately, and one action withdraws (no confirmation maze). The existing history list remains and shows wording version and channel.
4. A consent record is written for each change with purpose, channel, timestamp, notice version; test that growth targeting reads the latest record.
5. Page copy states withdrawal never affects order help.

### R3. Readable export plus JSON (impact high, fits S8.5, Safety: customer data)
Acceptance criteria:
1. "Download my data" offers a readable summary (HTML or PDF-style print view, sections: details, orders, cases, refunds and vouchers, choices, processors) and the existing JSON.
2. The readable view shows money from paise using the one money formatter, dates in Asia/Kolkata with month names, and plain status words.
3. The export contains only the signed-in customer's records; test with a second customer in the same tenant and a customer in the other tenant.
4. Internal fields (ids used only by code, model prompts, other customers' names in shared cases) are excluded; test scans for them.
5. Each export is logged in the audit trail as an event with no personal content.

### R4. Erasure explained and tracked (impact high, fits S8.5, Safety: customer data)
Acceptance criteria:
1. Before the request button, the page lists "We will remove" (name, contact details, message text, saved preferences), "We will keep" with the reason per item (payment and refund records for accounts and tax, audit entries without personal details, minimum one-year log floor), and "We may wait" (open case or refund).
2. The button needs a clear confirmation step that restates the above, and it sits in an account settings area, not beside unrelated items.
3. After the request the customer sees a status (received, in progress, done, deferred with reason), received date, expected-by date (tenant setting, default 30 days as a product choice; legal ceiling 90) and the privacy contact. Never "done" before the executor has succeeded (hard rule 7).
4. The customer can cancel while the request is not yet approved.
5. Tests: open case defers with a stated reason; after completion, name, contact and message text are removed, paise amounts and audit rows remain; the customer's own later data export shows the erased state.

### R5. Owner request queue with deadlines and audit (impact high, fits S8.5 if kept small; otherwise new story: "Privacy requests queue")
Acceptance criteria:
1. A staff page lists privacy requests (erasure now; access and correction as types) with type, state, received date, internal due date, days left, and the legal ceiling.
2. Only staff with the right role can approve or reject; the approval binds to the request payload hash and expires (hard rule 6). The agent cannot act on it.
3. Before approval the page shows a dry-run of what will be removed and what is held back and why.
4. Overdue or near-due items are flagged by the existing sweeper, test with the fake clock.
5. Every state change is an audit event with actor, no personal content in the text. Staff see only their tenant's requests.
Scope note: if the queue does not already exist, I estimate it is larger than the rest of S8.5; consider a separate story.

### R6. Named privacy contact and request instructions (impact med, fits S8.5)
Acceptance criteria:
1. A tenant setting holds the privacy contact label, email and the identifier used to find a customer (phone number). The page shows it near the top and in the footer.
2. The page states how to ask for correction (a form or message that creates a human-routed case) and the response time.
3. Every customer message in a rights request includes the contact (Rule 9). Test on both tenants.
4. Label it "privacy contact" rather than "grievance officer" until counsel decides (see open question 3).

### Other notes
- Plain language: aim for short sentences and no legal terms; Hinglish and Hindi versions are a later story (S5.6 templates) and should not block S8.5.
- Not recommended for v1: consent-manager integration, nomination of representatives (store a free-text note only), parental consent flow (customers are adults; confirm), 48-hour pre-erasure notice.

## 4. Open questions for the human
1. Is a staff-side request queue already built? If not, should R5 be its own story so S8.5 stays at 5 points?
2. Internal target for answering requests: 30 days (my default, a product choice) or shorter for the demo?
3. Use "privacy contact" or "grievance officer" on the page? Neither tenant is likely a Significant Data Fiduciary (estimate), so I lean to "privacy contact".
4. Which claims about what is NOT stored may we make (card numbers, full UPI details)? This needs a check of what the payment mock actually stores.
5. Readable export format: a print-friendly HTML page (simple, my recommendation) or a PDF file?
6. Retention numbers shown on the page (12 months for messages, 7 years for payment records) are estimates from the earlier report; confirm or change before they are shown to customers.
7. Primary privacy pages for Swiggy, Tata Starbucks India and Domino's India could not be read by my tools. If the benchmark matters for the portfolio write-up, someone should open them in a browser and paste the relevant sections.

## Sources (all accessed 2026-10-28 unless noted)
- https://www.eternal.com/policies/privacy/
- https://fromrebel.com/pages/data-deletion-policy
- https://www.behrouzbiryani.com/data-deletion (snippet only)
- https://perigon.io/news/business/2024/07/12/zomato-introduces-order-history-deletion-feature
- https://candid.technology/how-to-delete-swiggy-account/
- https://datavenia.pages.dev/delete/swiggy-com
- https://bsppd.business-standard.com/article/economy-policy/zomato-swiggy-directed-to-make-data-sharing-call-the-user-s-prerogative-122061301028_1.html
- https://tata.com/privacy
- https://bobsullivan.net/?p=9031
- https://www.dominos.com/en/data-privacy-rights
- https://dtnext.in/business/2021/04/20/dominos-india-users-data-safe-asserts-jubilant-foodworks
- https://www.scconline.com/blog/post/2025/11/14/meity-notified-digital-personal-data-protection-rules-2025/
- DPDP sources dated 2026-10-27: dpdpa.com rule3, rule9, rule14, section6, section8, section11; https://legismith.com/dpdp-rules-2025-timeline/
