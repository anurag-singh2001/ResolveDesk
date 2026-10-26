# ruff: noqa: F811 (pytest fixtures imported from test_cases_api)
"""S5.6: the customer's language choice and the messages that follow it, for every tenant."""

import pytest
from sqlalchemy import select

from app.core import i18n
from app.core.db import tenant_session
from app.core.i18n import LANGUAGES, MONEY_STATUS_KEYS, TEMPLATES, t
from app.core.models import AuditEvent
from app.core.money import format_inr
from tests.helpers import login
from tests.integration.test_cases_api import _open, clean_mocks, flow  # noqa: F401


@pytest.fixture
def choose(api, flow):
    """Set the logged-in customer's language; always put it back to the default afterwards."""

    def _set(lang):
        resp = api.put("/me/preferences", headers=flow["customer"], json={"language": lang})
        assert resp.status_code == 200, resp.text
        return resp.json()

    yield _set
    api.put("/me/preferences", headers=flow["customer"], json={"language": "en"})


def test_default_is_english_and_the_customer_can_change_it(api, flow, choose):
    url, hdr = "/me/preferences", flow["customer"]
    assert api.get(url, headers=hdr).json() == {"language": "en"}
    for lang in LANGUAGES:
        assert choose(lang) == {"language": lang}
        assert api.get(url, headers=hdr).json() == {"language": lang}


def test_unsupported_codes_are_refused(api, flow):
    for bad in ("fr", "HI", "", None, 3):
        resp = api.put("/me/preferences", headers=flow["customer"], json={"language": bad})
        assert resp.status_code == 422
    assert api.put("/me/preferences", headers=flow["customer"], json={}).status_code == 422
    assert api.get("/me/preferences", headers=flow["customer"]).json() == {"language": "en"}


def test_staff_have_no_preferences_and_anonymous_is_refused(api, flow):
    assert api.get("/me/preferences", headers=flow["hq"]).status_code == 404
    put = api.put("/me/preferences", headers=flow["hq"], json={"language": "hi"})
    assert put.status_code == 404
    assert api.get("/me/preferences").status_code in (401, 403)


def test_a_change_is_audited_with_old_and_new_value_only(api, app_engine, flow, choose):
    choose("hi")
    choose("hi")  # same value again: nothing new to record
    with tenant_session(flow["tid"], app_engine) as s:
        payloads = s.scalars(
            select(AuditEvent.payload).where(AuditEvent.event == "customer.language_changed")
        ).all()
    assert {"before": "en", "after": "hi"} in payloads


@pytest.mark.parametrize("lang", LANGUAGES)
def test_status_and_timeline_follow_the_customers_choice(api, flow, choose, lang):
    choose(lang)
    opened = _open(api, flow)
    assert opened["message"] == t("status.awaiting_approval", lang)
    got = api.get(f"/cases/{opened['id']}", headers=flow["customer"]).json()
    assert got["message"] == t("status.awaiting_approval", lang)
    steps = api.get(f"/cases/{opened['id']}/timeline", headers=flow["customer"]).json()
    assert steps[0]["title"] == t("tl.received.title", lang)
    assert steps[0]["text"] == t("tl.received.text", lang)
    proposed = next(s for s in steps if s["stage"] == "awaiting_approval")
    assert proposed["title"] == t("tl.proposed.title", lang)
    assert format_inr(flow["missing_paise"]) in proposed["text"]  # the amount is the same


@pytest.mark.parametrize("lang", LANGUAGES)
def test_a_confirmed_refund_says_so_in_each_language_with_the_same_amount(api, flow, choose, lang):
    choose(lang)
    opened = _open(api, flow)
    api.post(
        f"/approvals/{opened['proposal_id']}/decision",
        headers=flow["hq"],
        json={"decision": "approved"},
    )
    got = api.get(f"/cases/{opened['id']}", headers=flow["customer"]).json()
    assert got["stage"] == "confirmed"
    amount = format_inr(got["amount_paise"])
    assert got["message"] == t("status.refund_confirmed", lang, amount=amount)
    assert got["message"] != t("status.refund_processing", lang, amount=amount)


def test_a_missing_key_in_the_chosen_language_shows_english(api, flow, choose, monkeypatch):
    choose("hi")
    key = "status.awaiting_approval"
    monkeypatch.setattr(i18n, "TEMPLATES", {**TEMPLATES, key: {"en": TEMPLATES[key]["en"]}})
    opened = _open(api, flow)
    assert opened["message"] == TEMPLATES[key]["en"]


def test_a_customers_choice_does_not_leak_to_another_customer(api, flow, choose):
    choose("hi")
    others = [
        u for u in flow["cfg"].users if u.role == "customer" and u.email != flow["customer_email"]
    ]
    if not others:
        pytest.skip("tenant has a single customer")
    other = login(api, flow["cfg"].slug, others[0].email)
    assert api.get("/me/preferences", headers=other).json() == {"language": "en"}


def test_the_five_statuses_are_distinct_in_every_language():
    for lang in LANGUAGES:
        assert len({t(k, lang, amount="x") for k in MONEY_STATUS_KEYS.values()}) == 5
