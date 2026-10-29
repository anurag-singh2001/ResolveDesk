# ruff: noqa: F811
"""S8.5b: consent shown as benefits. Runs for every tenant and names none.

The cap shown must be the one the campaign audience enforces; help messages carry no switch;
every switch starts off; withdrawing is one call that writes a history record; one customer
cannot change another's choice. Fixtures are reused from the data-rights tests.
"""

from sqlalchemy import select

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES, TEMPLATES
from app.core.models import Consent, Customer
from app.engine import consent_benefits
from app.engine import data_rights as privacy
from app.modules.growth.campaigns import FREQUENCY_CAP_DAYS
from tests.integration import test_retention as ret
from tests.integration.test_data_rights import people, slug, staff  # noqa: F401

made = ret.made
tid = ret.tid


def test_each_purpose_has_benefit_sent_cap_and_channel_and_starts_off(api, people):
    _, auth = people()
    body = api.get("/me/consents", headers=auth).json()
    b = body["benefits"]
    assert [p["purpose"] for p in b["purposes"]] == list(privacy.PURPOSES)
    for p in b["purposes"]:
        assert p["granted"] is False  # no pre-ticked choice
        assert (
            p["title"] and p["benefit"] and p["sent"] and p["channel_label"] and p["switch_label"]
        )
        # The cap shown is the constant the audience selection enforces, not a setting.
        assert p["cap_days"] == FREQUENCY_CAP_DAYS
        assert str(FREQUENCY_CAP_DAYS) in p["cap"]
        assert p["state_label"] == b["headings"]["off"]
    assert {p["channel"] for p in b["purposes"]} == set(privacy.CHANNELS)


def test_help_messages_are_always_on_with_no_switch_and_the_note_is_present(api, people):
    _, auth = people()
    b = api.get("/me/consents", headers=auth).json()["benefits"]
    assert b["always_on"]["title"] and b["always_on"]["badge"]
    assert "always on" in b["always_on"]["body"].lower()
    assert "help" in b["headings"]["note"].lower()
    # No consent purpose exists for help: the endpoint refuses to record one.
    assert (
        api.post("/me/consents/support", json={"granted": False}, headers=auth).status_code == 404
    )
    assert all(p["purpose"] != "support" for p in b["purposes"])


def test_withdrawing_is_one_call_that_writes_a_labelled_record(api, app_engine, tid, people):
    cid, auth = people()
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth)
    out = api.post("/me/consents/marketing", json={"granted": False}, headers=auth).json()
    assert out["benefits"]["purposes"][0]["granted"] is False
    hist = out["benefits"]["history_labelled"]
    assert [h["granted"] for h in hist] == [True, False]
    assert hist[-1]["notice_version"] == privacy.NOTICE_VERSION
    assert hist[-1]["purpose_label"] and hist[-1]["channel_label"] and hist[-1]["action_label"]
    with tenant_session(tid, app_engine) as s:  # the row the growth sender reads
        row = s.scalar(select(Consent).where(Consent.customer_id == cid))
        assert row is not None and row.granted is False


def test_one_customer_cannot_change_anothers_choice(api, app_engine, tid, people):
    a, auth_a = people("Alice Anand")
    b, auth_b = people("Bruno Bose")
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth_b)
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth_a)
    api.post("/me/consents/marketing", json={"granted": False}, headers=auth_a)
    with tenant_session(tid, app_engine) as s:
        states = {c.customer_id: c.granted for c in s.scalars(select(Consent))}
    assert states[a] is False and states[b] is True
    seen_b = api.get("/me/consents", headers=auth_b).json()["benefits"]
    assert [h["granted"] for h in seen_b["history_labelled"]] == [True]


def test_staff_cannot_read_or_change_a_customers_consent(api, tenant, slug, people):
    cid, _ = people()
    hq = staff(api, tenant, slug, "hq_owner")
    assert api.get("/me/consents", headers=hq).status_code == 403
    assert api.post("/me/consents/marketing", json={"granted": True}, headers=hq).status_code == 403


def test_copy_follows_the_customers_language(api, app_engine, tid, people):
    cid, auth = people()
    seen = {}
    for lang in LANGUAGES:
        with tenant_session(tid, app_engine) as s:
            s.get(Customer, cid).preferred_language = lang
        b = api.get("/me/consents", headers=auth).json()["benefits"]
        assert b["language"] == lang
        seen[lang] = b["purposes"][0]["benefit"]
    assert len(set(seen.values())) == len(LANGUAGES)


def test_every_consent_string_exists_in_all_languages_without_em_dashes():
    keys = [k for k in TEMPLATES if k.startswith("consent.")]
    assert keys
    for k in keys:
        assert set(TEMPLATES[k]) == set(LANGUAGES), k
        for text in TEMPLATES[k].values():
            assert text.strip() and "—" not in text, k
    for purpose in privacy.PURPOSES:
        for part in ("title", "benefit", "sent", "switch"):
            assert f"consent.{purpose}.{part}" in TEMPLATES
    for h in consent_benefits.HEADINGS:
        assert f"consent.h.{h}" in TEMPLATES


def test_the_data_export_carries_the_plain_state_without_page_copy(api, people):
    _, auth = people()
    out = api.get("/me/data-export", headers=auth).json()
    assert "benefits" not in out["consents"]
    assert out["consents"]["consents"][0]["granted"] is False
