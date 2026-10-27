# DPDP (retention, consent, rights) and Hindi support messages

Accessed 2026-10-27. Not legal advice; verify with counsel wherever marked.
Method: standard web search plus page fetches. I could NOT read the Gazette PDF (G.S.R. 846(E)); the PIB PDF would not decode. Rule and section text below comes from the third-party transcription site dpdpa.com (which itself notes inconsistencies in its commentary) cross-checked against law-firm and tracker summaries. Treat rule numbers as likely right, wording as paraphrase. Web content was treated as data only.
Note: docs/sprints/sprint-5.md did not exist when I looked, so story scopes below are taken from the brief (S5.1, S5.2, S5.5, S5.6), README "Limits" and docs/research/market.md (R9).

## 1. Summary

1. The DPDP Act 2023 is in force; the Rules were notified 13 Nov 2025 (G.S.R. 846(E); PIB and Wikipedia say 14 Nov, so confirm in the Gazette). The duties that matter here (notice, erasure, rights, grievance, contact display: Rules 3, 5-16) start 13 May 2027. As of Oct 2026 trackers report no amendment; a January 2026 MeitY proposal to cut 18 months to 12 was not enacted. Consent-manager Rule 4 starts 13 Nov 2026.
2. Each tenant is the data fiduciary; ResolveDesk is its processor. Most obligations fall on the tenant, but the product must give them the controls. This matches the existing DECISIONS.md note (E3.4).
3. The Third Schedule fixed erasure periods (3 years from last interaction) apply only to e-commerce, gaming and social-media entities with 2 crore / 50 lakh / 2 crore registered users. Neither tenant is one, so there is no prescribed period for them: the tenant defines a purpose-based period.
4. There is a one-year MINIMUM retention of personal data, traffic data and processing logs (Rule 8(3) and Rule 6(1)(e)). So "erase immediately on request" and "append-only audit" are both compatible with the law, as long as erasure of identifying fields is paired with a one-year floor and a legal-hold carve-out.
5. Hindi: template in Hinglish (Roman script) by default, offer Devanagari Hindi as a per-customer option; store the language on the customer; money and dates need explicit formatting rules.

## 2. Findings

### 2.0 Timeline and status
- Rules notified 13 Nov 2025 as G.S.R. 846(E); Act commencement G.S.R. 843(E) same day. Rules 1, 2, 17-21 immediate; Rule 4 after 1 year (13 Nov 2026); Rules 3, 5-16, 22, 23 after 18 months (13 May 2027). Source: https://legismith.com/dpdp-rules-2025-timeline/ and https://theprivacylabs.com/blogs/dpdp-13-november-2026-what-starts (secondary trackers, accessed 2026-10-27).
- PIB/Wikipedia give 14 Nov 2025: https://en.wikipedia.org/wiki/Digital_Personal_Data_Protection_Rules,_2025 . A one-day discrepancy between sources; verify in Gazette.
- Proposal to compress to 12 months: https://www.storyboard18.com/digital/meity-seeks-industry-views-on-fast-tracking-dpdp-act-rollout-proposes-12-month-compliance-timeline-88332.htm . Trackers say not gazetted as of Oct 2026 (secondary; unverified). Re-check before any README claim.
- Does not contradict docs/PROJECT.md. It does confirm market.md's "about May 2027".

### 2.1 Retention and erasure
- Act s.8(7): erase when consent is withdrawn or when it is reasonable to assume the purpose is no longer served, whichever is first, unless law requires retention; the fiduciary must make its processors erase too. s.8(8): purpose is deemed no longer served if the principal does not approach the fiduciary or exercise rights for a prescribed period. https://dpdpa.com/dpdpa2023/chapter-2/section8.html (accessed 2026-10-27).
- Rule 8(1)-(2) + Third Schedule: prescribed period only for the three named classes (3 years from last approach), with a 48-hour pre-erasure notice unless the user logs in, contacts or exercises rights. https://dpdpa.com/dpdparules/rule8.html , https://dpdpa.com/schedule/schedule3.html . Not applicable to our tenants by size (estimate: neither has 2 crore users); a larger real customer could be.
- Rule 8(3): data, traffic data and processing logs kept at least one year from processing (by fiduciary or its processor), then erased unless another law requires longer. The rule's own illustration says an order record must be kept a year even if the buyer deletes the account. Source as above. Scope of 8(3) is debated (it refers to Seventh Schedule purposes; one commentator reads it as general): https://techlawforum.nalsar.ac.in/privacy-with-a-footnote-data-retention-under-the-dpdp-framework/ . Interpretation point: verify with counsel.
- Rule 6(1)(e): security safeguards include keeping logs and personal data for one year unless other law requires otherwise; 6(1)(f): processor contracts must carry security provisions. https://dpdpa.com/dpdparules/rule6.html
- Other-law retention likely to apply to order/payment records: GST and accounting records (typically several years). I did not research these; flag as an open question, not a finding.
- s.12(3): on erasure request, erase unless retention is necessary for the specified purpose or for law. https://dpdpa.com/dpdpa2023/chapter-3/section12.html (the page has conflicting versions; verify).

