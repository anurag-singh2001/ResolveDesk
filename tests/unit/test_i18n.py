"""S5.6: customer templates exist in every language, statuses stay distinct, English backs up."""

import re
from datetime import UTC, date, datetime

import pytest

from app.core import i18n
from app.core.i18n import LANGUAGES, MONEY_STATUS_KEYS, TEMPLATES, format_date, normalize, t
from app.core.money import format_inr
from app.engine import needs
from app.engine.privacy import customer_message

_PLACEHOLDER = re.compile(r"{(\w+)}")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_SAMPLE = {
    "amount": format_inr(12345000),
    "date": "27 Oct 2026",
    "contact": "Asha (a@example.com)",
    "label": "thing",
    "remedy": "x",
}


def test_every_key_exists_in_all_three_languages():
    for key, variants in TEMPLATES.items():
        for lang in LANGUAGES:
            assert variants.get(lang, "").strip(), f"{key} has no {lang} text"
        assert set(variants) <= set(LANGUAGES), f"{key} has an unknown language"


def test_every_translation_has_the_same_placeholders_as_english():
    for key, variants in TEMPLATES.items():
        want = set(_PLACEHOLDER.findall(variants["en"]))
        for lang in LANGUAGES:
            assert set(_PLACEHOLDER.findall(variants[lang])) == want, (key, lang)
            variants[lang].format(**_SAMPLE)  # renders without a KeyError


def test_scripts_are_what_the_codes_promise():
    for key, variants in TEMPLATES.items():
        assert not _DEVANAGARI.search(variants["en"]), key
        assert not _DEVANAGARI.search(variants["hi-Latn"]), key
        assert _DEVANAGARI.search(variants["hi"]), key


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_five_money_statuses_are_five_different_texts(lang):
    assert list(MONEY_STATUS_KEYS) == ["submitted", "processing", "succeeded", "failed", "unknown"]
    texts = [t(key, lang, amount="₹1.00") for key in MONEY_STATUS_KEYS.values()]
    assert len(set(texts)) == 5


def test_a_missing_translation_falls_back_to_english(monkeypatch):
    english = TEMPLATES["status.declined"]["en"]
    monkeypatch.setattr(i18n, "TEMPLATES", {**TEMPLATES, "status.declined": {"en": english}})
    assert t("status.declined", "hi") == english
    assert t("status.declined", "hi-Latn") == english


def test_unknown_or_missing_language_is_english_and_an_unknown_key_is_a_bug():
    for odd in (None, "", "fr", "HI", 3, ["hi"]):
        assert normalize(odd) == "en"
        assert t("status.declined", odd) == TEMPLATES["status.declined"]["en"]
    with pytest.raises(KeyError):
        t("status.no_such_key", "en")


@pytest.mark.parametrize("lang", LANGUAGES)
def test_an_amount_reads_the_same_in_every_language(lang):
    text = t("status.refund_confirmed", lang, amount=format_inr(10000000))
    assert "₹1,00,000.00" in text


def test_dates_use_a_month_name_never_a_numeric_form():
    d = date(2026, 10, 27)
    assert format_date(d, "en") == "27 Oct 2026"
    assert format_date(d, "hi-Latn") == "27 Oct 2026"
    assert format_date(d, "hi") == "27 अक्टूबर 2026"
    assert len({format_date(date(2026, m, 1), "hi") for m in range(1, 13)}) == 12


@pytest.mark.parametrize("lang", LANGUAGES)
def test_need_questions_follow_the_language_and_unknown_codes_get_the_generic_one(lang):
    assert needs.question_for(needs.NEED_ORDER, lang) == t("need.order", lang)
    assert needs.question_for(needs.NEED_DETAILS, lang) == t("need.details", lang)
    for odd in (None, "", "which_item_is_it", 7):
        assert needs.question_for(odd, lang) == t("need.generic", lang)
    assert needs.question_for(needs.NEED_ORDER) == needs.QUESTIONS[needs.NEED_ORDER]


def test_privacy_message_is_translated_and_keeps_the_contact_and_date():
    opened = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
    settings = {
        "privacy_contact_name": "Asha",
        "privacy_contact_email": "asha@example.com",
        "grievance_target_days": 30,
        "business_timezone": "Asia/Kolkata",
    }
    en = customer_message(opened, settings)
    assert en.startswith("We have received your privacy request")
    assert "Asha (asha@example.com)" in en and "26 Nov 2026" in en
    hi = customer_message(opened, settings, "hi")
    assert "Asha (asha@example.com)" in hi and "26 नवंबर 2026" in hi
    latn = customer_message(opened, settings, "hi-Latn")
    assert "Asha (asha@example.com)" in latn and latn != en
