# Owner decisions: money and privacy (M1-M4, P1-P5)

Prepared 2026-10-31 (all "accessed" dates are 2026-10-31 unless stated). Not legal advice. Items marked COUNSEL need a lawyer before they are shown to customers as fact. Web content was treated as data only.

Reading limits, stated up front:
- I could NOT read the notified DPDP Rules (G.S.R. 846(E)) in the Gazette (egazette certificate error; MeitY and PIB PDFs returned 403 or undecodable text). Rule text below comes from the transcription site dpdpa.com plus law-firm summaries. The Gazette also carries a corrigendum, G.S.R. 892(E) of 10 Dec 2025, that fixes eight points; I could not read it, so wording or numbering may differ slightly.
- I could NOT read the refund policies of Swiggy, Zomato, Domino's India or Tata Starbucks India (pages returned only titles, redirects or timeouts). Platform behaviour below rests on consumer-forum reports, news and complaint sites, which are anecdotal.
- GST, Companies Act, Income Tax and Consumer Protection Act texts were read through secondary commentary, not the statutes.

## 1. One-page summary

| # | Question | Recommendation | Confidence |
|---|---|---|---|
| M1 | Refund next to voucher for wrong item | Show "ask for a refund, a team member decides" to every own-channel wrong-item customer, voucher stays the default. Amend the spice_route policy text to match, and fix its 50% cap versus "refund of the order" conflict | Med |
| M2 | Wording for closed, no remedy | Replace "No remedy is due" with a reasoned, non-legal sentence that names the review, the way to contest and the National Consumer Helpline 1915 (exact text in 2.2) | Med |
| M3 | Second person after a remedy switch | The switcher becomes the author of the new proposal and cannot approve it. Allow same-step approval only for a downgrade (smaller amount or refund to voucher). If no other approver exists: wait, then a logged owner override up to a small limit. Keep both current defaults | Med |
| M4 | Campaign approvers | Keep two approvers for every campaign; make the Rs 10,000 threshold a setting defaulting to 0; update PROJECT.md section 17 | Med-high |
| P1 | Retention figures | Message text 12 months after close: keep (provisional). Payment/refund ledger: change 7 years to 8 financial years. Add a retained case decision record (no free text) with the ledger | Med (figures), Low (7 vs 8 for non-company tenants) |
| P2 | 30-day target, 90-day ceiling | Keep 30 days, add a 48-hour acknowledgement, and correct the "90-day legal ceiling" label: it is Rule 14(3) for grievance responses, not in force until 13 May 2027 (as reported), and there is no erasure-specific deadline | Med-high |
| P3 | Label | "Privacy and grievance contact" (a named person). Do not use "Data Protection Officer" | Med |
| P4 | Completion message after erasure | Yes. Send once, after the executor succeeds, to a destination captured at request time, held in a short-lived outbox row and deleted after the send outcome is final. Content in 2.8 | Med |
| P5 | "What we do not keep" | Claim only: card number, CVV/expiry and UPI PIN are never seen or stored by us. Do not claim "no UPI details" or "no card details" unless a scan test proves it. Conditions in 2.9 | Med-high |

Contradictions with current defaults or PROJECT.md (stated plainly):
1. "90-day legal ceiling" on the privacy page is imprecise and premature (P2).
2. PROJECT.md section 17 says campaigns above Rs 10,000 need both approvers; code requires two for all. I recommend the code behaviour and a spec edit (M4). Note that the default campaign budget cap is itself Rs 10,000, so the spec threshold (strictly "above") would never trigger at defaults.
3. spice_route `wrong_item_v1` 1.2 says a manager decides "a refund of the order" for a wrong order, but `refunds_v2` 1.2 caps any single refund at 50% of the order, and the S7.9 refund option is `refund_percent: 50`. The policy promises more than the option can deliver (M1).
4. "7 years" for payment records is likely 8 financial years for tenants that are companies (P1).

## 2. Details

### 2.1 M1 Refund as a choice for wrong-item customers

Recommendation: Option A. Show the refund to every wrong-item customer on an own-channel order as a request ("you can ask for a partial refund of up to X; a team member decides"), with the voucher as the default option. Do not hide it behind a declined voucher (Option C) and do not restrict it to whole-order errors (Option B).