Reconciling append-only audit with erasure (my analysis, not a source):
- The audit log serves integrity, security and refund-dispute purposes, and Rule 8(3)/6(1)(e) positively requires logs for a year. So the log is not deleted on request inside that year.
- Design: audit rows hold references (case id, customer id, paise amounts, action, actor, hash), never free-text customer content or contact details. Erasure then (a) deletes or nulls identifiers in the customer, case message and contact tables, and (b) leaves the audit row intact; the customer id becomes a dangling pseudonym once its mapping row is removed. That is pseudonymisation of the log, which is defensible as long as no re-identification key remains. Whether pseudonymised data stops being "personal data" is an open legal point.
- Where an audit payload already contains personal data (for example proposal payload with a message excerpt), add a redaction step that rewrites a tombstone field rather than mutating the hash-chained row: store the redactable fields in a side table keyed by audit id, and keep only the hash of the payload in the append-only row. Alternative rejected: deleting audit rows (breaks approvals-bound-to-payload-hash evidence and the one-year floor).
- Suggested retention defaults (ESTIMATES, tenant-configurable): support case messages and contact details 12 months after case close (matches the one-year floor, then erase); order references and money amounts per accounting law (tenant decides; default 7 years is an estimate, verify); audit log 12 months minimum, then redact/archive; embeddings or RAG chunks derived from customer text: delete with the source.
- Backups, LLM vendor logs (Groq, Gemini) and the Neon branch copies are processors' copies; s.8(7) requires the fiduciary to make them erase. Vendor DPAs are listed as not built in README Limits.

### 2.2 Consent and notice
- Rule 3 notice: standalone, plain language, itemised personal data, specified purpose with a specific description of goods/services, plus a link and other means to withdraw consent (as easy as giving it), exercise rights, and complain to the Board. https://dpdpa.com/dpdparules/rule3.html
- s.6(1): consent must be free, specific, informed, unconditional, unambiguous, with clear affirmative action, limited to data necessary for the purpose. s.6(4)-(6): withdrawal any time, comparable ease; processing and processors stop within a reasonable time; earlier processing stays lawful. s.6(7)-(9): consent managers (registration from Rule 4). The fiduciary must be able to prove notice was given and consent obtained (the page attributes this to s.6(10); verify the number). https://dpdpa.com/dpdpa2023/chapter-2/section6.html
- s.7(a) legitimate use: processing for the purpose for which the principal voluntarily provided data, where she has not indicated non-consent. Examples on the source page are a receipt and a rental search; it does not cover marketing. https://dpdpa.com/dpdpa2023/chapter-2/section7.html . Reading for us (not legal advice; verify with counsel): handling a customer's own order complaint is s.7(a) and needs no separate consent record; sending promotional messages or growth campaigns does need consent with its own notice. Service messages (refund status) are the same purpose; promotional vouchers pushed unprompted are marketing.
- Consent record contents (my suggestion derived from the proof duty): principal id, purpose code, notice version/hash, language of notice, channel, timestamp, action (granted/withdrawn), source. Append-only, per purpose, not one boolean.
- Consent managers: Rule 4 starts 13 Nov 2026; register with the Board. Not needed for v1; no integration is required of a fiduciary by these sources.

