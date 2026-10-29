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
        "en": "Ask for a refund",
        "hi-Latn": "Refund ke liye request",
        "hi": "रिफ़ंड का अनुरोध",
    },
    "option.refund.summary": {
        "en": "You can ask for a partial refund of up to {amount}; a team member decides.",
        "hi-Latn": (
            "Aap {amount} tak ke partial refund ke liye keh sakte hain; "
            "team ka ek sadasya faisla karta hai."
        ),
        "hi": "आप {amount} तक के आंशिक रिफ़ंड के लिए अनुरोध कर सकते हैं; टीम का एक सदस्य निर्णय लेता है।",
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
    # ---- what we hold (S8.5a). Hindi copy awaits native review (docs/DECISIONS.md).
    "held.label.name": {
        "en": "Your name",
        "hi-Latn": "Aapka naam",
        "hi": "आपका नाम",
    },
    "held.purpose.name": {
        "en": "So we know who we are helping.",
        "hi-Latn": "Taaki hum jaan sakein ki hum kiski madad kar rahe hain.",
        "hi": "ताकि हम जान सकें कि हम किसकी मदद कर रहे हैं।",
    },
    "held.label.phone": {
        "en": "Your phone number",
        "hi-Latn": "Aapka phone number",
        "hi": "आपका फ़ोन नंबर",
    },
    "held.purpose.phone": {
        "en": "To reach you about your orders and cases.",
        "hi-Latn": "Aapke orders aur cases ke bare mein aapse sampark karne ke liye.",
        "hi": "आपके ऑर्डर और मामलों के बारे में आपसे संपर्क करने के लिए।",
    },
    "held.label.email": {
        "en": "Your email",
        "hi-Latn": "Aapka email",
        "hi": "आपका ईमेल",
    },
    "held.purpose.email": {
        "en": "To reach you about your orders and cases.",
        "hi-Latn": "Aapke orders aur cases ke bare mein aapse sampark karne ke liye.",
        "hi": "आपके ऑर्डर और मामलों के बारे में आपसे संपर्क करने के लिए।",
    },
    "held.label.orders": {
        "en": "Your orders",
        "hi-Latn": "Aapke orders",
        "hi": "आपके ऑर्डर",
    },
    "held.purpose.orders": {
        "en": "To show what you bought and to check your complaints.",
        "hi-Latn": "Yeh dikhane ke liye ki aapne kya kharida aur aapki shikayat jaanchne ke liye.",
        "hi": "यह दिखाने के लिए कि आपने क्या खरीदा और आपकी शिकायतें जाँचने के लिए।",
    },
    "held.label.messages": {
        "en": "Your support messages",
        "hi-Latn": "Aapke support messages",
        "hi": "आपके सहायता संदेश",
    },
    "held.purpose.messages": {
        "en": "To resolve your cases and keep a record of what we said.",
        "hi-Latn": "Aapke cases suljhane aur humne kya kaha uska record rakhne ke liye.",
        "hi": "आपके मामले सुलझाने और हमने क्या कहा इसका रिकॉर्ड रखने के लिए।",
    },
    "held.label.payments": {
        "en": "Your payment references",
        "hi-Latn": "Aapke payment references",
        "hi": "आपके भुगतान संदर्भ",
    },
    "held.purpose.payments": {
        "en": "To match refunds to what you paid. We hold references, not card numbers.",
        "hi-Latn": "Refund ko aapke payment se milane ke liye. Hum references rakhte "
        "hain, card number nahin.",
        "hi": "रिफ़ंड को आपके भुगतान से मिलाने के लिए। हम संदर्भ रखते हैं, कार्ड नंबर नहीं।",
    },
    "held.label.remedies": {
        "en": "Your refund and voucher records",
        "hi-Latn": "Aapke refund aur voucher records",
        "hi": "आपके रिफ़ंड और वाउचर रिकॉर्ड",
    },
    "held.purpose.remedies": {
        "en": "To show what we offered or paid you, and to stop double payments.",
        "hi-Latn": "Humne aapko kya diya ya offer kiya yeh dikhane aur double payment "
        "rokne ke liye.",
        "hi": "हमने आपको क्या दिया या ऑफ़र किया यह दिखाने और दोहरा भुगतान रोकने के लिए।",
    },
    "held.label.consents": {
        "en": "Your offer choices",
        "hi-Latn": "Aapke offers ke choices",
        "hi": "आपके ऑफ़र संबंधी विकल्प",
    },
    "held.purpose.consents": {
        "en": "To follow your choice about offers and prove it.",
        "hi-Latn": "Offers ke bare mein aapka choice maanne aur uska saboot rakhne ke liye.",
        "hi": "ऑफ़र के बारे में आपकी पसंद मानने और उसका प्रमाण रखने के लिए।",
    },
    "held.use.help": {
        "en": "Help with your orders",
        "hi-Latn": "Aapke orders mein madad",
        "hi": "आपके ऑर्डर में मदद",
    },
    "held.use.marketing": {
        "en": "Offers, only if you agree",
        "hi-Latn": "Offers, sirf aapki sahmati se",
        "hi": "ऑफ़र, केवल आपकी सहमति से",
    },
    "held.ret.messages": {
        "en": "Message text may be removed {days} days after a case closes, if nothing is "
        "still being settled and it is not on hold.",
        "hi-Latn": "Case band hone ke {days} din baad message text hata diya ja sakta hai, "
        "agar kuch settle hona baaki na ho aur case hold par na ho.",
        "hi": "मामला बंद होने के {days} दिन बाद संदेश का पाठ हटाया जा सकता है, यदि कुछ भी "
        "निपटना बाकी न हो और मामला रोका न गया हो।",
    },
    "held.ret.contact": {
        "en": "Kept while you have an account, until you ask us to erase it.",
        "hi-Latn": "Jab tak aapka account hai tab tak rakha jaata hai, "
        "jab tak aap hatane ko na kahein.",
        "hi": "जब तक आपका खाता है तब तक रखा जाता है, जब तक आप हटाने को न कहें।",
    },
    "held.contact.unset": {
        "en": "Not set yet.",
        "hi-Latn": "Abhi tay nahin hua.",
        "hi": "अभी तय नहीं हुआ।",
    },
    "held.ret.records": {
        "en": "Kept {years} years, as business records.",
        "hi-Latn": "{years} saal tak rakha jaata hai, business record ke roop mein.",
        "hi": "व्यवसाय रिकॉर्ड के रूप में {years} साल तक रखा जाता है।",
    },
    "held.ret.consents": {
        "en": "Kept as proof of your choices.",
        "hi-Latn": "Aapke choices ke saboot ke roop mein rakha jaata hai.",
        "hi": "आपकी पसंद के प्रमाण के रूप में रखा जाता है।",
    },
    "held.provisional": {
        "en": "provisional",
        "hi-Latn": "abhi tay nahin",
        "hi": "अभी अंतिम नहीं",
    },
    "held.count": {
        "en": "{n} on record",
        "hi-Latn": "{n} record mein",
        "hi": "{n} रिकॉर्ड में",
    },
    "held.not_kept.card_numbers": {
        "en": "We do not keep your card numbers.",
        "hi-Latn": "Hum aapke card number nahin rakhte.",
        "hi": "हम आपके कार्ड नंबर नहीं रखते।",
    },
    "held.not_kept.upi_details": {
        "en": "We do not keep your UPI details.",
        "hi-Latn": "Hum aapke UPI details nahin rakhte.",
        "hi": "हम आपके UPI विवरण नहीं रखते।",
    },
    "held.contact.label": {
        "en": "Privacy contact",
        "hi-Latn": "Privacy contact",
        "hi": "प्राइवेसी संपर्क",
    },
    "held.contact.target": {
        "en": "We aim to reply within {days} days. The legal limit is {ceiling} days.",
        "hi-Latn": "Hum {days} din ke andar jawab dene ka lakshya rakhte hain. Kanooni "
        "seema {ceiling} din hai.",
        "hi": "हम {days} दिन के भीतर जवाब देने का लक्ष्य रखते हैं। कानूनी सीमा {ceiling} दिन है।",
    },
    "held.h.title": {
        "en": "What we hold about you",
        "hi-Latn": "Hum aapke bare mein kya rakhte hain",
        "hi": "हम आपके बारे में क्या रखते हैं",
    },
    "held.h.item": {
        "en": "Item",
        "hi-Latn": "Cheez",
        "hi": "विवरण",
    },
    "held.h.yours": {
        "en": "What we hold",
        "hi-Latn": "Humare paas kya hai",
        "hi": "हमारे पास क्या है",
    },
    "held.h.purpose": {
        "en": "Why",
        "hi-Latn": "Kyon",
        "hi": "क्यों",
    },
    "held.h.keep": {
        "en": "How long",
        "hi-Latn": "Kitne samay tak",
        "hi": "कितने समय तक",
    },
    "held.h.use": {
        "en": "Used for",
        "hi-Latn": "Kis kaam mein",
        "hi": "किस काम में",
    },
    "held.h.processors": {
        "en": "Who else sees it",
        "hi-Latn": "Aur kaun dekhta hai",
        "hi": "और कौन देखता है",
    },
    "held.h.not_kept": {
        "en": "What we do not keep",
        "hi-Latn": "Hum kya nahin rakhte",
        "hi": "हम क्या नहीं रखते",
    },
    "held.h.contact": {
        "en": "Questions about your data",
        "hi-Latn": "Aapke data ke bare mein sawal",
        "hi": "आपके डेटा के बारे में सवाल",
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
    # ---- plain-language rules summary (app/engine/rules_summary.py, S8.2) ----
    # Hindi lines (hi) are drafts: OWNER TO CONFIRM with a native reviewer before launch.
    "rules.voucher.order": {
        "en": "A voucher up to the value of your order, at most {amount}.",
        "hi-Latn": "Aapke order ki value tak ka voucher, adhiktam {amount}.",
        "hi": "आपके ऑर्डर की क़ीमत तक का वाउचर, अधिकतम {amount}।",
    },
    "rules.voucher.percent": {
        "en": "A voucher up to {percent}% of your order, at most {amount}.",
        "hi-Latn": "Aapke order ke {percent}% tak ka voucher, adhiktam {amount}.",
        "hi": "आपके ऑर्डर के {percent}% तक का वाउचर, अधिकतम {amount}।",
    },
    "rules.refund.percent": {
        "en": "A refund of up to {percent}% of your order, never more than you paid.",
        "hi-Latn": (
            "Aapke order ke {percent}% tak ka refund, aapke diye hue paise se zyada kabhi nahi."
        ),
        "hi": "आपके ऑर्डर के {percent}% तक का रिफ़ंड, आपके चुकाए पैसों से ज़्यादा कभी नहीं।",
    },
    "rules.refund.missing": {
        "en": "A refund for the items that did not arrive, up to {percent}% of your order.",
        "hi-Latn": "Jo items nahi pahunche unka refund, aapke order ke {percent}% tak.",
        "hi": "जो आइटम नहीं पहुँचे उनका रिफ़ंड, आपके ऑर्डर के {percent}% तक।",
    },
    "rules.apology": {
        "en": "We apologise and note it with the team.",
        "hi-Latn": "Hum maafi chahte hain aur team ko bata dete hain.",
        "hi": "हम क्षमा चाहते हैं और टीम को बता देते हैं।",
    },
    "rules.tier.label": {
        "en": "{minutes} minutes late or more",
        "hi-Latn": "{minutes} minute ya usse zyada late",
        "hi": "{minutes} मिनट या उससे ज़्यादा देरी",
    },
    "rules.late.excluded": {
        "en": (
            "No remedy applies when the delay was caused on your side, for example a wrong address."
        ),
        "hi-Latn": "Agar deri aapki taraf se hui, jaise galat pata, to koi remedy nahi milta.",
        "hi": "यदि देरी आपकी तरफ़ से हुई, जैसे ग़लत पता, तो कोई उपाय लागू नहीं होता।",
    },
    "rules.escalate": {
        "en": "A team member looks at your case and decides what is fair.",
        "hi-Latn": "Team ka ek sadasya aapka case dekhta hai aur tay karta hai ki kya uchit hai.",
        "hi": "टीम का एक सदस्य आपका केस देखता है और तय करता है कि क्या उचित है।",
    },
    "rules.privacy": {
        "en": "A team member handles privacy requests. They are never settled with a payout.",
        "hi-Latn": (
            "Privacy requests team ka ek sadasya sambhalta hai. Inka hal kabhi payout se nahi hota."
        ),
        "hi": "गोपनीयता अनुरोध टीम का एक सदस्य संभालता है। इनका समाधान कभी भुगतान से नहीं होता।",
    },
    "rules.fair_use": {
        "en": (
            "If you already had {count} refunds or vouchers in the last 30 days, "
            "a team member decides instead."
        ),
        "hi-Latn": (
            "Agar pichhle 30 din mein aapko pehle se {count} refund ya voucher mil chuke hain, "
            "to team ka ek sadasya faisla karta hai."
        ),
        "hi": (
            "यदि पिछले 30 दिनों में आपको पहले से {count} रिफ़ंड या वाउचर मिल चुके हैं, "
            "तो टीम का एक सदस्य निर्णय लेता है।"
        ),
    },
    "rules.in_force": {
        "en": "These rules have been in force since {date}.",
        "hi-Latn": "Ye niyam {date} se lagu hain.",
        "hi": "ये नियम {date} से लागू हैं।",
    },
    "rules.category.late_delivery": {
        "en": "Your order is late",
        "hi-Latn": "Aapka order late hai",
        "hi": "आपका ऑर्डर देर से आया",
    },
    "rules.category.missing_items": {
        "en": "Items are missing",
        "hi-Latn": "Items kam hain",
        "hi": "आइटम कम हैं",
    },
    "rules.category.wrong_item": {
        "en": "You got the wrong item",
        "hi-Latn": "Galat item mila",
        "hi": "ग़लत आइटम मिला",
    },
    "rules.category.wrong_order": {
        "en": "You got the wrong order",
        "hi-Latn": "Galat order mila",
        "hi": "ग़लत ऑर्डर मिला",
    },
    "rules.category.food_quality": {
        "en": "The food quality was poor",
        "hi-Latn": "Khane ki quality achhi nahi thi",
        "hi": "खाने की गुणवत्ता ठीक नहीं थी",
    },
    "rules.category.quality": {
        "en": "The quality was poor",
        "hi-Latn": "Quality achhi nahi thi",
        "hi": "गुणवत्ता ठीक नहीं थी",
    },
    "rules.category.payment_issue": {
        "en": "There is a payment problem",
        "hi-Latn": "Payment mein problem hai",
        "hi": "भुगतान में समस्या है",
    },
    "rules.category.status_question": {
        "en": "You want to know where your order is",
        "hi-Latn": "Aap jaanna chahte hain ki order kahan hai",
        "hi": "आप जानना चाहते हैं कि ऑर्डर कहाँ है",
    },
    "rules.category.privacy_request": {
        "en": "You have a privacy request",
        "hi-Latn": "Aapki privacy request hai",
        "hi": "आपका गोपनीयता अनुरोध है",
    },
    "rules.category.loyalty": {
        "en": "A loyalty question",
        "hi-Latn": "Loyalty ka sawaal",
        "hi": "लॉयल्टी से जुड़ा सवाल",
    },
    # ---- why a remedy has this amount (app/api/decision_sources.py, S8.3) ----
    "basis.voucher_order_total": {
        "en": "The voucher is sized to the order total.",
        "hi-Latn": "Voucher ki value aapke order ke total ke hisaab se rakhi gayi hai.",
        "hi": "वाउचर की राशि आपके ऑर्डर के कुल के हिसाब से रखी गई है।",
    },
    "basis.voucher_order_percent": {
        "en": "The voucher is {percent}% of the order total.",
        "hi-Latn": "Voucher order ke total ka {percent}% hai.",
        "hi": "वाउचर ऑर्डर के कुल का {percent}% है।",
    },
    "basis.voucher_cap": {
        "en": "The voucher is capped at {cap} by the voucher limit.",
        "hi-Latn": "Voucher ki value voucher limit ke hisaab se {cap} par roki gayi hai.",
        "hi": "वाउचर की राशि वाउचर सीमा के अनुसार {cap} पर सीमित है।",
    },
    "basis.late_tier": {
        "en": "The order was {minutes} minutes late, which reached the late-delivery tier "
        "for {tier} minutes or more.",
        "hi-Latn": "Order {minutes} minute late tha, jo {tier} minute ya usse zyada ke "
        "late-delivery tier tak pahunchta hai.",
        "hi": "ऑर्डर {minutes} मिनट देर से आया, जो {tier} मिनट या उससे अधिक के देरी-स्तर तक पहुँचता है।",
    },
    "basis.refund_percent": {
        "en": "The refund is {percent}% of the order total.",
        "hi-Latn": "Refund order ke total ka {percent}% hai.",
        "hi": "रिफ़ंड ऑर्डर के कुल का {percent}% है।",
    },
    "basis.refund_choice": {
        "en": "The refund is {percent}% of the order total, the option that was chosen.",
        "hi-Latn": "Refund order ke total ka {percent}% hai, jo vikalp chuna gaya tha.",
        "hi": "रिफ़ंड ऑर्डर के कुल का {percent}% है, जो विकल्प चुना गया था।",
    },
    "basis.capped_refundable": {
        "en": "It is limited to what is still refundable on this order.",
        "hi-Latn": "Yeh is order par abhi bacha refund-yogya hissa tak seemit hai.",
        "hi": "यह इस ऑर्डर पर अभी शेष रिफ़ंड योग्य राशि तक सीमित है।",
    },
    "basis.refund_missing": {
        "en": "The refund is the price of the items missing from the order.",
        "hi-Latn": "Refund order se gayab items ki keemat ke barabar hai.",
        "hi": "रिफ़ंड ऑर्डर से गायब आइटमों की कीमत के बराबर है।",
    },
    "basis.refund_missing_capped": {
        "en": "It is limited by the refund rule or what is still refundable.",
        "hi-Latn": "Yeh refund niyam ya bache refund-yogya hisse se seemit hai.",
        "hi": "यह रिफ़ंड नियम या शेष रिफ़ंड योग्य राशि से सीमित है।",
    },
    "basis.approver_set": {
        "en": "A team member set this amount.",
        "hi-Latn": "Yeh raashi team ke ek sadasya ne tay ki.",
        "hi": "यह राशि टीम के एक सदस्य ने तय की।",
    },
    "source.version_changed": {
        "en": "This policy has changed since the decision; the link shows the current wording.",
        "hi-Latn": "Faisle ke baad yeh policy badal gayi hai; link mein abhi ka text dikhta hai.",
        "hi": "निर्णय के बाद यह नीति बदल गई है; लिंक में अभी का पाठ दिखता है।",
    },
    "source.changed": {
        "en": "This section has changed since the decision; the document is linked instead.",
        "hi-Latn": "Faisle ke baad yeh section badal gaya hai; uski jagah document ka link hai.",
        "hi": "निर्णय के बाद यह भाग बदल गया है; इसकी जगह दस्तावेज़ का लिंक दिया गया है।",
    },
    # ---- readable data export (S8.5c). Hindi copy awaits native review (docs/DECISIONS.md).
    "export.title": {
        "en": "Your data, in a readable form",
        "hi-Latn": "Aapka data, padhne laayak roop mein",
        "hi": "आपका डेटा, पढ़ने योग्य रूप में",
    },
    "export.generated": {
        "en": "Prepared on {date}",
        "hi-Latn": "{date} ko taiyaar kiya gaya",
        "hi": "{date} को तैयार किया गया",
    },
    "export.tz_note": {
        "en": "Dates and times are in Indian Standard Time.",
        "hi-Latn": "Tareekh aur samay Bharatiya Manak Samay mein hain.",
        "hi": "तारीख़ और समय भारतीय मानक समय में हैं।",
    },
    "export.why": {
        "en": "Why we hold it",
        "hi-Latn": "Hum ise kyon rakhte hain",
        "hi": "हम इसे क्यों रखते हैं",
    },
    "export.howlong": {
        "en": "How long we keep it",
        "hi-Latn": "Hum ise kitne samay tak rakhte hain",
        "hi": "हम इसे कितने समय तक रखते हैं",
    },
    "export.empty": {
        "en": "Nothing on record.",
        "hi-Latn": "Kuch record mein nahin hai.",
        "hi": "रिकॉर्ड में कुछ नहीं है।",
    },
    "export.s.details": {
        "en": "Your details",
        "hi-Latn": "Aapki jaankari",
        "hi": "आपकी जानकारी",
    },
    "export.s.orders": {
        "en": "Your orders",
        "hi-Latn": "Aapke orders",
        "hi": "आपके ऑर्डर",
    },
    "export.s.cases": {
        "en": "Your help requests",
        "hi-Latn": "Aapke madad ke anurodh",
        "hi": "आपके सहायता अनुरोध",
    },
    "export.s.remedies": {
        "en": "Refunds and vouchers",
        "hi-Latn": "Refund aur voucher",
        "hi": "रिफ़ंड और वाउचर",
    },
    "export.s.choices": {
        "en": "Your choices about offers",
        "hi-Latn": "Offers ke bare mein aapke choices",
        "hi": "ऑफ़र के बारे में आपकी पसंद",
    },
    "export.s.processors": {
        "en": "Companies that handle data for us",
        "hi-Latn": "Hamare liye data sanbhalne wali companies",
        "hi": "हमारे लिए डेटा संभालने वाली कंपनियाँ",
    },
    "export.f.name": {
        "en": "Name",
        "hi-Latn": "Naam",
        "hi": "नाम",
    },
    "export.f.phone": {
        "en": "Phone",
        "hi-Latn": "Phone",
        "hi": "फ़ोन",
    },
    "export.f.email": {
        "en": "Email",
        "hi-Latn": "Email",
        "hi": "ईमेल",
    },
    "export.f.reference": {
        "en": "Your customer reference",
        "hi-Latn": "Aapka customer reference",
        "hi": "आपका ग्राहक संदर्भ",
    },
    "export.f.order": {
        "en": "Order",
        "hi-Latn": "Order",
        "hi": "ऑर्डर",
    },
    "export.f.placed": {
        "en": "Placed on",
        "hi-Latn": "Kab diya gaya",
        "hi": "कब दिया गया",
    },
    "export.f.brand": {
        "en": "Brand",
        "hi-Latn": "Brand",
        "hi": "ब्रांड",
    },
    "export.f.place": {
        "en": "Outlet",
        "hi-Latn": "Outlet",
        "hi": "आउटलेट",
    },
    "export.f.total": {
        "en": "Total",
        "hi-Latn": "Kul",
        "hi": "कुल",
    },
    "export.f.status": {
        "en": "Status",
        "hi-Latn": "Sthiti",
        "hi": "स्थिति",
    },
    "export.f.topic": {
        "en": "About",
        "hi-Latn": "Vishay",
        "hi": "विषय",
    },
    "export.f.opened": {
        "en": "Opened on",
        "hi-Latn": "Kab shuru hua",
        "hi": "कब शुरू हुआ",
    },
    "export.f.update": {
        "en": "Latest update",
        "hi-Latn": "Taaza update",
        "hi": "ताज़ा अपडेट",
    },
    "export.f.remedy": {
        "en": "Type",
        "hi-Latn": "Prakar",
        "hi": "प्रकार",
    },
    "export.f.amount": {
        "en": "Amount",
        "hi-Latn": "Raashi",
        "hi": "राशि",
    },
    "export.f.choice": {
        "en": "Choice",
        "hi-Latn": "Choice",
        "hi": "पसंद",
    },
    "export.f.channel": {
        "en": "Channel",
        "hi-Latn": "Channel",
        "hi": "माध्यम",
    },
    "export.f.on": {
        "en": "Agreed to offers",
        "hi-Latn": "Offers ke liye haan kaha",
        "hi": "ऑफ़र के लिए हाँ कहा",
    },
    "export.f.off": {
        "en": "Not agreed (no offers)",
        "hi-Latn": "Sahmati nahin (koi offers nahin)",
        "hi": "सहमति नहीं (कोई ऑफ़र नहीं)",
    },
    "export.f.history": {
        "en": "Changes you made",
        "hi-Latn": "Aapke kiye badlav",
        "hi": "आपके किए बदलाव",
    },
    "export.f.agreed": {
        "en": "Agreed",
        "hi-Latn": "Sahmat hue",
        "hi": "सहमत हुए",
    },
    "export.f.stopped": {
        "en": "Stopped",
        "hi-Latn": "Band kiya",
        "hi": "बंद किया",
    },
    "export.f.role": {
        "en": "What they do",
        "hi-Latn": "Woh kya karte hain",
        "hi": "वे क्या करते हैं",
    },
    "export.f.data": {
        "en": "Data they see",
        "hi-Latn": "Woh kaun sa data dekhte hain",
        "hi": "वे कौन सा डेटा देखते हैं",
    },
    "export.o.placed": {
        "en": "Placed",
        "hi-Latn": "Diya gaya",
        "hi": "दिया गया",
    },
    "export.o.completed": {
        "en": "Completed",
        "hi-Latn": "Poora hua",
        "hi": "पूरा हुआ",
    },
    "export.o.cancelled": {
        "en": "Cancelled",
        "hi-Latn": "Cancel hua",
        "hi": "रद्द हुआ",
    },
    "export.r.refund": {
        "en": "Refund",
        "hi-Latn": "Refund",
        "hi": "रिफ़ंड",
    },
    "export.r.free_item_voucher": {
        "en": "Voucher",
        "hi-Latn": "Voucher",
        "hi": "वाउचर",
    },
    "export.c.marketing": {
        "en": "Offers and promotions",
        "hi-Latn": "Offers aur promotions",
        "hi": "ऑफ़र और प्रचार",
    },
    "export.print": {
        "en": "Print or save as PDF",
        "hi-Latn": "Print karein ya PDF mein save karein",
        "hi": "प्रिंट करें या PDF में सहेजें",
    },
    "export.back": {
        "en": "Back to Privacy & data",
        "hi-Latn": "Privacy aur data par wapas",
        "hi": "गोपनीयता और डेटा पर वापस",
    },
    "export.open": {
        "en": "Open readable version",
        "hi-Latn": "Padhne laayak roop kholein",
        "hi": "पढ़ने योग्य रूप खोलें",
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