Reasoning:
1. Consumer law expects a refund route for wrong or deficient supply. The Consumer Protection Act 2019 treats as an unfair trade practice refusing, after sale or service, to take back defective goods or withdraw deficient services and refund the consideration within the period on the bill, or 30 days if none is stated (s.2(47), clause reported as (viii) by commentary). A voucher-only path, or one that makes the customer refuse the voucher first, invites that argument. Source (secondary, clause number unverified): https://www.freepressjournal.in/amp/analysis/know-your-rights-return-of-goods-rules-provisions-a-consumer-should-be-aware-of and https://www.taxclue.in/blog/section-2-consumer-protection-act-2019-definitions-unfair-trade-practice-unfair-contract-e-commerce-and-others/ (accessed 2026-10-31).
2. The E-Commerce Rules 2020 require an e-commerce entity to pay accepted refunds within a reasonable period (RBI or other law applies; no day count). Nothing forces a refund for every claim; the duty is to pay what is accepted. Sources: https://www.taxclue.in/blog/rule-4-8-11-consumer-protection-e-commerce-rules-2020-cancellation-charges-consent-refunds-and-price-manipulation (secondary, sub-rule number unverified; one analysis mentions a 2026 amendment adding rules from 1 Jan 2027, which I could not verify) (accessed 2026-10-31).
3. Consumer forums treat wrong or short food as deficiency in service and reject "it was the restaurant's fault": Chandigarh Commission on Swiggy short delivery, which also rejected the "only an intermediary" plea (https://www.livelaw.in/amp/consumer-cases/chandigarh-consumer-commission-holds-swiggy-instamart-liable-for-short-delivery-orders-compensation-310692); a Chennai commission held the contract was with Zomato, not the restaurant (https://www.dtnext.in/amp/story/news/chennai/zomato-ordered-to-pay-chennai-man-15k-fine-for-missing-dosa-uttapam-set-799169). Both accessed 2026-10-31 via search results, not fully read.
4. Veg/non-veg mix-ups are the sharp case. A Dharwad consumer court fined Domino's Rs 50,000 for a non-veg pizza to a veg customer even though Domino's had offered a refund and a complimentary pizza (https://english.publictv.in/?p=1159159, accessed 2026-10-31, search snippet only). Lesson: a voucher alone is not safe for this category; a person should always see it.
5. What the big apps do is not verifiable from primary sources. Secondary reports say Swiggy offers a "Compensation" route in the app for wrong orders and refuses missing-item refunds inconsistently (https://www.newsbytesapp.com/news/science/steps-to-cancel-your-orders-on-swiggy/story; https://ianslive.in/swiggy-faces-backlash-after-vegetarian-order-delivered-as-non-veg--20251117120943), and that Zomato often points to the restaurant (search results, accessed 2026-10-31). Domino's and Starbucks India: no official policy found. Treat "refund-first for wrong items" as the customer expectation set by apps, not as a documented rule.
6. Fit with the tenants' policies, as written:
   - brewco `order_accuracy_v2` 1.1: "A refund comes second, only when a manager decides a remake or voucher doesn't fit." A customer's request is a legitimate prompt for that manager decision, and a refund option is always human-approved, so no policy is bypassed.
   - spice_route `wrong_item_v1`: 1.1 gives a voucher for a wrong dish; 1.2 lets a manager choose voucher or refund only when the whole order is wrong. Offering a refund request for a single wrong dish goes beyond the text. Either amend the policy (my recommendation: add "the customer may ask for a refund of the wrong item's value; a manager decides") or restrict the option to whole-order cases through pack data. This is an owner policy decision; I would not leave code and policy disagreeing.
7. Abuse risk (estimate, no Indian data found): more customers will tick the refund box. The controls already exist: a person decides, fair-use limit, 50% cap, refundable balance. Add a photo/evidence prompt for the refund request if not already there.

Also check (not verified in code): aggregator-placed orders (Swiggy/Zomato) must not show the refund option, because both tenants' policies say the delivery app refunds those orders.

What would change my mind: a primary Swiggy or Zomato policy showing voucher-first with refund only on decline (then C is market-normal); counsel advising that offering refund for all invites claims; evidence from the pilot that more than about half of requests are declined by managers, which would show the option raises expectations that policy then breaks.

Confidence: Medium. The legal direction is clear, but my sources are secondary and the platform benchmark is anecdotal.

### 2.2 M2 Wording when a case closes with no remedy

Current text (app/core/i18n.py `close.no_remedy`): "We reviewed this case and closed it. No remedy is due on this order."

Problems: "remedy" and "is due" are legal-sounding, it gives no reason and no next step, and the Hindi "muaavza" (compensation) wrongly suggests a damages claim. Hard rule 7 allows only verified facts, so the text must not say more than the system holds (for example it must not say "a different team member will review" unless a review route exists; today a closed case cannot be replied to).

Recommended English (generic reason):
"We have looked at your case again and, based on the records for this order, we are not able to offer a refund or voucher this time. If you think we have missed something, or you have a photo or receipt to share, contact us at {privacy_grievance_contact}: we reply within 2 working days and aim to settle within 30 days. You can also call the National Consumer Helpline on 1915 (consumerhelpline.gov.in)."

Where a reason code exists (for example the late-delivery pack's "delay caused by a wrong address"), prepend one fixed, code-owned reason sentence: "Our delivery record shows the delay came from the delivery address."

Recourse facts:
- National Consumer Helpline: 1915 toll free (8 AM to 8 PM), alternative 1800-11-4000, WhatsApp +91 8800001915; complaints via web portal, app, UMANG, WhatsApp or call; NCH forwards to the company. Source (official site): https://consumerhelpline.gov.in/ (accessed 2026-10-31).
- Grievance route: the E-Commerce Rules 2020 require an e-commerce entity to appoint a grievance officer, show name, contact and designation, acknowledge within 48 hours and redress within one month (secondary: https://www.indialaw.in/blog/civil/consumer-protection-e-commerce-rules/, accessed 2026-10-31; primary text not read). Whether each tenant is an "e-commerce entity" (own web or app ordering) is a COUNSEL point; if yes, the contact block is mandatory, not optional.
- Consumer Commission: complaint within two years of the cause of action (CPA s.69; secondary: https://www.taxclue.in/blog/section-69-consumer-protection-act-2019-limitation-period-for-complaints/). No need to say this in the message.

Do not write "this decision is final", "no further action possible" or quote the 2-year limit.

Hindi notes (needs native review, as already flagged in DECISIONS):
- Avoid "muaavza"/"मुआवज़ा"; say refund and voucher as loan words (रिफंड, वाउचर), which customers use, or "पैसे वापसी".
- Hinglish draft: "Humne aapka case dobara dekha. Is order ke records ke hisaab se hum is baar refund ya voucher nahi de paa rahe hain. Agar aapko lagta hai ki kuch chhoot gaya hai, ya aapke paas photo ya rasid hai, to {contact} par likhiye: hum 2 kaam ke dinon mein jawab denge aur 30 din mein nipatane ki koshish karenge. Aap National Consumer Helpline 1915 par bhi sampark kar sakte hain."
- Devanagari draft: "हमने आपका केस दोबारा देखा। इस ऑर्डर के रिकॉर्ड के आधार पर हम इस बार रिफंड या वाउचर नहीं दे पा रहे हैं। अगर आपको लगता है कि कुछ छूट गया है, या आपके पास फ़ोटो या रसीद है, तो {contact} पर लिखें: हम 2 कार्य-दिवस में जवाब देंगे और 30 दिन में निपटाने का प्रयास करेंगे। आप राष्ट्रीय उपभोक्ता हेल्पलाइन 1915 पर भी संपर्क कर सकते हैं।"
- Keep digits ASCII, as the existing Hindi decision does.

What would change my mind: counsel says naming NCH is unwise for the tenants (they may prefer to omit it; the grievance contact alone is the legal minimum if they are e-commerce entities); the owner does not want to promise 2 working days.

Confidence: Medium (wording is judgement; the recourse facts are solid). Implementation gap to flag: the sentence promises a contact route, so S8.5 contact settings must be filled or the sentence must drop that clause (as the privacy page already does with "Not set yet").

### 2.3 M3 Second-person rule on a remedy switch

Recommended rule:
1. The user who switches a proposal is the author of the new proposal (set `proposed_by` to the switcher). The existing four-eyes rule then applies: the author cannot approve it.
2. Same-step approval is allowed only for a downgrade: the new amount is not higher and the new action is not more cash-like (refund to voucher, or a smaller amount of the same action). Upgrades (voucher to refund, or any higher amount) need a different eligible person. Reason: the risk is money out, and a downgrade cannot cost the business more than the proposal the switcher was already entitled to decide.
3. No second approver exists (single HQ owner, thin outlet): the upgrade waits as "awaiting a second person" and the case owner moves to HQ. The only exception is an owner override, allowed when the actor is hq_owner, the amount is at or below a small setting (suggest Rs 500, equal to the existing manager limit; estimate), a written reason is stored, and the audit event is flagged `self_approved` and shown in a weekly list. Above the limit it stays pending until another person exists; it does not silently succeed.
4. Never auto-approve a switched proposal (already the S7.10 decision; keep it).

Evidence: separation of duties is a standard control: NIST SP 800-53 AC-5 says to identify duties needing separation and enforce them with access authorisations (https://www.stigviewer.com/controls/nist-800-53/AC-5 and https://www.upguard.com/compliance/nist-sp-800-53/ac/ac-5, accessed 2026-10-31; I read summaries, not the NIST PDF). The ACFE reports that missing controls and overrides of existing controls are the leading weaknesses in occupational fraud cases (about 32% and 19% in the 2024 edition, per a secondary summary at https://www.ivey.uwo.ca/media/kjljj5cy/2024-report-to-the-nations.pdf, accessed 2026-10-31, search snippet only). That supports logging overrides rather than banning them. I found no source on small-business thresholds; the Rs 500 figure is an estimate that mirrors the tenants' own manager limit in `refunds_v1` 1.1.

Confirm or challenge current defaults:
- Proposer cannot approve their own staff proposal: CONFIRM. Self-withdrawal (reject own) allowed: CONFIRM.
- Staff proposals never auto-approved: CONFIRM for refunds (already always team). For vouchers under the auto cap it is stricter than the AI path, which would auto-approve the same voucher without any person. That asymmetry is acceptable in v1 (a person-made proposal usually follows an escalation) but could become a tenant setting later. No change now.
- Open S7.10 gap in DECISIONS: switch does not apply four-eyes today. My rule closes it.

What would change my mind: a pilot with a one-person back office where the override list fills with routine items (then raise the limit or add a delayed-release rule: self-approved after 24 hours unless an alert is cleared).

Confidence: Medium. Logic is standard; thresholds are estimates.

### 2.4 M4 Campaign approvers

Recommendation: keep two approvers for every campaign (code behaviour), expose the PROJECT.md figure as a setting (`campaign_dual_approval_min_paise`, default 0), and edit PROJECT.md section 17 step 5 to say so.

Reasoning:
1. The campaign budget cap defaults to Rs 10,000 (hq-marketing-needs.md section 2.4). Spec wording "value > Rs 10,000 needs both" means no default campaign needs two approvers, so the spec as written lets one person launch a customer-facing send at defaults. That is probably not the intent.
2. A campaign's risk is not only rupees: it sends marketing messages to real customers under consent (DPDP s.6, the consent record must be provable) and carries brand risk. Cost scales with audience, but the exposure of a wrong audience or a wrong offer does not.
3. Campaigns are rare (one per signal, 48-hour proposal and 24-hour approval windows), so the friction cost of two approvers is low.
4. BrewCo has franchisee owners plus HQ, so two distinct people exist by design. spice_route has one location and the growth module is not meaningful there; no single-owner deadlock arises in v1.

What would change my mind: campaigns become frequent (for example weekly per outlet), or a franchisee reports delays; then set the threshold to 10,000 per spec.

Confidence: Medium-high. This is a policy choice more than a fact.

### 2.5 P1 Retention figures

Status of the law first (latest I could find, accessed 2026-10-31):
- DPDP Act 2023 and the DPDP Rules 2025 (G.S.R. 846(E), 13 Nov 2025, per trackers). Rules 1, 2 and 17-21 in force; Rule 4 from 13 Nov 2026; Rules 3, 5-16, 22, 23 (the duties on fiduciaries: notice, erasure, rights, contact, grievance) from 13 May 2027 (https://ssrana.in/articles/meity-notifies-final-digital-personal-data-protection-rules-2025/). MeitY proposed in January 2026 to shorten the 18 months to 12 and to make Rule 8(3) operational within three months; the latest article I found (April 2026) still calls this a plan and I found nothing confirming it was notified (https://ssrana.in/articles/meity-plans-to-cut-short-dpdp-compliance-timeline-and-notify-cross-border-restrictions-for-sdfs/). Status in October 2026 is UNVERIFIED: check the Gazette. Until then, the privacy page is voluntary good practice, not yet law.
- Rule 8(3) (dpdpa.com, https://dpdpa.com/dpdparules/rule8.html, read 2026-10-31): a fiduciary must retain personal data, traffic data and processing logs for a minimum of one year from the date of processing "for the purposes as specified in the Seventh Schedule", then erase unless another law requires longer. The rule's own example says an e-commerce platform must keep order, payment and delivery events for at least a year even if the customer deletes the account. The Seventh Schedule lists State uses (security, legal functions, SDF assessment) (https://dpdpa.com/schedule/schedule7.html). Whether 8(3) is a general one-year floor is debated (nalsar commentary cited in dpdp-and-hindi.md). COUNSEL.
- Erasure: s.8(7) erase on withdrawal or when purpose is served, unless law requires keeping; the fiduciary makes processors erase too (https://dpdpa.com/dpdpa2023/chapter-2/section8.html).

Other-law retention for payment and refund records (the tenant is the one bound):
| Law | Period | Source and status |
|---|---|---|
| CGST Act s.36 | Until 72 months after the due date of the annual return for that year; longer if proceedings are pending (one year after final disposal) | Secondary, https://www.knowyourgst.com/gstlaw/cgst-act/36-period-of-retention-of-accounts-36/ and https://www.caclub.in/section-36-of-cgst-act-2017-period-for-retaining-accounts-other-records (accessed 2026-10-31); Rule 56 not read |
| Companies Act 2013 s.128(5) | 8 financial years of books of account (companies only) | Secondary, https://www.registerkaro.in/post/sec-128-of-companies-act-2013 and https://ca2013.com/128-books-of-account-etc-to-be-kept-by-company/ (accessed 2026-10-31) |
| Income tax | Under the 1961 Act, 6 years from the end of the assessment year (Rule 6F), more if reassessment or litigation is open. The Income-tax Act 2025 replaces the 1961 Act (books provision now s.62 per commentary); I could not confirm its start date or its retention period | Secondary, https://taxguru.in/income-tax/maintenance-books-accounts-section-44aa.html ; UNVERIFIED for the 2025 Act. COUNSEL |
| Consumer Protection Act s.69 | Complaint within 2 years of cause of action (condonation possible) | Secondary, https://www.advocatekhoj.com/library/bareacts/consumerprotection2019/69.php (accessed 2026-10-31) |
| RBI payment rules | Bind the gateway/aggregator; I found no rule setting a merchant's refund-record retention period | Searched, not found. Estimate |

Arithmetic on the GST row (my calculation): a sale on 1 April 2026 (FY 2026-27) has an annual return due about 31 Dec 2027; plus 72 months is 31 Dec 2033, which is 7 years 9 months after the sale. So "7 years from the transaction" can fall up to 9 months short. "8 financial years" (the Companies Act wording) covers it.

Recommended figures:
1. Case message text, photos and contact data on the case: 12 months after case close, never below 365 days. KEEP. It meets the one-year floor and is the minimum the Rules appear to require; a longer period would need a purpose that a regulator accepts. Cost: the consumer-complaint window is 2 years, so the words of a chat are gone before the window ends. Mitigation: item 3.
2. Payment and refund ledger (amount in paise, date, order id, method type, provider reference, status): CHANGE 7 years to 8 financial years (state as "8 years" on the page; compute from the end of the financial year). Applies even after erasure, with the customer link removed.
3. Case decision record kept with the ledger for the same period: category, remedy, amount, who approved, timestamps, reason codes. No free text, no names or contact. This lets the business answer a dispute within the 2-year window without keeping the chat.
4. Audit log: at least 12 months; keep longer only where it is evidence for a money decision, and keep it free of personal content (already the design).
5. Marketing consent records: keep while the consent is relied on and for 3 years after withdrawal (estimate, to match the general 3-year limitation period; not researched). COUNSEL.

Trade-off to tell the owner: retaining customer-identifying data for 8 years because the books must be kept is a different thing from keeping the whole customer profile; the ledger needs no customer name for B2C sales. After erasure the ledger should be pseudonymous. Whether pseudonymous rows are still personal data is open (dpdp-and-hindi.md open question 1; COUNSEL).

Platform comparison: Rebel Foods keeps transaction records "up to 7 years" for tax and accounting and backups up to 90 days (https://fromrebel.com/pages/data-deletion-policy, accessed 2026-10-31). So 7 is the industry-visible figure, 8 is the conservative one.

What would change my mind: counsel confirms a tenant is not a company and the GST and tax periods are shorter; or the Income-tax Act 2025 sets a longer period; or the Gazette shows Rule 8(3) is not a general floor, which would let message text go sooner than 12 months.

Confidence: Medium for 12 months and for the ledger direction; Low on the exact 7 versus 8, because the statutes were read second-hand.

### 2.6 P2 Response target and the "90-day legal ceiling"

Findings:
- Rule 14(3), as transcribed at dpdpa.com (read 2026-10-31, https://dpdpa.com/dpdparules/rule14.html): the fiduciary must publish its grievance redressal system with a response time of "within a reasonable period not exceeding ninety days" and implement measures to meet it. The same page's commentary says the rights-request part has no separate period. Law-firm summaries read 14(3) as a 90-day limit for responding to data principal requests (https://ssrana.in/articles/meity-notifies-final-digital-personal-data-protection-rules-2025/, accessed 2026-10-31). So the sources disagree on whether it is "grievances" or "rights requests"; I could not read the Gazette to settle it. In practice both go through the same published system.
- No erasure-specific deadline was found in the Rules. Erasure is s.8(7) (when consent is withdrawn or purpose served) and s.12 (on request), with no day count in the Act text I could read.
- The Act text of s.13 says respond "within such period as may be prescribed" (https://dpdpa.com/dpdpa2023/chapter-3/section13.html); the page's 30-day and 7-day figures are unsourced commentary.
- Rule 14 starts 13 May 2027 as reported (see 2.5), so today there is no DPDP deadline in force.
- A deadline that IS in force for consumer complaints, if the tenant is an e-commerce entity: acknowledge in 48 hours, redress within one month (E-Commerce Rules 2020 rule 4, secondary sources above; COUNSEL on applicability).

Conclusion: 30 days is right. It is stricter than the 90-day outer limit, matches the E-Commerce one-month redress, and matches Rebel Foods (acknowledge in 5 business days, complete in 30 days of verification). Add a 48-hour acknowledgement.

Correction to make: the page and `LEGAL_CEILING_DAYS` text call 90 days "the legal ceiling". Recommended wording: "We aim to answer within 30 days. From 13 May 2027 the DPDP Rules will limit how long we may take to respond to a privacy complaint to 90 days." Do not present it as a current ceiling for erasure. Also the label in data_held ("privacy_legal_ceiling") should say it is a grievance-response limit.

Confidence: Medium-high on 30 days and the correction; Medium on whether 14(3) strictly covers rights requests.

What would change my mind: the Gazette text of 14(3) or the corrigendum G.S.R. 892(E) saying something different; a notified acceleration to Nov 2026.

### 2.7 P3 Label: privacy contact, grievance officer or DPO

What the law says:
- DPDP s.8(9): publish the business contact of the DPO (if applicable) or of a person who can answer questions about processing (https://dpdpa.com/dpdpa2023/chapter-2/section8.html). Rule 9: publish prominently and repeat it in every response to a rights communication (https://dpdpa.com/dpdparules/rule9.html). Both accessed 2026-10-31.
- DPDP s.8(10): establish an effective grievance mechanism; s.13: readily available means of grievance redressal.
- A DPO is mandatory only for a Significant Data Fiduciary (s.10: notified by the Central Government by volume and sensitivity of data and risk; must be India-based and answer to the board; plus independent audit and DPIAs) (https://dpdpa.com/dpdpa2023/chapter-2/section10.html, accessed 2026-10-31). Neither tenant is likely to be one (estimate; thresholds not notified in anything I found).
- The DPDP Act does not use the term "grievance officer" in the provisions I read. One legal blog says every fiduciary must appoint one (https://www.legal500.com/intelligence/india/privacy/the-role-obligations-and-liability-of-grievance-officers-under-india%27s-dpdp-act-and-dpdp-rules-2025, accessed 2026-10-31), but the article did not cite the provision, so I do not rely on it.
- The Consumer Protection (E-Commerce) Rules 2020 do require a named "Grievance Officer" (name, contact, designation) for e-commerce entities.

Recommendation: label the block "Privacy and grievance contact", with a named person or role and an email. This satisfies Rule 9 (a person who can answer questions) and s.8(10), and doubles as the consumer Grievance Officer if the tenant is an e-commerce entity. Do not use "Data Protection Officer": it implies the SDF status and its board-reporting duties, and a mislabel could be read as a representation. Same contact appears in every rights response (Rule 9) and in the close-without-remedy message (M2).

COUNSEL: whether each tenant is an e-commerce entity; whether the same person may serve both roles.

Confidence: Medium.

What would change my mind: a tenant becomes notified as an SDF (then "Data Protection Officer" is required and must meet s.10).

### 2.8 P4 Completion message after erasure

Recommendation: yes, send one message. A person who asked for erasure expects to be told it happened; Rebel Foods promises a confirmation email (https://fromrebel.com/pages/data-deletion-policy, read 2026-10-31); Zomato gives no timeline or confirmation (https://www.eternal.com/policies/privacy/, read 2026-10-31). The Rules require the contact to be repeated in every response to a rights communication (Rule 9), which includes this message.

Channel and data:
1. At request time (before sign-in is removed), ask which verified channel to use: the phone (WhatsApp/SMS) or email already on the account, defaulting to the one the request came from. Store the destination only in an outbox row with a purpose label, no other profile data, and a hard TTL of 7 days (estimate) after which it is deleted whether or not the send worked.
2. Send only after the executor reports success (hard rule 7: never "done" before the system holds that fact). Delete the outbox destination as soon as the send reaches a final state (delivered, failed, or unknown after the connector timeout). If the send fails or is unknown, do not retry beyond the TTL and do not claim delivery; the request record shows `completion_message: failed|unknown`.
3. Keep, with no personal content, an erasure receipt: request id, dates, counts of items removed and kept, and message state. This proves the action (DPDP s.6/8 proof duty) and sits within the audit log rules.
4. No in-app channel: the sign-in is gone. If a person has no verified contact left, there is nothing to send; say so on the request screen before they confirm ("we will tell you by {channel}").
5. Is it marketing? No: it is a response to a rights request, so it needs no marketing consent. COUNSEL on whether holding the destination for up to 7 days after erasure sits within s.7(a)/Rule 14 or needs a notice line; I think a one-line notice at request time covers it.

Content (English, draft):
"Your request {reference} is complete. We removed your name, contact details and message text. We kept payment and refund records, without your name, because tax and accounting law requires them, until {date}. Records of the money we handled are kept up to 8 years; message text is already gone. If you have a question or complaint, contact {privacy_grievance_contact}; we reply within 30 days. If you are still not satisfied, you can complain to the Data Protection Board of India after you have used our process." (Board route: s.13 says exhaust the grievance route first.)

Never include the customer's name, order contents or amounts in the message.

Confidence: Medium. What would change my mind: counsel says the post-erasure destination hold needs explicit consent (then ask for tick-box consent at request time); the owner decides to say nothing and show only a status on the request screen (acceptable only if the person can still see it, which they cannot after sign-in is removed).

### 2.9 P5 "What we do not keep" claims

Findings:
- RBI: authorised payment aggregators and the merchants they onboard may not store customer card credentials in their own systems; only limited data such as the last four digits and the issuer name may be kept for tracking; token-based card-on-file replaced storage; the purge deadline was 30 September 2022 after extensions (secondary: https://khaitanco.com/thought-leaderships/RBI-extending-the-restriction-on-Storage-of-Actual-Card-Data-Card-on-File-to-facilitate-compliance and https://www.mondaq.com/india/financial-services/1208986/rbi-extending-the-restriction-on-storage-of-actual-card-data-cardonfile-to-facilitate-compliance, accessed 2026-10-31; RBI circular not read). So for cards the claim "we do not store card numbers" is also what the law requires of a merchant, so it is safe if true.
- Benchmarks: Jubilant (Domino's India) said in 2021 that full card numbers, CVV and passwords are not stored (https://dtnext.in/business/2021/04/20/dominos-india-users-data-safe-asserts-jubilant-foodworks, via privacy-page-needs.md, accessed 2026-10-28). Zomato says card data is passed to third-party processors that "may store" it (https://www.eternal.com/policies/privacy/, read 2026-10-31); this shows the correct nuance: the processor may hold it, the business does not.
- In our code (grep of app/ for vpa, last4, card_number, upi_id, 2026-10-31): `payments.method` and `amount_paise` and `status` exist (app/agents/tools.py:94), and the only card/UPI references are the claim keys in `data_held.py` and i18n. No card or UPI identifier field was found. This does not prove that provider payloads, logs or LLM prompts are free of them; raw gateway responses can include a UPI ID (VPA) or last four digits.

Claims, by safety:
| Claim | Safe? | Condition |
|---|---|---|
| "We never see or store your card number, CVV, expiry or card PIN" | Yes | Payment is collected on the provider's hosted or tokenised page; a test fails if a 13-19 digit number passes through any table, log, audit payload or prompt. |
| "We never see your UPI PIN or net-banking password" | Yes | These never reach a merchant in any UPI or gateway flow. (My knowledge; no source found.) |
| "We do not store your UPI ID" | Only if tested | Many gateway refund payloads carry the payer VPA. Claim only if a scan of stored provider payloads finds none and the connector drops the field. |
| "We do not keep payment details" (broad) | No | We do keep the method type, amount, status and provider reference. Say that instead. |
| "Our payment provider may keep card data to let you pay again" | Needed if true | If a saved-card feature is ever added, disclose the processor as in Zomato's wording. |

Recommended page wording (once the scan test exists): "We never see or store your full card number, CVV or UPI PIN. Our payment provider handles those. We keep a payment reference, the amount, the payment method type and its status." The existing mechanism (`CONFIRMED_NOT_KEPT` empty by default, claim shown only when code confirms) is correct; the owner should confirm `card_numbers` only (not `upi_details`) until the scan test exists.

COUNSEL/engineering: the real gateway (not the mock) determines this; recheck with the provider's data sheet when a gateway is chosen. PCI DSS scope is a separate topic not researched.

Confidence: Medium-high for the card claim and the PIN claim; the UPI ID claim depends on testing.

## 3. Mapping to stories (for the scrum-master; I do not edit EPICS.md)

| Rec | Story | Impact | v1 fit |
|---|---|---|---|
| M1 amend spice_route wrong_item policy; align cap | new story: policy v2 for wrong item and refund cap (owner decision first); S7.9 follow-up to hide the refund option on aggregator orders if not already | High | Yes, small |
| M2 reworded close text with contact | S7.6 follow-up; depends on S8.5 contact setting | Med | Yes |
| M3 switch rule and override | S7.10 follow-up (new story: "switch authorship and owner override") | High (money) | Yes |
| M4 campaign threshold setting | E18 growth approval (existing) plus PROJECT.md edit by the owner | Low | Yes |
| P1 change payment years 7 to 8, add decision record | S8.5a follow-up (`payment_retention_years`), retention job story | Med | Yes |
| P2 label correction and 48-hour acknowledgement | S8.5a / S8.5c follow-up | Med | Yes |
| P3 label | S8.5a follow-up | Low | Yes |
| P4 completion message with outbox | new story: erasure completion notice (Safety: customer data) | Med | Yes, if erasure (S8.5c) is merged |
| P5 scan test and confirm card_numbers | S8.5a follow-up: test that fails on card-like numbers in tables and logs | Med | Yes |

## 4. Needs counsel or the owner

Counsel:
1. Gazette text of Rule 14(3) (grievances versus rights requests), Rule 8(3) scope, and whether pseudonymised ledger rows are still personal data.
2. Whether each tenant is an "e-commerce entity" under the 2020 Rules (grievance officer, 48 hours, one month).
3. Retention periods under the Income-tax Act 2025, CGST s.36/Rule 56, and Companies Act s.128 for each tenant's legal form.
4. Whether holding a contact destination for up to 7 days to send the erasure confirmation is allowed without a separate consent.
5. Current status of any DPDP timeline compression (Gazette after April 2026).

Owner:
1. M1: amend spice_route wrong-item policy text, or restrict the refund option to whole-order cases; and decide the cap for a whole wrong order (50% today).
2. M2: do you want National Consumer Helpline named in the customer message?
3. M3: override limit (suggest Rs 500) and who may use it.
4. M4: edit PROJECT.md section 17 to "every campaign needs two approvers".
5. P1: 12 months for messages and 8 years for the ledger; confirm.
6. P3: who is named as the privacy and grievance contact for each tenant.
7. P5: confirm only the card-number claim for now.
8. Could not be verified, so please look in a browser if the benchmark matters: Swiggy, Zomato, Domino's India and Tata Starbucks India refund pages.

## Sources (all accessed 2026-10-31 unless noted)
- https://dpdpa.com/dpdparules/rule8.html ; https://dpdpa.com/dpdparules/rule9.html ; https://dpdpa.com/dpdparules/rule14.html ; https://dpdpa.com/schedule/schedule7.html
- https://dpdpa.com/dpdpa2023/chapter-2/section8.html ; .../section10.html ; https://dpdpa.com/dpdpa2023/chapter-3/section13.html
- https://ssrana.in/articles/meity-notifies-final-digital-personal-data-protection-rules-2025/ ; https://ssrana.in/articles/meity-plans-to-cut-short-dpdp-compliance-timeline-and-notify-cross-border-restrictions-for-sdfs/
- https://www.legal500.com/intelligence/india/privacy/the-role-obligations-and-liability-of-grievance-officers-under-india%27s-dpdp-act-and-dpdp-rules-2025
- https://consumerhelpline.gov.in/ ; https://www.indialaw.in/blog/civil/consumer-protection-e-commerce-rules/ ; https://www.taxclue.in/blog/rule-4-8-11-consumer-protection-e-commerce-rules-2020-cancellation-charges-consent-refunds-and-price-manipulation
- https://www.taxclue.in/blog/section-2-consumer-protection-act-2019-definitions-unfair-trade-practice-unfair-contract-e-commerce-and-others/ ; https://www.freepressjournal.in/amp/analysis/know-your-rights-return-of-goods-rules-provisions-a-consumer-should-be-aware-of ; https://www.advocatekhoj.com/library/bareacts/consumerprotection2019/69.php ; https://www.taxclue.in/blog/section-69-consumer-protection-act-2019-limitation-period-for-complaints/
- https://www.knowyourgst.com/gstlaw/cgst-act/36-period-of-retention-of-accounts-36/ ; https://www.caclub.in/section-36-of-cgst-act-2017-period-for-retaining-accounts-other-records ; https://www.registerkaro.in/post/sec-128-of-companies-act-2013 ; https://ca2013.com/128-books-of-account-etc-to-be-kept-by-company/ ; https://taxguru.in/income-tax/maintenance-books-accounts-section-44aa.html
- https://khaitanco.com/thought-leaderships/RBI-extending-the-restriction-on-Storage-of-Actual-Card-Data-Card-on-File-to-facilitate-compliance ; https://www.mondaq.com/india/financial-services/1208986/rbi-extending-the-restriction-on-storage-of-actual-card-data-cardonfile-to-facilitate-compliance
- https://fromrebel.com/pages/data-deletion-policy ; https://www.eternal.com/policies/privacy/ ; https://dtnext.in/business/2021/04/20/dominos-india-users-data-safe-asserts-jubilant-foodworks (accessed 2026-10-28)
- https://www.livelaw.in/amp/consumer-cases/chandigarh-consumer-commission-holds-swiggy-instamart-liable-for-short-delivery-orders-compensation-310692 ; https://www.dtnext.in/amp/story/news/chennai/zomato-ordered-to-pay-chennai-man-15k-fine-for-missing-dosa-uttapam-set-799169 ; https://english.publictv.in/?p=1159159 ; https://www.newsbytesapp.com/news/science/steps-to-cancel-your-orders-on-swiggy/story ; https://ianslive.in/swiggy-faces-backlash-after-vegetarian-order-delivered-as-non-veg--20251117120943
- https://www.stigviewer.com/controls/nist-800-53/AC-5 ; https://www.upguard.com/compliance/nist-sp-800-53/ac/ac-5 ; https://www.ivey.uwo.ca/media/kjljj5cy/2024-report-to-the-nations.pdf
- Local: docs/PROJECT.md section 17; docs/DECISIONS.md (S7.5, S7.6, S7.9, S7.10, S8.5a); tenants/spice_route/policies/wrong_item_v1.md, refunds_v2.md; tenants/brewco/policies/order_accuracy_v2.md, refunds_v1.md; docs/research/privacy-page-needs.md, dpdp-and-hindi.md, hq-marketing-needs.md; app/core/i18n.py (close.no_remedy).