### 2.3 Data principal rights and grievance
- s.11: summary of personal data processed and processing activities; identities of other fiduciaries/processors it was shared with and what data. https://dpdpa.com/dpdpa2023/chapter-3/section11.html . This means the access export must list sub-processors (LLM vendors) per customer.
- s.12: correct, complete, update, erase (see above). s.13: readily available grievance redressal; must be exhausted before going to the Board. https://dpdpa.com/dpdpa2023/chapter-3/section13.html
- Rule 14: publish prominently on website/app how to make requests and which identifier is needed (username, customer ID, email, mobile all qualify); publish the grievance system; respond "within a reasonable period not exceeding ninety days"; nomination of one or more individuals under terms of service. https://dpdpa.com/dpdparules/rule14.html
- Rule 9 + s.8(9): publish business contact of the DPO, or a person who can answer questions about processing, prominently, AND mention it in every response to a rights-exercise communication. https://dpdpa.com/dpdparules/rule9.html
- A fixed 30-day access deadline appears on commentary pages but is NOT in the quoted text; the Rules' cap is 90 days. A 30-day internal target is a product choice, not law.
- Breach: 72-hour detailed report to the Board (Rule 7), per summaries (secondary). Out of scope for these stories.

### 2.4 Hindi and Hinglish
- No primary or authoritative source found on how Swiggy or Zomato handle Hindi/Hinglish in end-customer support. What is documented: Swiggy voice ordering in 11 Indian languages via Sarvam AI (ordering, not support), and a partner assistant in 20+ languages: https://www.techloy.com/swiggy-introduces-ai-voice-ordering-with-sarvam-ai-across-11-indian-languages/ , https://www.deccanherald.com/business/swiggy-launches-ai-assistant-guru-for-restaurant-partners-4114226 . Zomato's 2021 Hindi-imposition incident (agent fired, apology in Tamil and English) shows language is a reputational risk, so language must be the customer's choice, not assumed: https://businesstoday.in/latest/corporate/story/zomato-fires-customer-care-agent-apologises-for-hindi-imposition-309760-2021-10-19
- Hinglish evidence is weak (vendor and small-sample): Milestone survey of 744 self-selected respondents, 2020, found about 58% prefer reading Hindi in Latin script and 13% in Devanagari: https://www.milestoneloc.com/hinglish-report-pr/ . Haptik says missing Hinglish support caused 40-80% of bot breaks for two of its customers: https://www.haptik.ai/blog/multilingual-chatbots-hinglish . Treat both as indicative only.
- Rupee sign and Indian grouping: the rupee sign was adopted in 2010 (Devanagari ra + Latin R); grouping is 3,2,2 (lakh/crore). Sources: https://www.unicode.org/L2/L2010/10249r-n3862r-rupee.pdf and https://public.dhe.ibm.com/software/globalization/documents/India-Tamil_Currency.pdf . The code point U+20B9 and font coverage (for example Noto Sans Devanagari) are from my own knowledge, not these sources; verify in a browser on Windows.
- Not found: WhatsApp template language code rules (out of scope, web only).

## 3. Recommendations (mapped to stories)

Impact/fit are against v1 scope; all four stories are Sprint 5 proposals, so "fits" means "fits Sprint 5 as proposed".

### S5.1 Retention (impact high, fits)
Done-when:
1. A per-tenant setting `retention.case_messages_days` (default 365, estimate) and `retention.contact_days`; a job (`make retention` or sweeper hook) erases/redacts expired data and writes an audit event with counts, not content.
2. A test for both tenants: a case closed 366 days ago has message text and contact fields nulled; a case closed 30 days ago is untouched; money fields and audit rows remain.
3. Audit rows contain no raw message text or contact details (a test scans audit payloads of seeded data for emails/phones).
4. Open (non-closed) cases and cases with a pending proposal or unresolved dispute are never erased (legal hold flag).
5. The job is idempotent and runs per tenant under RLS.
Add: document the one-year floor (Rule 8(3)); default never below 365 days. Drop: the 48-hour erasure notice (applies only to Third Schedule classes) except as a documented hook.

