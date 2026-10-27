# Reply-language auto-detection (en / hi-Latn / hi) - S7.12

Accessed 2026-10-28. Web content treated as untrusted data. Items marked (estimate) are my judgement, not sourced.

## 1. Summary
- Devanagari characters are a near-certain, free signal for `hi`. Romanized Hindi (Hinglish) is the hard case; script alone cannot separate it from English.
- Off-the-shelf LID (fastText lid.176, lingua) is built for script-distinct languages. A 2025 paper says romanization makes Hindi/Urdu "highly confusable", and I found no benchmark of these tools on Hinglish. Do not add them for v1.
- Recommended: Devanagari rule, then the existing classifier LLM call returns `language` + `confidence`, then a small Hinglish stop-word heuristic as fallback, default `en`.
- Language is fixed per case from the first message, but updated when a later customer message is confidently different.
- No new dependency. No contradiction with docs/PROJECT.md found (I did not find S7.12 in docs/EPICS.md; story id taken from the request).

## 2. Findings
1. **Romanization hurts LID.** "Such romanization renders languages that are normally easily distinguished based on script highly confusable, such as Hindi and Urdu"; a dedicated model reached F1 74.7% (pretrained neural baseline) to 88.2% (synthetic plus harvested data) on a 20-language Indic romanized benchmark. https://arxiv.org/abs/2504.21540
2. **fastText lid.176** recognizes 176 languages, 126 MB (`.bin`) or 917 kB (`.ftz`), CC-BY-SA 3.0; the page gives no short-text accuracy figures and nothing on Romanized Hindi. https://fasttext.cc/docs/en/language-identification.html
3. **lingua-py** is a Naive Bayes n-gram (1-5) detector that claims good short-text results, but its docs I could read give no Hindi-specific numbers, and its Hindi model is for Devanagari. https://github.com/pemistahl/lingua-py (Roman-script Hindi support: not documented; treat as unsupported.)
4. **Code-mixed LID is usually token-level and trained on code-mixed data**: ~94.5% on SAIL ICON 2017 (sub-word LSTM) and >96% in another Hindi-English tagging paper; a Google feed-forward model targets code-mixed text across 100 languages. These are token-level, not message-level, so not comparable to a per-message label. https://arxiv.org/pdf/1703.10772 , https://ar5iv.arxiv.org/html/1810.04142
5. **Industry practice (vendor, 2021):** Haptik says its bots detect whether a user starts in Hinglish or Hindi and continue in that language; brands can configure Hindi vs Hinglish replies; the example answers a Hinglish query in Hinglish. https://prnewswire.com/in/news-releases/haptik-ai-now-supports-india-s-universal-language-hinglish-846506434.html
6. **Gap:** I found no public description of how Swiggy/Zomato configure language replies. Do not claim them as precedent.
7. Accuracy expectations on short code-mixed text (estimate): Devanagari rule ~99%; LLM on Hinglish with at least 3 content words ~90-95%; on 1-2 word messages, close to a coin flip. Validate with the eval set below rather than trusting these.

## 3. Recommendations

| # | Recommendation | Maps to | Impact | v1? |
|---|---|---|---|---|
| R1 | Layered detector in `app/core/i18n.py`: (a) any Devanagari letter share >= 30% of letters -> `hi`; (b) else classifier LLM returns `language in {en, hi-Latn, hi}` + `confidence` in its existing structured output (no extra call); (c) if LLM unavailable or confidence < 0.6, Hinglish word-list fallback; (d) else `en`. | S7.12 | high | yes |
| R2 | Hinglish fallback list (~40 high-frequency tokens, whole-word, lowercase): `hai, hain, nahi, nahin, mera, meri, mujhe, aap, kya, kyun, kab, abhi, bhai, yaar, paisa, wapas, refund karo, order nahi aaya, der, bahut, kitna, jaldi, chahiye, tha, thi, ho gaya, nahi mila, ghanta, khana, galat, kharab, theek, kripya, dhanyavad`. Rule: >= 2 distinct hits and hits >= 25% of tokens -> `hi-Latn`. Avoid ambiguous tokens that are English words or names (`to`, `me`, `main`, `in`, `ho`). | S7.12 | med | yes |
| R3 | Per-case language: set from the first customer message; update only if a later message is detected with confidence >= 0.8 and differs from the current value on 2 consecutive messages (or one Devanagari message). Short or ambiguous messages (<= 2 tokens, only emoji/digits/order ids) never change it. | S7.12 | high | yes |
| R4 | Mirror script as well as language: Devanagari in -> Devanagari out; Roman Hindi in -> Roman Hindi out; mixed -> the dominant language by content-word count, tie -> previous case language, then `en`. Haptik-style behaviour (finding 5). | S7.12 | med | yes |
| R5 | Retire manual `customers.preferred_language` as a source; keep it only as the initial default for a brand-new customer with no message (do not drop the column in v1). Log detected label, source (rule/llm/heuristic/default) and confidence to the audit trail. | S7.12 / app/core/audit | med | yes |
| R6 | Detector output only picks a template locale; it must never be interpolated into prompts or templates unvalidated (closed set of 3 labels, else `en`). Customer text is untrusted (CLAUDE.md rule 9 spirit). | S7.12 | med | yes |
| R7 | fastText/lingua: do not adopt in v1. Revisit only if eval accuracy of R1 is below the criteria. | new story: optional LID library spike | low | no |

