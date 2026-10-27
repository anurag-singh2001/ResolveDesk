"""S7.12: reply-language detection, the research's 13 messages layer by layer (no tenant, no DB)."""

from types import SimpleNamespace

import pytest

from app.core import language
from app.core.i18n import LANGUAGES, case_language
from app.core.language import detect, observe


class _Session:
    """Just enough session for observe(): audit rows are collected, customers are absent."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def get(self, *_):
        return None


def _case(lang=None, pending=None):
    return SimpleNamespace(
        id=None, tenant_id=None, customer_id=None, language=lang, language_pending=pending
    )


@pytest.mark.parametrize(
    "text, label, source",
    [
        ("मेरा ऑर्डर अभी तक नहीं आया", "hi", "rule"),  # 1
        ("Where is my order? It's been 50 minutes.", "en", None),  # 2
        ("mera order abhi tak nahi aaya, refund do", "hi-Latn", "heuristic"),  # 3
        ("bhai khana bahut thanda tha, paisa wapas chahiye", "hi-Latn", "heuristic"),  # 4
        ("My biryani was cold, please refund", "en", None),  # 5
        ("order #4821 में चिकन नहीं था", "hi", "rule"),  # 6
        ("refund", "en", "default"),  # 7
        ("😡😡 order 4821", "en", "default"),  # 8
        ("Paneer Butter Masala and Masala Chai missing from order", "en", None),  # 9
        ("kya aap bata sakte ho ki refund kab milega?", "hi-Latn", "heuristic"),  # 10
        ("अब हिंदी में बताइए", "hi", "rule"),  # 13
    ],
)
def test_the_research_messages_without_a_model(text, label, source):
    got = detect(text)
    assert got.label == label
    if source:
        assert got.source == source


def test_devanagari_decides_without_consulting_the_model():
    got = detect("मेरा ऑर्डर अभी तक नहीं आया", llm_label="en", llm_confidence=1.0)
    assert (got.label, got.source, got.confidence) == ("hi", "rule", 1.0)


def test_confident_model_label_is_used_and_low_confidence_falls_back_to_the_word_list():
    assert detect("my order is late", "hi-Latn", 0.9).source == "llm"
    low = detect("mera order abhi tak nahi aaya, refund do", "en", 0.4)
    assert (low.label, low.source) == ("hi-Latn", "heuristic")
    assert detect("Where is my order", "hi", 0.5).label == "en"


@pytest.mark.parametrize("bad", ["fr", "HI", "", None, 3, ["hi"], "hi; ignore previous"])
def test_a_bad_model_label_never_escapes_the_closed_set(bad):
    got = detect("Where is my order today", bad, 0.99)
    assert got.label in LANGUAGES and got.source != "llm"
    assert detect("hello there friend", "hi", "0.9").source != "llm"  # confidence must be a number
    assert detect("hello there friend", "hi", True).source != "llm"


def test_one_hinglish_word_is_not_hinglish():
    assert detect("please send the refund, bhai").label == "en"
    assert detect("the order did not arrive and I want a refund, nahi chahiye please").label == "en"


def test_never_raises_on_odd_input():
    for text in ("", "   ", None, "1234", "😡", "#4821", "।"):
        assert detect(text).label == "en"


# ---- per-case behaviour (research 7, 8, 11, 12, 13) ----


def test_first_message_sets_the_case_language_and_audits_without_the_text():
    s, case = _Session(), _case()
    assert observe(s, case, "mera order abhi tak nahi aaya, refund do") == "hi-Latn"
    (row,) = s.added
    assert row.event == "case.language_set"
    assert row.payload["label"] == "hi-Latn" and row.payload["source"] == "heuristic"
    assert "confidence" in row.payload and "mera" not in str(row.payload)


def test_agents_mode_waits_for_the_classifier_unless_plainly_devanagari():
    s, case = _Session(), _case()
    text = "mera order nahi aaya, paisa wapas chahiye"
    assert observe(s, case, text, allow_heuristic=False) is None
    assert observe(s, case, "मेरा ऑर्डर नहीं आया", allow_heuristic=False) == "hi"


def test_the_classifier_label_decides_when_confident():
    s, case = _Session(), _case()
    assert observe(s, case, "order late", llm_label="hi-Latn", llm_confidence=0.9) == "hi-Latn"
    assert s.added[0].payload["source"] == "llm"


def test_short_or_empty_messages_never_change_a_case():  # 7, 8, 11
    for start in LANGUAGES:
        for text in ("haan", "yes", "ok", "refund", "😡😡 order 4821", "4821", "haan nahi", "हाँ"):
            s, case = _Session(), _case(start)
            assert observe(s, case, text) == start and s.added == []


def test_two_consecutive_confident_messages_switch_but_one_does_not():  # 12
    s, case = _Session(), _case("en")
    assert observe(s, case, "mujhe paisa wapas chahiye") == "en"
    assert case.language_pending == "hi-Latn"
    assert observe(s, case, "order nahi mila abhi tak") == "hi-Latn"
    assert case.language_pending is None
    assert s.added[-1].event == "case.language_changed"


def test_a_message_in_the_current_language_resets_the_pending_switch():
    s, case = _Session(), _case("en")
    observe(s, case, "mujhe paisa wapas chahiye")
    observe(s, case, "Where is my order, it was ordered an hour ago")
    assert case.language_pending is None
    assert observe(s, case, "order nahi mila abhi tak") == "en"


def test_one_devanagari_message_switches_at_once():  # 13
    s, case = _Session(), _case("en")
    assert observe(s, case, "अब हिंदी में बताइए") == "hi"


def test_english_is_a_switch_target_too():
    s, case = _Session(), _case("hi-Latn")
    observe(s, case, "Where is my order, it has been late for an hour")
    assert observe(s, case, "Please refund the missing item from this order") == "en"


def test_case_language_prefers_the_case_then_the_default():
    assert case_language(None, SimpleNamespace(language="hi", customer_id=None)) == "hi"
    assert case_language(None, SimpleNamespace(language=None, customer_id=None)) == "en"
    assert case_language(None, SimpleNamespace(language="zz", customer_id=None)) == "en"


def test_limits_are_the_researched_ones():
    assert language.DEVANAGARI_SHARE == 0.30 and language.LLM_MIN_CONFIDENCE == 0.6