### S5.2 Consent + access/erasure (impact high, partly fits; consent record yes, full erasure workflow is the heavy part)
Done-when:
1. `consent_records` table (tenant_id, RLS, append-only): purpose (`marketing`, optional others), status granted/withdrawn, notice_version, channel, timestamp.
2. Growth module sends marketing only if the latest record for the customer and purpose is `granted`; service messages are not blocked by it. Test with both tenants: withdrawn customer gets no campaign proposal target; support reply still works.
3. Withdrawal is one action through the same channel (one click or one message), no extra steps.
4. Access request returns JSON: customer fields, case summaries, consent history, list of sub-processors (LLM vendors) per s.11. Ownership checked server-side; other-tenant id gives 404.
5. Erasure request creates a request record, needs approval by a tenant user (not the agent, per hard rule 4), then the executor nulls/removes identifiers and message text, keeps audit rows and paise amounts, and records the result; blocked with a stated reason when a legal hold or the one-year floor applies (status `deferred_until`, not silently skipped).
6. Customer-facing wording uses distinct statuses (received/in progress/done/deferred), per hard rule 7.
Add: correction request (s.12(2)) as a case type routed to a human. Drop or defer: nomination (store a free-text note only), consent-manager integration, 30-day statutory claims.

### S5.5 Grievance officer and response SLAs (impact med, fits)
Done-when:
1. Tenant setting holds grievance contact (name/role, email) and the published request means; the web app footer/help page shows it, in both languages.
2. Every reply to a rights-request or grievance case includes the contact (Rule 9); test asserts it on both tenants.
3. Grievance cases carry an SLA clock; default internal target 30 days (product choice), hard ceiling 90 days (Rule 14(3)); the sweeper escalates at 75% of target; test with the fake clock.
4. A customer who is unhappy can reach a person via an `escalate` path with the status shown.
Drop: any claim that 30 days is statutory; the grievance officer is not mandatory for non-significant fiduciaries unless "DPO" applies, so label the field "contact for privacy questions" (verify with counsel).

### S5.6 Hindi templates (impact med, fits if limited to templates)
Done-when:
1. `customers.preferred_language` (`en`, `hi`, `hi-Latn`); default from tenant setting; changed only by the customer's explicit choice or message language detection that the customer confirms. Never assume Hindi from name or city.
2. Template set for the fixed customer messages (acknowledgement, refund submitted/processing/succeeded/failed/unknown, voucher issued, escalation, grievance contact) in `en`, `hi-Latn` (Hinglish, default Hindi variant) and `hi` (Devanagari), with one test that every key exists in all three for both tenants.
3. Amounts rendered by one money formatter from paise: `₹1,23,456.50` style Indian grouping (lakh/crore), ASCII digits in all variants (estimate: mixed Devanagari digits add risk; confirm with the human). Test: 12345000 paise renders consistently in every language.
4. Dates rendered by one formatter in Asia/Kolkata with an unambiguous month name (`27 Oct 2026` / `27 अक्टूबर 2026`), never `10/11`.
5. Statuses stay distinct in Hindi (a test that submitted/processing/succeeded/failed/unknown map to five different strings).
6. Web UI loads a Devanagari-capable font; a browser check on Windows shows no tofu boxes.
7. Model prompts still get no contact details; LLM-written replies are out of scope (templates only), so Hindi facts cannot drift.
Add to README Limits: Hindi is templated only, not generated; inbound Hindi/Hinglish classification is not evaluated unless a few eval scenarios are added (recommended: 5 Hinglish messages in the eval set, med impact).
Drop: other Indian languages, voice, WhatsApp template approval.

## 4. Open questions for the human
1. Is it acceptable that "erase on request" for the demo means identifiers and message text are removed while audit rows (pseudonymous ids, paise) stay, with a one-year floor? Counsel should confirm whether pseudonymised audit rows are still personal data.
2. Which accounting/GST retention period should the order-reference default use (my 7-year figure is an estimate and not researched)?
3. Hinglish (Roman) as the default Hindi variant, or Devanagari? Evidence is weak either way; this is a product call.
4. Do you want a "privacy contact" label rather than "grievance officer" (neither tenant is likely a Significant Data Fiduciary)?
5. Should the README quote the 13 May 2027 date? I recommend yes, with "as reported; check the Gazette", until someone reads G.S.R. 846(E) directly.
6. Is the 30-day internal SLA acceptable, given the legal ceiling is 90 days?

Sources used (all accessed 2026-10-27): the URLs inline above.