## 4. Edge cases and decisions
- **One-word messages** ("refund", "hello", "ok", "?"): no language signal; keep case language, default `en` for a first message. "Namaste"/"hi" alone: do not switch.
- **Emoji / digits / order id only:** ignore for detection (strip before counting).
- **Transliterated brand/dish names** ("Paneer Butter Masala", "Chai", "Biryani"): not Hindi evidence. Exclude catalogue names and keep the list free of food words except where clearly verbs/adjectives; the LLM prompt should say to ignore proper nouns.
- **Mixed sentence** ("my order abhi tak nahi aaya, refund do"): Hinglish; the English word share is common and should not force `en`.
- **Mid-conversation switch:** follow R3; do not flip on a single ambiguous message; if the customer writes Devanagari, switch at once.
- **Reply to an agent prompt** ("yes", "1", "haan"): `haan/nahi` are hi-Latn evidence only when the message has >= 2 tokens; a lone "haan" keeps the current language.
- **Case already open:** the language chosen applies to all customer-facing templates in that case, including approval/refund confirmations (still verified facts only, rule 7).
- **Urdu in Roman script** is indistinguishable from hi-Latn (finding 1); acceptable, reply in hi-Latn.

## 5. Acceptance criteria
1. Devanagari-majority message -> `hi` with no LLM call (unit test asserts zero calls).
2. With the LLM stub raising/unavailable, the heuristic still yields correct labels for the test set rows marked "heuristic".
3. Output label is always one of `en|hi-Latn|hi`; invalid LLM output -> fallback chain, never an exception.
4. Case language is set on first message and persisted; a single low-confidence or <= 2-token message does not change it; two consecutive confident messages in another language do.
5. Run for both tenants (tests never name a tenant); template selection uses the detected label and customer text cannot inject a locale.
6. Eval target on the 12 messages below: >= 11/12 correct with the real LLM; 100% on the rule and heuristic rows.
7. Audit record contains label, source, confidence.

## 6. Test messages (for tests/eval scenarios)

| # | Message | Expected | Path |
|---|---|---|---|
| 1 | "मेरा ऑर्डर अभी तक नहीं आया" | hi | rule |
| 2 | "Where is my order? It's been 50 minutes." | en | llm / default |
| 3 | "mera order abhi tak nahi aaya, refund do" | hi-Latn | llm + heuristic |
| 4 | "bhai khana bahut thanda tha, paisa wapas chahiye" | hi-Latn | heuristic |
| 5 | "My biryani was cold, please refund" | en | default |
| 6 | "order #4821 में चिकन नहीं था" (Devanagari plus id) | hi | rule |
| 7 | "refund" | en (first message) / unchanged (later) | default / R3 |
| 8 | "😡😡 order 4821" | en (first) / unchanged (later) | default / R3 |
| 9 | "Paneer Butter Masala and Masala Chai missing from order" | en | llm (dish names are not Hindi) |
| 10 | "kya aap bata sakte ho ki refund kab milega?" | hi-Latn | heuristic |
| 11 | Case in hi-Latn; next message "haan" | stays hi-Latn | R3 |
| 12 | Case in en; then two messages "mujhe paisa wapas chahiye" and "order nahi mila abhi tak" | switches to hi-Latn after the 2nd | R3 |
| 13 | Case in en; then "अब हिंदी में बताइए" | switches to hi | rule |

## 7. Open questions for the human
1. Hinglish reply script: always Roman for hi-Latn, or should a Hindi-script customer ever receive Roman and vice versa? (R4 assumes strict mirroring.)
2. Should a customer be able to override the detected language (e.g. "reply in English")? Out of scope per request ("no manual setting"), but an explicit instruction is a strong signal; add as a later story?
3. Is dropping `customers.preferred_language` from the data model acceptable later, or keep for analytics?
4. Does the classifier prompt/schema change count as an eval-baseline change (threshold of 0.6/0.8 are my estimates to tune)?
5. Is mild Urdu-in-Roman misclassification acceptable?

Sources: [arXiv 2504.21540](https://arxiv.org/abs/2504.21540), [fastText LID](https://fasttext.cc/docs/en/language-identification.html), [lingua-py](https://github.com/pemistahl/lingua-py), [arXiv 1703.10772](https://arxiv.org/pdf/1703.10772), [Google code-mixed LID](https://ar5iv.arxiv.org/html/1810.04142), [Haptik release](https://prnewswire.com/in/news-releases/haptik-ai-now-supports-india-s-universal-language-hinglish-846506434.html)
