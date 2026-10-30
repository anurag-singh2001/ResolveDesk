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
        "en": "You can also reach our privacy and grievance contact: {contact}.",
        "hi-Latn": "Aap hamare privacy aur shikayat sampark se bhi sampark kar sakte hain: "
        "{contact}.",
        "hi": "आप हमारे प्राइवेसी और शिकायत संपर्क से भी संपर्क कर सकते हैं: {contact}।",
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
        "en": "Kept {years} years, counted from the end of the financial year, as business "
        "records.",
        "hi-Latn": "{years} saal tak rakha jaata hai, vitt varsh ke ant se ginkar, business "
        "record ke roop mein.",
        "hi": "वित्त वर्ष के अंत से गिनकर {years} साल तक, व्यवसाय रिकॉर्ड के रूप में रखा जाता है।",
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
        "en": "We never see or store your card number, CVV or UPI PIN.",
        "hi-Latn": "Hum aapka card number, CVV ya UPI PIN na dekhte hain, na rakhte hain.",
        "hi": "हम आपका कार्ड नंबर, CVV या UPI PIN न देखते हैं, न रखते हैं।",
    },
    "held.not_kept.upi_details": {
        "en": "We do not keep your UPI details.",
        "hi-Latn": "Hum aapke UPI details nahin rakhte.",
        "hi": "हम आपके UPI विवरण नहीं रखते।",
    },
    "held.contact.label": {
        "en": "Privacy and grievance contact",
        "hi-Latn": "Privacy aur shikayat sampark",
        "hi": "प्राइवेसी और शिकायत संपर्क",
    },
    # Our own targets, not a legal deadline (owner decision P2).
    "held.contact.target": {
        "en": "We confirm we have your message within {hours} hours and aim to reply within "
        "{days} days.",
        "hi-Latn": "Hum {hours} ghante ke andar bata dete hain ki aapka sandesh mil gaya aur "
        "{days} din ke andar jawab dene ka lakshya rakhte hain.",
        "hi": "हम {hours} घंटे के भीतर बता देते हैं कि आपका संदेश मिल गया और {days} दिन के भीतर "
        "जवाब देने का लक्ष्य रखते हैं।",
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
    # ---- erasure explained and tracked (S8.5d, app/engine/erasure_info.py). Hindi copy awaits
    # native review (docs/DECISIONS.md). The lists must match what data_rights._redact and
    # erasure_block really do; tests/integration/test_erasure_info.py checks that.
    "erase.title": {
        "en": "Erase my data",
        "hi-Latn": "Mera data mitaiye",
        "hi": "मेरा डेटा मिटाएं",
    },
    "erase.intro": {
        "en": "Erasing removes your personal details from our records. Some records have to stay. "
        "Read the lists below, then decide.",
        "hi-Latn": "Erase karne se aapki nijee jaankari hamare records se hat jaati hai. Kuch "
        "records rakhne padte hain. Neeche ki soochi padhiye, phir tay kijiye.",
        "hi": "मिटाने से आपकी निजी जानकारी हमारे रिकॉर्ड से हट जाती है। कुछ रिकॉर्ड रखने पड़ते हैं। "
        "नीचे की सूची पढ़ें, फिर तय करें।",
    },
    "erase.h.remove": {
        "en": "We will remove",
        "hi-Latn": "Hum hata denge",
        "hi": "हम हटा देंगे",
    },
    "erase.h.keep": {
        "en": "We will keep",
        "hi-Latn": "Hum rakhenge",
        "hi": "हम रखेंगे",
    },
    "erase.h.wait": {
        "en": "We may wait",
        "hi-Latn": "Hum intezaar kar sakte hain",
        "hi": "हम इंतज़ार कर सकते हैं",
    },
    "erase.remove.name": {
        "en": "Your name",
        "hi-Latn": "Aapka naam",
        "hi": "आपका नाम",
    },
    "erase.remove.contact": {
        "en": "Your phone number and email",
        "hi-Latn": "Aapka phone number aur email",
        "hi": "आपका फ़ोन नंबर और ईमेल",
    },
    "erase.remove.messages": {
        "en": "The text of your support messages",
        "hi-Latn": "Aapke support messages ka text",
        "hi": "आपके सपोर्ट संदेशों का टेक्स्ट",
    },
    "erase.remove.profile": {
        "en": "Extra details saved on your profile",
        "hi-Latn": "Aapki profile par saved anya jaankari",
        "hi": "आपकी प्रोफ़ाइल पर सहेजी गई अन्य जानकारी",
    },
    "erase.remove.login": {
        "en": "Your sign-in. You will not be able to sign in again.",
        "hi-Latn": "Aapka sign-in. Aap dobara sign in nahin kar paayenge.",
        "hi": "आपका साइन-इन। आप दोबारा साइन इन नहीं कर पाएंगे।",
    },
    "erase.remove.offers": {
        "en": "Offers and promotions are turned off for you",
        "hi-Latn": "Aapke liye offers aur promotions band kar diye jaate hain",
        "hi": "आपके लिए ऑफ़र और प्रमोशन बंद कर दिए जाते हैं",
    },
    "erase.keep.records": {
        "en": "Orders, payments and refunds: amounts, dates, order references and refund or "
        "voucher records",
        "hi-Latn": "Orders, payments aur refunds: raashi, taareekh, order references aur refund "
        "ya voucher ke records",
        "hi": "ऑर्डर, भुगतान और रिफ़ंड: राशि, तारीख़, ऑर्डर संदर्भ और रिफ़ंड या वाउचर के रिकॉर्ड",
    },
    "erase.keep.records.why": {
        "en": "Kept {years} years, counted from the end of the financial year, for our "
        "accounts and to show what was paid.",
        "hi-Latn": "{years} saal rakhe jaate hain, vitt varsh ke ant se ginkar, hamare hisaab ke "
        "liye aur yeh dikhane ke liye ki kya bhugtaan hua.",
        "hi": "वित्त वर्ष के अंत से गिनकर {years} साल रखे जाते हैं, हमारे हिसाब के लिए और यह "
        "दिखाने के लिए कि क्या भुगतान हुआ।",
    },
    "erase.keep.cases": {
        "en": "Case records: category, status and dates",
        "hi-Latn": "Case ke records: category, status aur taareekh",
        "hi": "केस के रिकॉर्ड: श्रेणी, स्थिति और तारीख़",
    },
    "erase.keep.cases.why": {
        "en": "To show what was decided and paid on each case. Your message text is removed.",
        "hi-Latn": "Yeh dikhane ke liye ki har case par kya tay hua aur kya diya gaya. Aapke "
        "messages ka text hata diya jaata hai.",
        "hi": "यह दिखाने के लिए कि हर केस पर क्या तय हुआ और क्या दिया गया। आपके संदेशों का टेक्स्ट "
        "हटा दिया जाता है।",
    },
    "erase.keep.audit": {
        "en": "A log of actions taken (who did what, and when)",
        "hi-Latn": "Kiye gaye kaamon ka log (kisne kya kiya, aur kab)",
        "hi": "किए गए कामों का लॉग (किसने क्या किया, और कब)",
    },
    "erase.keep.audit.why": {
        "en": "It shows that money and privacy actions were handled properly. It holds codes and "
        "ids, not your name or message text.",
        "hi-Latn": "Yeh dikhata hai ki paise aur privacy ke kaam theek se hue. Isme codes aur ids "
        "hote hain, aapka naam ya messages ka text nahin.",
        "hi": "यह दिखाता है कि पैसे और प्राइवेसी के काम ठीक से हुए। इसमें कोड और आईडी होते हैं, "
        "आपका नाम या संदेशों का टेक्स्ट नहीं।",
    },
    "erase.keep.consents": {
        "en": "Your record of agreeing to or stopping offers",
        "hi-Latn": "Offers ke liye haan ya band karne ka aapka record",
        "hi": "ऑफ़र के लिए हां या बंद करने का आपका रिकॉर्ड",
    },
    "erase.keep.consents.why": {
        "en": "It is proof of what you chose and when.",
        "hi-Latn": "Yeh saboot hai ki aapne kya chuna aur kab.",
        "hi": "यह सबूत है कि आपने क्या चुना और कब।",
    },
    "erase.keep.linked": {
        "en": "Other records linked to you by a reference number, such as offer lists, signals "
        "and notes on decisions. Your language choice and home outlet also stay.",
        "hi-Latn": "Reference number se aapse jude anya records, jaise offer ki soochi, signals "
        "aur faislon par notes. Aapki bhasha ka chunav aur home outlet bhi rehte hain.",
        "hi": "संदर्भ संख्या से आपसे जुड़े अन्य रिकॉर्ड, जैसे ऑफ़र सूची, सिग्नल और फ़ैसलों पर नोट। "
        "आपकी भाषा की पसंद और होम आउटलेट भी रहते हैं।",
    },
    "erase.keep.linked.why": {
        "en": "They hold no name or contact details. They show how offers and decisions were made.",
        "hi-Latn": "Inme naam ya contact details nahin hote. Yeh dikhate hain ki offers aur faisle "
        "kaise hue.",
        "hi": "इनमें नाम या संपर्क विवरण नहीं होते। ये दिखाते हैं कि ऑफ़र और फ़ैसले कैसे हुए।",
    },
    "erase.keep.reference": {
        "en": "Your customer reference code",
        "hi-Latn": "Aapka customer reference code",
        "hi": "आपका ग्राहक संदर्भ कोड",
    },
    "erase.keep.reference.why": {
        "en": "It is a code, not your name. It links the records above.",
        "hi-Latn": "Yeh ek code hai, aapka naam nahin. Yeh upar ke records ko jodta hai.",
        "hi": "यह एक कोड है, आपका नाम नहीं। यह ऊपर के रिकॉर्ड को जोड़ता है।",
    },
    "erase.wait.review": {
        "en": "A member of our team approves each request first.",
        "hi-Latn": "Hamari team ka ek sadasya pehle har request ko manzoor karta hai.",
        "hi": "हमारी टीम का एक सदस्य पहले हर अनुरोध को मंज़ूर करता है।",
    },
    "erase.wait.retention_floor": {
        "en": "Less than a year has passed since your last order or case. We must keep some "
        "records for at least one year, so the request can go ahead after that.",
        "hi-Latn": "Aapke aakhri order ya case ko ek saal nahin hua hai. Hamein kuch records "
        "kam se kam ek saal rakhne hote hain, isliye request uske baad aage badh sakti hai.",
        "hi": "आपके आखिरी ऑर्डर या केस को एक साल नहीं हुआ है। हमें कुछ रिकॉर्ड कम से कम एक साल रखने "
        "होते हैं, इसलिए अनुरोध उसके बाद आगे बढ़ सकता है।",
    },
    "erase.reason.open_case": {
        "en": "You have a case that is still being handled. We can erase your data once it is "
        "closed.",
        "hi-Latn": "Aapka ek case abhi chal raha hai. Wo band hone par hum aapka data mita sakte "
        "hain.",
        "hi": "आपका एक केस अभी चल रहा है। वह बंद होने पर हम आपका डेटा मिटा सकते हैं।",
    },
    "erase.reason.in_flight": {
        "en": "A refund or payment linked to your orders is still being processed. We will "
        "revisit your request once it has settled.",
        "hi-Latn": "Aapke orders se jura koi refund ya payment abhi process ho raha hai. Wo poora "
        "hone par hum aapki request dobara dekhenge.",
        "hi": "आपके ऑर्डर से जुड़ा कोई रिफ़ंड या भुगतान अभी प्रोसेस हो रहा है। वह पूरा होने पर हम "
        "आपका अनुरोध फिर देखेंगे।",
    },
    "erase.reason.legal_hold": {
        "en": "Some of your records are on hold and must be kept for now. A member of our team "
        "will follow up.",
        "hi-Latn": "Aapke kuch records hold par hain aur abhi rakhne padenge. Hamari team ka ek "
        "sadasya aapse sampark karega.",
        "hi": "आपके कुछ रिकॉर्ड होल्ड पर हैं और अभी रखने होंगे। हमारी टीम का एक सदस्य आपसे संपर्क करेगा।",
    },
    "erase.reason.retention_floor": {
        "en": "We must keep some records for at least one year after your last activity. Your "
        "request can go ahead after {date}.",
        "hi-Latn": "Hamein aapki aakhri gatividhi ke baad kuch records kam se kam ek saal rakhne "
        "hote hain. Aapki request {date} ke baad aage badh sakti hai.",
        "hi": "हमें आपकी आखिरी गतिविधि के बाद कुछ रिकॉर्ड कम से कम एक साल रखने होते हैं। आपका "
        "अनुरोध {date} के बाद आगे बढ़ सकता है।",
    },
    "erase.btn.request": {
        "en": "Request erasure",
        "hi-Latn": "Erase ki request karein",
        "hi": "मिटाने का अनुरोध करें",
    },
    "erase.confirm.title": {
        "en": "Ask us to erase your data?",
        "hi-Latn": "Kya aap apna data mitaane ko kehna chahte hain?",
        "hi": "क्या आप अपना डेटा मिटाने के लिए कहना चाहते हैं?",
    },
    "erase.confirm.body": {
        "en": "Once it is done it cannot be undone. The lists above apply: what we remove, what we "
        "keep, and what may make us wait. Until it is done you can withdraw the request.",
        "hi-Latn": "Ek baar ho jaane par ise wapas nahin kiya ja sakta. Upar ki soochiyan lagu "
        "hoti hain: kya hatega, kya rahega, aur kis wajah se intezaar ho sakta hai. Jab tak yeh "
        "poora nahin hota, aap request wapas le sakte hain.",
        "hi": "एक बार हो जाने पर इसे वापस नहीं किया जा सकता। ऊपर की सूचियां लागू होती हैं: क्या हटेगा, "
        "क्या रहेगा, और किस वजह से इंतज़ार हो सकता है। जब तक यह पूरा नहीं होता, आप अनुरोध वापस "
        "ले सकते हैं।",
    },
    "erase.btn.confirm": {
        "en": "Yes, request erasure",
        "hi-Latn": "Haan, erase ki request karein",
        "hi": "हां, मिटाने का अनुरोध करें",
    },
    "erase.btn.back": {
        "en": "Cancel",
        "hi-Latn": "Raddh karein",
        "hi": "रद्द करें",
    },
    "erase.btn.withdraw": {
        "en": "Withdraw my request",
        "hi-Latn": "Meri request wapas lein",
        "hi": "मेरा अनुरोध वापस लें",
    },
    "erase.status.title": {
        "en": "Your erasure request",
        "hi-Latn": "Aapki erase request",
        "hi": "आपका मिटाने का अनुरोध",
    },
    "erase.stage.received": {
        "en": "Received",
        "hi-Latn": "Mil gayi",
        "hi": "मिल गया",
    },
    "erase.stage.deferred": {
        "en": "Could not complete yet",
        "hi-Latn": "Abhi poori nahin ho sakti",
        "hi": "अभी पूरा नहीं हो सकता",
    },
    "erase.stage.done": {
        "en": "Done",
        "hi-Latn": "Ho gaya",
        "hi": "हो गया",
    },
    "erase.stage.withdrawn": {
        "en": "Withdrawn",
        "hi-Latn": "Wapas li gayi",
        "hi": "वापस ले लिया गया",
    },
    "erase.stage.received.text": {
        "en": "We have your request. Nothing has been erased yet. A member of our team will "
        "review it.",
        "hi-Latn": "Humein aapki request mil gayi hai. Abhi kuch mitaya nahin gaya hai. Hamari "
        "team ka ek sadasya ise dekhega.",
        "hi": "हमें आपका अनुरोध मिल गया है। अभी कुछ मिटाया नहीं गया है। हमारी टीम का एक सदस्य इसे देखेगा।",
    },
    "erase.stage.deferred.text": {
        "en": "Nothing has been erased. Reason: ",
        "hi-Latn": "Kuch mitaya nahin gaya hai. Wajah: ",
        "hi": "कुछ मिटाया नहीं गया है। वजह: ",
    },
    "erase.stage.done.text": {
        "en": "Your data was erased on {date}.",
        "hi-Latn": "Aapka data {date} ko mita diya gaya.",
        "hi": "आपका डेटा {date} को मिटा दिया गया।",
    },
    "erase.stage.withdrawn.text": {
        "en": "You withdrew this request. Nothing was erased.",
        "hi-Latn": "Aapne yeh request wapas le li. Kuch mitaya nahin gaya.",
        "hi": "आपने यह अनुरोध वापस ले लिया। कुछ मिटाया नहीं गया।",
    },
    "erase.received_on": {
        "en": "Received on {date}",
        "hi-Latn": "{date} ko mili",
        "hi": "{date} को मिला",
    },
    "erase.expected_by": {
        "en": "We aim to finish by {date}.",
        "hi-Latn": "Hum {date} tak poora karne ka lakshya rakhte hain.",
        "hi": "हम {date} तक पूरा करने का लक्ष्य रखते हैं।",
    },
    # ---- erasure completion message (S8.8, owner decision P4). Hindi awaits native review ----
    "erase.notice.sent_to": {
        "en": "When it is done we will tell you once, at the contact you choose. We keep that "
        "contact for up to {days} days, only to send this message, and then delete it.",
        "hi-Latn": "Kaam poora hone par hum aapko ek baar, aapke chune hue sampark par bata "
        "denge. Hum yeh sampark sirf is sandesh ke liye {days} din tak rakhte hain, phir mita "
        "dete hain.",
        "hi": "काम पूरा होने पर हम आपको एक बार, आपके चुने हुए संपर्क पर बता देंगे। हम यह संपर्क "
        "सिर्फ़ इस संदेश के लिए {days} दिन तक रखते हैं, फिर मिटा देते हैं।",
    },
    "erase.notice.none": {
        "en": "We have no phone number or email for you, so we cannot tell you when it is "
        "done. You can check with our privacy and grievance contact.",
        "hi-Latn": "Hamare paas aapka phone number ya email nahin hai, isliye hum aapko bata "
        "nahin payenge ki kaam ho gaya. Aap hamare privacy aur shikayat sampark se pooch sakte "
        "hain.",
        "hi": "हमारे पास आपका फ़ोन नंबर या ईमेल नहीं है, इसलिए हम आपको बता नहीं पाएँगे कि काम हो "
        "गया। आप हमारे प्राइवेसी और शिकायत संपर्क से पूछ सकते हैं।",
    },
    "erase.notice.choose": {
        "en": "Where should we tell you?",
        "hi-Latn": "Hum aapko kahan bataye?",
        "hi": "हम आपको कहाँ बताएँ?",
    },
    "erase.notice.phone": {
        "en": "My phone",
        "hi-Latn": "Mera phone",
        "hi": "मेरा फ़ोन",
    },
    "erase.notice.email": {
        "en": "My email",
        "hi-Latn": "Mera email",
        "hi": "मेरा ईमेल",
    },
    "notice.done": {
        "en": "Your erasure request {reference} is complete. We removed your name, contact "
        "details and message text, and turned off offers and promotions.",
        "hi-Latn": "Aapka erasure request {reference} poora ho gaya. Humne aapka naam, sampark "
        "vivaran aur sandesh ka text hata diya hai, aur offers aur promotions band kar diye hain.",
        "hi": "आपका मिटाने का अनुरोध {reference} पूरा हो गया। हमने आपका नाम, संपर्क विवरण और "
        "संदेशों का टेक्स्ट हटा दिया है, और ऑफ़र और प्रमोशन बंद कर दिए हैं।",
    },
    "notice.kept": {
        "en": "We kept payment and refund records, without your name, for our accounts and to "
        "show what was paid. They are kept up to {years} years.",
        "hi-Latn": "Humne bhugtaan aur refund ke records aapke naam ke bina rakhe hain, hamare "
        "hisaab ke liye aur yeh dikhane ke liye ki kya bhugtaan hua. Ve {years} saal tak rakhe "
        "jaate hain.",
        "hi": "हमने भुगतान और रिफ़ंड के रिकॉर्ड आपके नाम के बिना रखे हैं, हमारे हिसाब के लिए और यह "
        "दिखाने के लिए कि क्या भुगतान हुआ। वे {years} साल तक रखे जाते हैं।",
    },
    "notice.contact": {
        "en": "If you have a question or complaint, contact {contact}; we aim to reply within "
        "{days} days.",
        "hi-Latn": "Agar aapka koi sawal ya shikayat hai, to {contact} se sampark karein; hum "
        "{days} din ke andar jawab dene ka lakshya rakhte hain.",
        "hi": "अगर आपका कोई सवाल या शिकायत है, तो {contact} से संपर्क करें; हम {days} दिन के भीतर "
        "जवाब देने का लक्ष्य रखते हैं।",
    },
    "notice.board": {
        "en": "If you are still not satisfied after using our process, you can complain to the "
        "Data Protection Board of India.",
        "hi-Latn": "Agar hamari prakriya ke baad bhi aap santusht nahin hain, to aap Data "
        "Protection Board of India se shikayat kar sakte hain.",
        "hi": "अगर हमारी प्रक्रिया के बाद भी आप संतुष्ट नहीं हैं, तो आप डेटा प्रोटेक्शन बोर्ड ऑफ़ "
        "इंडिया से शिकायत कर सकते हैं।",
    },
    # ---- consent as benefits (S8.5b). Hindi awaits native review (docs/DECISIONS.md) ----
    "consent.h.title": {
        "en": "Offers and promotions",
        "hi-Latn": "Offers aur promotions",
        "hi": "ऑफ़र और प्रमोशन",
    },
    "consent.h.intro": {
        "en": "You choose whether we send you offers. You can change a switch at any time.",
        "hi-Latn": "Offers bhejein ya nahin, yeh aap chunte hain. "
        "Aap kabhi bhi switch badal sakte hain.",
        "hi": "ऑफ़र भेजें या नहीं, यह आप चुनते हैं। आप कभी भी स्विच बदल सकते हैं।",
    },
    "consent.h.history": {
        "en": "History of your choices",
        "hi-Latn": "Aapke choices ka itihaas",
        "hi": "आपकी पसंद का इतिहास",
    },
    "consent.h.note": {
        "en": "Turning offers off never changes the help you get with an order.",
        "hi-Latn": "Offers band karne se order mein milne wali madad par koi asar nahin padta.",
        "hi": "ऑफ़र बंद करने से ऑर्डर में मिलने वाली मदद पर कोई असर नहीं पड़ता।",
    },
    "consent.h.on": {
        "en": "On",
        "hi-Latn": "Chalu",
        "hi": "चालू",
    },
    "consent.h.off": {
        "en": "Off",
        "hi-Latn": "Band",
        "hi": "बंद",
    },
    "consent.h.notice": {
        "en": "Wording version",
        "hi-Latn": "Wording version",
        "hi": "शब्दावली संस्करण",
    },
    "consent.marketing.title": {
        "en": "Offers and vouchers",
        "hi-Latn": "Offers aur vouchers",
        "hi": "ऑफ़र और वाउचर",
    },
    "consent.marketing.benefit": {
        "en": "Hear about offers and vouchers for your next order.",
        "hi-Latn": "Apne agle order ke offers aur vouchers ke bare mein jaaniye.",
        "hi": "अपने अगले ऑर्डर के ऑफ़र और वाउचर के बारे में जानिए।",
    },
    "consent.marketing.sent": {
        "en": "We send a short message about an offer or voucher.",
        "hi-Latn": "Hum offer ya voucher ke bare mein ek chhota message bhejte hain.",
        "hi": "हम ऑफ़र या वाउचर के बारे में एक छोटा संदेश भेजते हैं।",
    },
    "consent.marketing.switch": {
        "en": "Send me offers and vouchers",
        "hi-Latn": "Mujhe offers aur vouchers bhejiye",
        "hi": "मुझे ऑफ़र और वाउचर भेजें",
    },
    "consent.cap": {
        "en": "At most one offer message in {days} days.",
        "hi-Latn": "{days} din mein zyada se zyada ek offer message.",
        "hi": "{days} दिन में अधिकतम एक ऑफ़र संदेश।",
    },
    "consent.channel.whatsapp": {
        "en": "On WhatsApp",
        "hi-Latn": "WhatsApp par",
        "hi": "WhatsApp पर",
    },
    "consent.state.on": {
        "en": "On",
        "hi-Latn": "Chalu",
        "hi": "चालू",
    },
    "consent.state.off": {
        "en": "Off",
        "hi-Latn": "Band",
        "hi": "बंद",
    },
    "consent.help.title": {
        "en": "Help messages",
        "hi-Latn": "Madad ke messages",
        "hi": "मदद के संदेश",
    },
    "consent.help.body": {
        "en": "Always on, needed to resolve your order. There is no switch for these, "
        "and turning offers off does not change them.",
        "hi-Latn": "Hamesha chalu, aapka order suljhane ke liye zaroori. "
        "Inke liye koi switch nahin hai, aur offers band karne se yeh nahin badalte.",
        "hi": "हमेशा चालू, आपका ऑर्डर सुलझाने के लिए ज़रूरी। "
        "इनके लिए कोई स्विच नहीं है, और ऑफ़र बंद करने से ये नहीं बदलते।",
    },
    "consent.help.badge": {
        "en": "Always on",
        "hi-Latn": "Hamesha chalu",
        "hi": "हमेशा चालू",
    },
    "consent.hist.granted": {
        "en": "agreed to",
        "hi-Latn": "sahmat hue",
        "hi": "सहमत हुए",
    },
    "consent.hist.withdrawn": {
        "en": "stopped",
        "hi-Latn": "band kiya",
        "hi": "बंद किया",
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
    # Owner decision M2 (2026-10-31): a reason, a way to contest, and the National Consumer
    # Helpline. {contact} is the privacy and grievance contact; {days} the settlement target.
    "close.no_remedy": {
        "en": "We have looked at your case again and, based on the records for this order, we "
        "are not able to offer a refund or voucher this time. If you think we have missed "
        "something, or you have a photo or receipt to share, contact us at {contact}: we reply "
        "within 2 working days and aim to settle within {days} days. You can also call the "
        "National Consumer Helpline on 1915 (consumerhelpline.gov.in).",
        "hi-Latn": "Humne aapka case dobara dekha. Is order ke records ke hisaab se hum is baar "
        "refund ya voucher nahi de paa rahe hain. Agar aapko lagta hai ki kuch chhoot gaya hai, "
        "ya aapke paas photo ya rasid hai, to {contact} par likhiye: hum 2 kaam ke dinon mein "
        "jawab denge aur {days} din mein nipatane ki koshish karenge. Aap National Consumer "
        "Helpline 1915 (consumerhelpline.gov.in) par bhi sampark kar sakte hain.",
        "hi": "हमने आपका केस दोबारा देखा। इस ऑर्डर के रिकॉर्ड के आधार पर हम इस बार रिफंड या "
        "वाउचर नहीं दे पा रहे हैं। अगर आपको लगता है कि कुछ छूट गया है, या आपके पास फ़ोटो या "
        "रसीद है, तो {contact} पर लिखें: हम 2 कार्य-दिवस में जवाब देंगे और {days} दिन में "
        "निपटाने का प्रयास करेंगे। आप राष्ट्रीय उपभोक्ता हेल्पलाइन 1915 (consumerhelpline.gov.in) "
        "पर भी संपर्क कर सकते हैं।",
    },
    # Same sentence without the contact clause, used only while no contact is set.
    "close.no_remedy_nocontact": {
        "en": "We have looked at your case again and, based on the records for this order, we "
        "are not able to offer a refund or voucher this time. You can call the National "
        "Consumer Helpline on 1915 (consumerhelpline.gov.in) if you think we have missed "
        "something.",
        "hi-Latn": "Humne aapka case dobara dekha. Is order ke records ke hisaab se hum is baar "
        "refund ya voucher nahi de paa rahe hain. Agar aapko lagta hai ki kuch chhoot gaya hai, to "
        "aap National Consumer Helpline 1915 (consumerhelpline.gov.in) par sampark kar sakte hain.",
        "hi": "हमने आपका केस दोबारा देखा। इस ऑर्डर के रिकॉर्ड के आधार पर हम इस बार रिफंड या "
        "वाउचर नहीं दे पा रहे हैं। अगर आपको लगता है कि कुछ छूट गया है, तो आप राष्ट्रीय "
        "उपभोक्ता हेल्पलाइन 1915 (consumerhelpline.gov.in) पर संपर्क कर सकते हैं।",
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
    "export.other": {
        "en": "Other",
        "hi-Latn": "Anya",
        "hi": "अन्य",
    },
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
