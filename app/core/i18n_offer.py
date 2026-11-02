"""Customer text for "ask the customer" (S8.10), merged into app/core/i18n.TEMPLATES.

Kept in its own module so the big template file stays free of merge conflicts. The wording says
plainly that this is a choice and that a team member reviews it: no promise of payment, and no
"issued" or "processed" language (hard rule 7). Hindi lines (hi) are drafts: OWNER TO CONFIRM with
a native reviewer before launch (docs/DECISIONS.md).
"""

OFFER_TEMPLATES: dict[str, dict[str, str]] = {
    "basis.customer_chose": {
        "en": "The customer chose this option when a team member asked.",
        "hi-Latn": "Team ke sadasya ke poochhne par customer ne yeh vikalp chuna.",
        "hi": "टीम के सदस्य के पूछने पर ग्राहक ने यह विकल्प चुना।",
    },
    "offer.heading": {
        "en": "Please choose an option",
        "hi-Latn": "Kripya ek vikalp chuniye",
        "hi": "कृपया एक विकल्प चुनिए",
    },
    "offer.intro": {
        "en": (
            "Our team has two options for you. This is a choice, not a promise: pick the one you "
            "prefer, and a team member will review it before anything is decided."
        ),
        "hi-Latn": (
            "Hamari team ke paas aapke liye do vikalp hain. Yeh ek choice hai, vaada nahi: jo "
            "pasand ho woh chuniye, aur kuch bhi tay hone se pehle team ka ek sadasya ise dekhega."
        ),
        "hi": (
            "हमारी टीम के पास आपके लिए दो विकल्प हैं। यह एक चुनाव है, वादा नहीं: जो पसंद हो वह "
            "चुनिए, और कुछ भी तय होने से पहले टीम का एक सदस्य इसे देखेगा।"
        ),
    },
    "offer.expires": {
        "en": (
            "Please answer within {days} days. If we do not hear from you, a team member "
            "will still look at your case."
        ),
        "hi-Latn": (
            "Kripya {days} din ke andar jawab dijiye. Jawab na aane par bhi team ka ek sadasya "
            "aapke case ko dekhega."
        ),
        "hi": ("कृपया {days} दिन के अंदर जवाब दीजिए। जवाब न आने पर भी टीम का एक सदस्य आपके केस को देखेगा।"),
    },
    "offer.status.waiting": {
        "en": "We are waiting for your choice between two options.",
        "hi-Latn": "Hum do vikalpon mein se aapki choice ka intezaar kar rahe hain.",
        "hi": "हम दो विकल्पों में से आपके चुनाव का इंतज़ार कर रहे हैं।",
    },
    "offer.status.chosen": {
        "en": (
            "Thank you. We have your choice. A team member will review it. Nothing is decided yet."
        ),
        "hi-Latn": (
            "Shukriya. Humein aapki choice mil gayi hai. Team ka ek sadasya ise dekhega. "
            "Abhi kuch tay nahi hua hai."
        ),
        "hi": ("धन्यवाद। हमें आपका चुनाव मिल गया है। टीम का एक सदस्य इसे देखेगा। अभी कुछ तय नहीं हुआ है।"),
    },
    "offer.status.review": {
        "en": "Thank you. A team member will look at your case first. Nothing is decided yet.",
        "hi-Latn": (
            "Shukriya. Team ka ek sadasya pehle aapke case ko dekhega. Abhi kuch tay nahi hua hai."
        ),
        "hi": "धन्यवाद। टीम का एक सदस्य पहले आपके केस को देखेगा। अभी कुछ तय नहीं हुआ है।",
    },
    "offer.status.expired": {
        "en": "We did not hear back, so a team member will look at your case.",
        "hi-Latn": "Jawab nahi aaya, isliye team ka ek sadasya aapke case ko dekhega.",
        "hi": "जवाब नहीं आया, इसलिए टीम का एक सदस्य आपके केस को देखेगा।",
    },
}
