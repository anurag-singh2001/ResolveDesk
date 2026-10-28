"""Customer-facing text: one lookup, template key + language -> text (S5.6).

Every message a customer reads is a fixed template here, never model output, so a translation
cannot drift from the facts (hard rule 7). A case's language is detected from the customer's
own messages (app/core/language.py), never guessed from a name or a place;
customers.preferred_language is only the initial default. A missing
translation falls back to English, so a half-translated key shows English, not nothing.

Languages: `en` (default), `hi-Latn` (Hinglish, Roman script), `hi` (Devanagari). Digits are
ASCII in all of them and amounts always come from format_inr (Indian grouping), so a figure
reads the same in every language. Hindi uses the polite "aap" form.
"""

from datetime import date

LANGUAGES = ("en", "hi-Latn", "hi")
DEFAULT_LANGUAGE = "en"

_MONTHS = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "hi": (
        "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
        "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
    ),
}  # fmt: skip

# key -> {language: text}. `{amount}`, `{date}`, `{contact}`, `{label}` are filled by code.
TEMPLATES: dict[str, dict[str, str]] = {
    # ---- remedy options (app/engine/remedy_choice.py, S7.9) ----
    "option.voucher.title": {
        "en": "Voucher",
        "hi-Latn": "Voucher",
        "hi": "वाउचर",
    },
    "option.voucher.summary": {
        "en": "A voucher worth {amount} for a future order.",
        "hi-Latn": "Agle order ke liye {amount} ka voucher.",
        "hi": "अगले ऑर्डर के लिए {amount} का वाउचर।",
    },
    "option.refund.title": {
        "en": "Refund",
        "hi-Latn": "Refund",
        "hi": "रिफ़ंड",
    },
    "option.refund.summary": {
        "en": "{amount} back to your original payment method.",
        "hi-Latn": "{amount} aapke original payment tareeke par wapas.",
        "hi": "{amount} आपके मूल भुगतान तरीके पर वापस।",
    },
    "option.timing.instant": {
        "en": "Usually instant.",
        "hi-Latn": "Aam taur par turant.",
        "hi": "आम तौर पर तुरंत।",
    },
    "option.timing.team": {
        "en": "After a team member approves it.",
        "hi-Latn": "Team ke ek sadasya ki manzoori ke baad.",
        "hi": "टीम के एक सदस्य की मंज़ूरी के बाद।",
    },
    # ---- case status (app/engine/case_status.py) ----
    "status.investigating": {
        "en": "We are looking into your order.",
        "hi-Latn": "Hum aapke order ko dekh rahe hain.",
        "hi": "हम आपके ऑर्डर को देख रहे हैं।",
    },
    "status.escalated_team": {
        "en": "A member of our team will look into this.",
        "hi-Latn": "Hamari team ka ek sadasya ise dekhega.",
        "hi": "हमारी टीम का एक सदस्य इसे देखेगा।",
    },
    "status.need_info": {
        "en": "We need a little more information from you.",
        "hi-Latn": "Hamein aapse thodi aur jaankari chahiye.",
        "hi": "हमें आपसे थोड़ी और जानकारी चाहिए।",
    },
    "status.apology_closed": {
        "en": "Sorry about this. We have noted it with the team.",
        "hi-Latn": "Iske liye maafi chahte hain. Humne ise team ke saath note kar liya hai.",
        "hi": "इसके लिए हमें खेद है। हमने इसे टीम के साथ दर्ज कर लिया है।",
    },
    "status.awaiting_approval": {
        "en": "Your request is waiting for a team member's approval.",
        "hi-Latn": "Aapka request team ke ek sadasya ki manzoori ka intezaar kar raha hai.",
        "hi": "आपका अनुरोध टीम के एक सदस्य की मंज़ूरी का इंतज़ार कर रहा है।",
    },
    "status.declined": {
        "en": "Your request was reviewed and not approved.",
        "hi-Latn": "Aapke request ko dekha gaya aur use manzoor nahi kiya gaya.",
        "hi": "आपके अनुरोध की समीक्षा की गई और उसे मंज़ूर नहीं किया गया।",
    },
    "status.needs_check_any": {
        "en": "Your request needs a check by our team. We will update you.",
        "hi-Latn": "Aapke request ko hamari team ko check karna hai. Hum aapko update denge.",
        "hi": "आपके अनुरोध की हमारी टीम द्वारा जाँच ज़रूरी है। हम आपको अपडेट देंगे।",
    },
    "status.needs_check_refund": {
        "en": "Your refund needs a check by our team before it can continue. We will update you.",
        "hi-Latn": "Aapke refund ko aage badhane se pehle hamari team ko check karna hai. "
        "Hum aapko update denge.",
        "hi": "आपके रिफ़ंड को आगे बढ़ाने से पहले हमारी टीम द्वारा जाँच ज़रूरी है। हम आपको अपडेट देंगे।",
    },
    "status.approved_pending": {
        "en": "Approved. We will confirm once it is ready.",
        "hi-Latn": "Manzoor ho gaya hai. Taiyaar hote hi hum confirm karenge.",
        "hi": "मंज़ूर हो गया है। तैयार होते ही हम पुष्टि करेंगे।",
    },
    "status.refund_confirmed": {
        "en": "Your refund of {amount} has been processed by our payment provider.",
        "hi-Latn": "Aapka {amount} ka refund hamare payment provider ne process kar diya hai.",
        "hi": "आपका {amount} का रिफ़ंड हमारे पेमेंट प्रोवाइडर ने प्रोसेस कर दिया है।",
    },
    "status.refund_failed": {
        "en": "We could not complete the refund automatically. "
        "A member of our team will contact you.",
        "hi-Latn": "Hum refund apne aap poora nahi kar paaye. "
        "Hamari team ka ek sadasya aapse sampark karega.",
        "hi": "हम रिफ़ंड अपने आप पूरा नहीं कर पाए। हमारी टीम का एक सदस्य आपसे संपर्क करेगा।",
    },
    "status.refund_processing": {
        "en": "Your refund of {amount} is approved and being processed. "
        "We will confirm once the payment provider does.",
        "hi-Latn": "Aapka {amount} ka refund manzoor ho gaya hai aur process ho raha hai. "
        "Payment provider ke confirm karte hi hum bhi confirm karenge.",
        "hi": "आपका {amount} का रिफ़ंड मंज़ूर हो गया है और प्रोसेस हो रहा है। "
        "पेमेंट प्रोवाइडर के पुष्टि करते ही हम भी पुष्टि करेंगे।",
    },
    "status.voucher_issued": {
        "en": "Your voucher worth {amount} has been issued.",
        "hi-Latn": "Aapka {amount} ka voucher jaari kar diya gaya hai.",
        "hi": "आपका {amount} का वाउचर जारी कर दिया गया है।",
    },
    "status.voucher_failed": {
        "en": "We could not issue the voucher automatically. "
        "A member of our team will contact you.",
        "hi-Latn": "Hum voucher apne aap jaari nahi kar paaye. "
        "Hamari team ka ek sadasya aapse sampark karega.",
        "hi": "हम वाउचर अपने आप जारी नहीं कर पाए। हमारी टीम का एक सदस्य आपसे संपर्क करेगा।",
    },
    "status.voucher_needs_check": {
        "en": "Your voucher needs a check by our team before it can be issued. We will update you.",
        "hi-Latn": "Aapke voucher ko jaari karne se pehle hamari team ko check karna hai. "
        "Hum aapko update denge.",
        "hi": "आपके वाउचर को जारी करने से पहले हमारी टीम द्वारा जाँच ज़रूरी है। हम आपको अपडेट देंगे।",
    },
    "status.voucher_processing": {
        "en": "Your voucher worth {amount} is approved. We will confirm once it has been issued.",
        "hi-Latn": "Aapka {amount} ka voucher manzoor ho gaya hai. "
        "Jaari hote hi hum confirm karenge.",
        "hi": "आपका {amount} का वाउचर मंज़ूर हो गया है। जारी होते ही हम पुष्टि करेंगे।",
    },
    # ---- case timeline (app/engine/case_timeline.py): titles and texts not shared above ----
    "tl.received.title": {
        "en": "Report received",
        "hi-Latn": "Report mil gayi",
        "hi": "रिपोर्ट मिल गई",
    },
    "tl.received.text": {
        "en": "We received your report.",
        "hi-Latn": "Humein aapki report mil gayi hai.",
        "hi": "हमें आपकी रिपोर्ट मिल गई है।",
    },
    "tl.looking.title": {
        "en": "Looking into it",
        "hi-Latn": "Dekh rahe hain",
        "hi": "देख रहे हैं",
    },
    "tl.looking.text": {
        "en": "We started looking into your order.",
        "hi-Latn": "Humne aapke order ko dekhna shuru kar diya hai.",
        "hi": "हमने आपके ऑर्डर को देखना शुरू कर दिया है।",
    },
    "tl.question.title": {
        "en": "Question for you",
        "hi-Latn": "Aapke liye sawaal",
        "hi": "आपके लिए सवाल",
    },
    "tl.question.text": {
        "en": "We asked you for a few more details about this order.",
        "hi-Latn": "Humne aapse is order ke baare mein kuch aur jaankari maangi hai.",
        "hi": "हमने आपसे इस ऑर्डर के बारे में कुछ और जानकारी माँगी है।",
    },
    "tl.replied.title": {
        "en": "You replied",
        "hi-Latn": "Aapne jawab diya",
        "hi": "आपने जवाब दिया",
    },
    "tl.replied.text": {
        "en": "We received your reply.",
        "hi-Latn": "Humein aapka jawab mil gaya hai.",
        "hi": "हमें आपका जवाब मिल गया है।",
    },
    "tl.passed.title": {
        "en": "Passed to our team",
        "hi-Latn": "Hamari team ko bheja gaya",
        "hi": "हमारी टीम को भेजा गया",
    },
    "tl.noted.title": {
        "en": "Noted",
        "hi-Latn": "Note kar liya",
        "hi": "दर्ज किया गया",
    },
    "tl.proposed.title": {
        "en": "Remedy proposed",
        "hi-Latn": "Samaadhaan prastaavit",
        "hi": "समाधान प्रस्तावित",
    },
    "tl.proposed.text": {
        "en": "We proposed {remedy}.",
        "hi-Latn": "Humne {remedy} prastaavit kiya.",
        "hi": "हमने {remedy} प्रस्तावित किया।",
    },
    "tl.declined.title": {
        "en": "Not approved",
        "hi-Latn": "Manzoor nahi hua",
        "hi": "मंज़ूर नहीं हुआ",
    },
    "tl.approved.title": {
        "en": "Approved",
        "hi-Latn": "Manzoor",
        "hi": "मंज़ूर",
    },
    "tl.approved.auto": {
        "en": "Approved automatically under the business's rules.",
        "hi-Latn": "Business ke niyamon ke tahat apne aap manzoor kiya gaya.",
        "hi": "बिज़नेस के नियमों के तहत अपने आप मंज़ूर किया गया।",
    },
    "tl.approved.team": {
        "en": "Your request was approved by our team.",
        "hi-Latn": "Aapke request ko hamari team ne manzoor kiya.",
        "hi": "आपके अनुरोध को हमारी टीम ने मंज़ूर किया।",
    },
    "tl.refund_confirmed.title": {
        "en": "Refund confirmed",
        "hi-Latn": "Refund ki pushti",
        "hi": "रिफ़ंड की पुष्टि",
    },
    "tl.refund_check.text": {
        "en": "Your refund needs a check by our team before it can continue.",
        "hi-Latn": "Aapke refund ko aage badhane se pehle hamari team ko check karna hai.",
        "hi": "आपके रिफ़ंड को आगे बढ़ाने से पहले हमारी टीम द्वारा जाँच ज़रूरी है।",
    },
    "tl.voucher_issued.title": {
        "en": "Voucher issued",
        "hi-Latn": "Voucher jaari",
        "hi": "वाउचर जारी",
    },
    "tl.voucher_check.text": {
        "en": "Your voucher needs a check by our team before it can be issued.",
        "hi-Latn": "Aapke voucher ko jaari karne se pehle hamari team ko check karna hai.",
        "hi": "आपके वाउचर को जारी करने से पहले हमारी टीम द्वारा जाँच ज़रूरी है।",
    },
    # what a remedy is called inside "We proposed {remedy}."
    "remedy.refund": {
        "en": "a refund of {amount}",
        "hi-Latn": "{amount} ka refund",
        "hi": "{amount} का रिफ़ंड",
    },
    "remedy.free_item_voucher": {
        "en": "a free item voucher of {amount}",
        "hi-Latn": "{amount} ka free item voucher",
        "hi": "{amount} का फ़्री आइटम वाउचर",
    },
    "remedy.loyalty_credit": {
        "en": "a loyalty credit of {amount}",
        "hi-Latn": "{amount} ka loyalty credit",
        "hi": "{amount} का लॉयल्टी क्रेडिट",
    },
    "remedy.other_amount": {
        "en": "a {label} of {amount}",
        "hi-Latn": "{amount} ka {label}",
        "hi": "{amount} का {label}",
    },
    "remedy.other": {
        "en": "a {label}",
        "hi-Latn": "ek {label}",
        "hi": "एक {label}",
    },
    # ---- what we ask a customer (app/engine/needs.py) ----
    "need.order": {
        "en": "Which order is this about? Please pick it from your order list.",
        "hi-Latn": "Yeh kaun se order ke baare mein hai? Kripya apni order list se chuniye.",
        "hi": "यह किस ऑर्डर के बारे में है? कृपया अपनी ऑर्डर सूची से चुनें।",
    },
    "need.details": {
        "en": "So we can look into it, could you tell us a bit more about what went wrong"
        " with your order (for example, which item was affected)?",
        "hi-Latn": "Hum ise dekh sakein, isliye kya aap bata sakte hain ki aapke order mein"
        " kya galat hua (jaise, kaun sa item prabhavit hua)?",
        "hi": "हम इसे देख सकें, इसलिए क्या आप बता सकते हैं कि आपके ऑर्डर में क्या गलत हुआ"
        " (जैसे, कौन सा आइटम प्रभावित हुआ)?",
    },
    "need.generic": {
        "en": "Could you tell us a bit more about what went wrong with this order?",
        "hi-Latn": "Kya aap bata sakte hain ki is order mein kya galat hua?",
        "hi": "क्या आप बता सकते हैं कि इस ऑर्डर में क्या गलत हुआ?",
    },
    # ---- privacy request (app/engine/privacy.py) ----
    "privacy.received": {
        "en": "We have received your privacy request and passed it to a member of our team.",
        "hi-Latn": "Humein aapki privacy request mil gayi hai aur humne ise apni team ke "
        "ek sadasya ko bhej diya hai.",
        "hi": "हमें आपका प्राइवेसी अनुरोध मिल गया है और हमने इसे अपनी टीम के एक सदस्य को भेज दिया है।",
    },
    "privacy.reach": {
        "en": "You can also reach our privacy contact: {contact}.",
        "hi-Latn": "Aap hamare privacy contact se bhi sampark kar sakte hain: {contact}.",
        "hi": "आप हमारे प्राइवेसी संपर्क से भी संपर्क कर सकते हैं: {contact}।",
    },
    "privacy.target": {
        "en": "Our internal target is to respond by {date}.",
        "hi-Latn": "Hamara aantarik lakshya {date} tak jawab dene ka hai.",
        "hi": "हमारा आंतरिक लक्ष्य {date} तक जवाब देने का है।",
    },
    # ---- staff replies and closing (app/engine/staff_actions.py, S7.6) ----
    # Hinglish and Devanagari copy is plain and awaits native review (docs/DECISIONS.md).
    "staff.looking_into": {
        "en": "We are looking into this and will update you.",
        "hi-Latn": "Hum ise dekh rahe hain aur aapko update denge.",
        "hi": "हम इसे देख रहे हैं और आपको अपडेट देंगे।",
    },
    "staff.share_photo": {
        "en": "Please share a photo of the item so we can check it.",
        "hi-Latn": "Kripya item ki ek photo bhejiye taaki hum ise check kar sakein.",
        "hi": "कृपया आइटम की एक फ़ोटो भेजें ताकि हम उसे जाँच सकें।",
    },
    "staff.passed_to_outlet": {
        "en": "We have passed this to the outlet.",
        "hi-Latn": "Humne ise outlet ko bhej diya hai.",
        "hi": "हमने इसे आउटलेट को भेज दिया है।",
    },
    # Offered only while an approved refund is really being processed; the amount is filled
    # by code from the proposal, never typed by staff.
    "staff.refund_processing": {
        "en": "Your refund of {amount} is approved and being processed. "
        "We will confirm once the payment provider does.",
        "hi-Latn": "Aapka {amount} ka refund manzoor ho gaya hai aur process ho raha hai. "
        "Payment provider ke confirm karte hi hum bhi confirm karenge.",
        "hi": "आपका {amount} का रिफ़ंड मंज़ूर हो गया है और प्रोसेस हो रहा है। "
        "पेमेंट प्रोवाइडर के पुष्टि करते ही हम भी पुष्टि करेंगे।",
    },
    "tl.staff.title": {
        "en": "Message from our team",
        "hi-Latn": "Hamari team ka sandesh",
        "hi": "हमारी टीम का संदेश",
    },
    "tl.staff_note.title": {
        "en": "From our team",
        "hi-Latn": "Hamari team ki taraf se",
        "hi": "हमारी टीम की ओर से",
    },
    "tl.closed.title": {
        "en": "Case closed",
        "hi-Latn": "Case band kiya gaya",
        "hi": "केस बंद किया गया",
    },
    "close.resolved": {
        "en": "We have closed this case as resolved.",
        "hi-Latn": "Humne is case ko suljha hua maan kar band kar diya hai.",
        "hi": "हमने इस केस को सुलझा हुआ मानकर बंद कर दिया है।",
    },
    "close.no_remedy": {
        "en": "We reviewed this case and closed it. No remedy is due on this order.",
        "hi-Latn": "Humne is case ki jaanch ki aur ise band kar diya. "
        "Is order par koi muaavza dena nahi banta.",
        "hi": "हमने इस केस की जाँच की और इसे बंद कर दिया। इस ऑर्डर पर कोई मुआवज़ा देय नहीं है।",
    },
    "close.duplicate": {
        "en": "We have closed this case because it repeats another report of yours.",
        "hi-Latn": "Humne is case ko band kar diya hai kyunki yeh aapki ek aur report "
        "jaisa hi hai.",
        "hi": "हमने इस केस को बंद कर दिया है क्योंकि यह आपकी एक और रिपोर्ट जैसा ही है।",
    },
    "close.unreachable": {
        "en": "We could not reach you, so we have closed this case. "
        "You can report the problem again any time.",
        "hi-Latn": "Hum aapse sampark nahi kar paaye, isliye humne yeh case band kar diya hai. "
        "Aap kabhi bhi problem dobara report kar sakte hain.",
        "hi": "हम आपसे संपर्क नहीं कर पाए, इसलिए हमने यह केस बंद कर दिया है। "
        "आप कभी भी समस्या दोबारा बता सकते हैं।",
    },
}

