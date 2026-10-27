"""Reply-language detection (S7.12): which template locale a case's customer messages use.

Layers, cheapest first, no new dependency (docs/research/language-detection.md):
  1. rule      Devanagari is >= 30% of the letters -> `hi` (no model call).
  2. llm       the classifier's own `language` + `language_confidence` (same call, no extra one),
               trusted at confidence >= 0.6.
  3. heuristic a Hinglish word list: >= 2 distinct hits and >= 25% of the words -> `hi-Latn`.
  4. default   `en`.
The result is only ever one of LANGUAGES; customer text and model output pick a locale from a
closed set and are never interpolated anywhere (hard rule 7, rule 9 in spirit).

Per case the language is fixed from the first message and moves only on one Devanagari message,
or two consecutive confident messages in another language. Messages of <= 2 words, or with no
letters (emoji, digits, order ids), never move it. The audit trail records label, source and
confidence, never the message text.
"""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import audit
from app.core.i18n import DEFAULT_LANGUAGE, LANGUAGES

DEVANAGARI_SHARE = 0.30
LLM_MIN_CONFIDENCE = 0.6
SWITCH_MIN_CONFIDENCE = 0.8
HEURISTIC_MIN_HITS = 2
HEURISTIC_MIN_SHARE = 0.25
MIN_WORDS_TO_SWITCH = 3  # <= 2 words never change an existing case language

# High-frequency Hinglish words that are not English words or common names.
HINGLISH_WORDS = frozenset(
    [
        "hai",
        "hain",
        "nahi",
        "nahin",
        "mera",
        "meri",
        "mujhe",
        "aap",
        "kya",
        "kyun",
        "kab",
        "abhi",
        "bhai",
        "yaar",
        "paisa",
        "wapas",
        "chahiye",
        "tha",
        "thi",
        "gaya",
        "mila",
        "aaya",
        "karo",
        "karna",
        "kuch",
        "tak",
        "der",
        "bahut",
        "kitna",
        "jaldi",
        "ghanta",
        "khana",
        "galat",
        "kharab",
        "theek",
        "kripya",
        "dhanyavad",
        "sakte",
        "sakta",
        "milega",
        "haan",
    ]
)
# Words that, in a long enough message, are real evidence of English (used only to switch back).
ENGLISH_WORDS = frozenset(
    [
        "the",
        "is",
        "are",
        "was",
        "were",
        "my",
        "not",
        "it",
        "its",
        "to",
        "and",
        "of",
        "for",
        "with",
        "has",
        "have",
        "been",
        "please",
        "where",
        "when",
        "what",
        "why",
        "how",
        "this",
        "that",
        "i",
        "you",
        "your",
        "me",
        "we",
        "our",
        "order",
        "refund",
        "received",
        "missing",
        "cold",
        "late",
    ]
)


@dataclass(frozen=True)
class Detection:
    label: str
    source: str  # rule | llm | heuristic | default
    confidence: float
    words: int  # letter-words counted (emoji, digits and order ids are not words)


def _words(text: str) -> list[str]:
    # Devanagari vowel signs are combining marks, so match the whole block explicitly.
    return re.findall(r"[A-Za-z]+|[ऀ-ॣ०-ॿ]+", text or "")


def _devanagari_share(text: str) -> float:
    deva = sum(1 for ch in text if "ऀ" <= ch <= "ॿ" and ch not in "।॥")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    total = deva + latin
    return deva / total if total else 0.0


def detect(text: str, llm_label: object = None, llm_confidence: object = None) -> Detection:
    """The best label for one message. Never raises; always one of LANGUAGES."""
    text = text or ""
    lower = [w.lower() for w in _words(text)]
    n = len(lower)
    if _devanagari_share(text) >= DEVANAGARI_SHARE:
        return Detection("hi", "rule", 1.0, n)
    if (
        isinstance(llm_label, str)
        and llm_label in LANGUAGES
        and isinstance(llm_confidence, int | float)
        and not isinstance(llm_confidence, bool)
        and llm_confidence >= LLM_MIN_CONFIDENCE
    ):
        return Detection(llm_label, "llm", float(min(llm_confidence, 1.0)), n)
    hit_words = [w for w in lower if w in HINGLISH_WORDS]
    if (
        n
        and len(set(hit_words)) >= HEURISTIC_MIN_HITS
        and len(hit_words) / n >= HEURISTIC_MIN_SHARE
    ):
        return Detection("hi-Latn", "heuristic", min(0.95, 0.5 + len(hit_words) / n), n)
    if n >= MIN_WORDS_TO_SWITCH and not hit_words:
        english = sum(1 for w in lower if w in ENGLISH_WORDS)
        if english / n >= 0.5:
            return Detection(DEFAULT_LANGUAGE, "heuristic", 0.85, n)
    return Detection(DEFAULT_LANGUAGE, "default", 0.5, n)


def _audit(session: Session, case, event: str, det: Detection, previous: str | None) -> None:
    audit.record(
        session,
        case.tenant_id,
        actor_type="system",
        actor_id=None,
        event=event,
        entity_type="case",
        entity_id=case.id,
        payload={
            "label": det.label,
            "source": det.source,
            "confidence": round(det.confidence, 2),
            "previous": previous,
        },
    )


def observe(
    session: Session,
    case,
    text: str,
    *,
    llm_label: object = None,
    llm_confidence: object = None,
    allow_heuristic: bool = True,
) -> str | None:
    """Apply one customer message to the case's language. Returns the case's language after.

    `allow_heuristic=False` is the first look in agents mode (before the classifier has run):
    only the Devanagari rule may decide then, otherwise the language stays unset until the
    classifier's own answer arrives (observe is called again with it).
    """
    from app.core.models import Customer

    det = detect(text, llm_label, llm_confidence)
    current = case.language
    if current is None:
        if det.source == "rule" or allow_heuristic or det.source == "llm":
            if det.source == "default":
                # Nothing to go on: the customer's old stored choice, then English.
                pref = session.get(Customer, case.customer_id)
                if det.words < MIN_WORDS_TO_SWITCH and pref is not None:
                    det = Detection(
                        pref.preferred_language
                        if pref.preferred_language in LANGUAGES
                        else DEFAULT_LANGUAGE,
                        "default",
                        det.confidence,
                        det.words,
                    )
            case.language = det.label
            case.language_pending = None
            _audit(session, case, "case.language_set", det, None)
        return case.language
    if det.label == current:
        case.language_pending = None
        return current
    if det.words < MIN_WORDS_TO_SWITCH and det.source != "rule":
        return current  # too short to mean anything
    if det.source == "rule" and det.words <= 2:
        return current  # "haan"-sized replies never move it, even in Devanagari
    if det.source == "rule":  # one Devanagari message switches at once
        case.language, case.language_pending = det.label, None
        _audit(session, case, "case.language_changed", det, current)
    elif det.source != "default" and det.confidence >= SWITCH_MIN_CONFIDENCE:
        if case.language_pending == det.label:
            case.language, case.language_pending = det.label, None
            _audit(session, case, "case.language_changed", det, current)
        else:
            case.language_pending = det.label
    return case.language
