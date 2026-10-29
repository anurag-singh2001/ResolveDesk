"""Consent shown as benefits (S8.5b, R2). Customer-facing wording for each marketing purpose.

Facts stated here are decided in CODE, never by a tenant setting (same rule as data_held):
the frequency cap shown is the constant the campaign audience actually enforces, so the page
cannot promise a limit the sender does not keep. Help messages are listed as always on with no
switch because support is not consent-based (app/engine/data_rights.py). Nothing here names a
tenant; copy lives in app/core/i18n.py.
"""

from typing import Any

from app.core.i18n import normalize, t
from app.engine import data_rights as privacy
from app.modules.growth.campaigns import FREQUENCY_CAP_DAYS

HEADINGS = ("title", "intro", "history", "note", "on", "off", "notice")

# Every purpose needs benefit copy; fail loudly at import if one is added without it.
assert privacy.PURPOSES == ("marketing",), "add copy for every consent purpose in i18n"


def _hist(e: Any, lang: str) -> dict[str, Any]:
    return {
        "purpose": e.purpose,
        "channel": e.channel,
        "granted": e.granted,
        "source": e.source,
        "notice_version": e.notice_version,
        "at": e.created_at,
        "purpose_label": t(f"consent.{e.purpose}.title", lang),
        "channel_label": t(f"consent.channel.{e.channel}", lang),
        "action_label": t("consent.hist.granted" if e.granted else "consent.hist.withdrawn", lang),
    }


def build(language: object, current: list[Any], events: list[Any]) -> dict[str, Any]:
    """`current` are rows with purpose, channel, granted; `events` are ConsentEvent rows.
    Returns the copy block the page renders."""
    lang = normalize(language)
    purposes = []
    for c in current:
        purposes.append(
            {
                "purpose": c.purpose,
                "channel": c.channel,
                "granted": c.granted,
                "title": t(f"consent.{c.purpose}.title", lang),
                "benefit": t(f"consent.{c.purpose}.benefit", lang),
                "sent": t(f"consent.{c.purpose}.sent", lang),
                "cap": t("consent.cap", lang, days=FREQUENCY_CAP_DAYS),
                "cap_days": FREQUENCY_CAP_DAYS,
                "channel_label": t(f"consent.channel.{c.channel}", lang),
                "switch_label": t(f"consent.{c.purpose}.switch", lang),
                "state_label": t("consent.state.on" if c.granted else "consent.state.off", lang),
            }
        )
    return {
        "language": lang,
        "headings": {k: t(f"consent.h.{k}", lang) for k in HEADINGS},
        "always_on": {
            "title": t("consent.help.title", lang),
            "body": t("consent.help.body", lang),
            "badge": t("consent.help.badge", lang),
        },
        "purposes": purposes,
        "history_labelled": [_hist(e, lang) for e in events],
    }