# The five money states a customer can be told, each mapped to its own template (hard rule 7:
# submitted / processing / succeeded / failed / unknown must never read as the same thing).
MONEY_STATUS_KEYS = {
    "submitted": "status.awaiting_approval",
    "processing": "status.refund_processing",
    "succeeded": "status.refund_confirmed",
    "failed": "status.refund_failed",
    "unknown": "status.needs_check_refund",
}


def normalize(language: object) -> str:
    """A supported code, else the default (an unknown or missing value never errors)."""
    return language if isinstance(language, str) and language in LANGUAGES else DEFAULT_LANGUAGE


def t(key: str, language: object = None, **params: object) -> str:
    """The text for `key` in `language`, English if that translation is missing.
    An unknown key is a bug and raises."""
    variants = TEMPLATES[key]
    text = variants.get(normalize(language)) or variants[DEFAULT_LANGUAGE]
    return text.format(**params) if params else text


def format_date(d: date, language: object = None) -> str:
    """`27 Oct 2026` / `27 अक्टूबर 2026`: a month name, never 10/11."""
    months = _MONTHS["hi"] if normalize(language) == "hi" else _MONTHS["en"]
    return f"{d.day} {months[d.month - 1]} {d.year}"


def case_language(session, case) -> str:
    """The language of a case's customer messages: the language detected from what the customer
    wrote (cases.language, S7.12), else the customer's older stored choice as the initial
    default, else English."""
    from sqlalchemy import select

    from app.core.models import Customer

    if getattr(case, "language", None) in LANGUAGES:
        return case.language
    if case.customer_id is None:
        return DEFAULT_LANGUAGE
    return normalize(
        session.scalar(select(Customer.preferred_language).where(Customer.id == case.customer_id))
    )
