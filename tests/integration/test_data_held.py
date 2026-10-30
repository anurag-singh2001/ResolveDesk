# ruff: noqa: F811
"""S8.5a: "what we hold" for the signed-in customer, and the privacy contact.

Runs for every tenant and names none. Each test builds the customers it needs and removes them
afterwards (fixtures reused from the data-rights and retention tests).
"""

import uuid

import pytest

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES, TEMPLATES
from app.core.models import Consent, Customer, Ticket, TicketMessage
from app.core.settings_resolver import effective_settings
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine import data_held
from app.engine.retention import retention_days
from tests.integration import test_retention as ret
from tests.integration.test_data_rights import SimpleId, people, slug, staff  # noqa: F401
from tests.integration.test_retention import NOW, _case, _money, _order

made = ret.made
tid = ret.tid


def _by_key(body):
    return {i["key"]: i for i in body["items"]}


def test_each_item_has_purpose_retention_and_the_customers_own_count(
    api, app_engine, tid, made, people
):  # noqa: F811
    a, auth_a = people("Alice Anand")
    b, auth_b = people("Bruno Bose")
    with tenant_session(tid, app_engine) as s:
        order_a = _order(s, tid, made, SimpleId(a), 10)
        for _ in range(3):
            _order(s, tid, made, SimpleId(b), 10)
        case_a = _case(s, tid, made, SimpleId(a), status="closed", age_days=10)
        _money(s, tid, case_a, execution="succeeded")  # approved and run: counted
        _money(s, tid, case_a, approved=False)  # only proposed: not counted
        # A ticket of B that points at A's order must not count towards A (shared reference).
        shared = Ticket(
            tenant_id=tid,
            customer_id=b,
            transaction_id=order_a.id,
            category="late_delivery",
            status="open",
            channel="app",
            opened_at=NOW,
        )
        s.add(shared)
        s.flush()
        made["tickets"].append(shared.id)
        s.add(
            TicketMessage(
                tenant_id=tid, ticket_id=shared.id, author="customer", body="hi", sent_at=NOW
            )
        )
        _case(s, tid, made, SimpleId(b), status="closed", age_days=10)
        _case(s, tid, made, SimpleId(b), status="closed", age_days=10)
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth_a)

    r = api.get("/me/data-held", headers=auth_a)
    assert r.status_code == 200, r.text
    body = r.json()
    items = _by_key(body)
    assert {"name", "phone", "orders", "messages", "payments", "remedies", "consents"} <= set(items)
    for item in body["items"]:
        assert item["purpose"] and item["retention"] and item["use"] in ("help", "marketing")
        assert item["retention_provisional"] is True  # labelled provisional until confirmed
    assert body["provisional_label"]
    # Only A's own counts: B has more orders, cases and messages.
    assert items["orders"]["count"] == 1
    assert items["messages"]["count"] == 2  # one case, two messages
    assert items["remedies"]["count"] == 1
    assert items["consents"]["count"] == 1
    assert items["consents"]["use"] == "marketing" and items["orders"]["use"] == "help"
    # The phone is masked, the name is the customer's own.
    assert items["name"]["value"] == "Alice Anand"
    assert items["phone"]["value"].endswith("3210") and "9876543210" not in r.text
    assert "Bruno" not in r.text and "Bose" not in r.text
    # The other customer sees their own counts.
    other = _by_key(api.get("/me/data-held", headers=auth_b).json())
    assert other["orders"]["count"] == 3 and other["messages"]["count"] == 5
    assert other["consents"]["count"] == 0 and other["remedies"]["count"] == 0


def test_offer_choices_count_the_choice_on_record_not_the_history(
    api,
    app_engine,
    tid,
    people,  # noqa: F811
):
    """Seeded customers have a choice (a consent row) with no history event behind it; the page
    must not say "0 on record" while the offers switch shows On."""
    cid, auth = people()
    with tenant_session(tid, app_engine) as s:
        for purpose in ("marketing", "service"):
            s.add(
                Consent(
                    tenant_id=tid,
                    customer_id=cid,
                    channel="whatsapp",
                    purpose=purpose,
                    granted=True,
                )
            )
    items = _by_key(api.get("/me/data-held", headers=auth).json())
    assert items["consents"]["count"] == 1  # the one offers choice; "service" has no switch
    assert "1" in items["consents"]["summary"]


def test_retention_comes_from_tenant_settings(api, app_engine, tid, people):  # noqa: F811
    _, auth = people()
    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    items = _by_key(api.get("/me/data-held", headers=auth).json())
    assert str(retention_days(settings)) in items["messages"]["retention"]
    assert str(settings["payment_retention_years"]) in items["orders"]["retention"]
    # The job redacts a signed-in customer's contact data never, so no day count is promised.
    for key in ("name", "phone"):
        assert not any(ch.isdigit() for ch in items[key]["retention"])
    assert "removed after" not in items["messages"]["retention"].lower()  # only "may be"


def test_a_bad_retention_override_cannot_crash_or_mislead(app_engine, tid, people):  # noqa: F811
    cid, _ = people()
    with tenant_session(tid, app_engine) as s:
        customer = s.get(Customer, cid)
        settings = effective_settings(s)
        for bad in ("lots", None, -3, True):
            body = data_held.what_we_hold(s, customer, {**settings, "payment_retention_years": bad})
            items = _by_key(body)
            assert str(data_held.DEFAULT_RECORD_YEARS) in items["orders"]["retention"]
            assert items["orders"]["retention_provisional"] is True


def test_processors_and_contact_come_from_settings(api, app_engine, tid, people):  # noqa: F811
    _, auth = people()
    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    body = api.get("/me/data-held", headers=auth).json()
    assert body["processors"] == [
        {k: p[k] for k in ("name", "role", "data")} for p in settings["data_processors"]
    ]
    assert body["processors"] and body["provisional_label"]
    c = body["contact"]
    assert c["label"] == "Privacy and grievance contact"
    assert c["name"] == settings["privacy_contact_name"]
    assert c["email"] == settings["privacy_contact_email"]
    assert c["response_target_days"] == settings["grievance_target_days"] == 30
    assert "legal_ceiling_days" not in c and c["acknowledge_hours"] == 48
    assert c["configured"] is True
    assert "30" in c["response_text"] and "48" in c["response_text"]
    assert "legal" not in c["response_text"].lower() and "90" not in c["response_text"]


def test_not_kept_claims_need_code_confirmation_and_the_setting(
    api, app_engine, tid, people, monkeypatch
):
    cid, auth = people()
    shown = api.get("/me/data-held", headers=auth).json()["not_kept"]
    assert shown == ["We never see or store your card number, CVV or UPI PIN."]  # confirmed by scan
    with tenant_session(tid, app_engine) as s:
        customer = s.get(Customer, cid)
        settings = effective_settings(s)

        def claims(value):
            return data_held.what_we_hold(s, customer, {**settings, "data_not_kept": value})[
                "not_kept"
            ]

        # A tenant override alone never enables a claim: with nothing confirmed in code, none shows.
        monkeypatch.setattr(data_held, "CONFIRMED_NOT_KEPT", frozenset())
        assert claims(["card_numbers", "upi_details"]) == []
        monkeypatch.setattr(data_held, "CONFIRMED_NOT_KEPT", frozenset({"card_numbers"}))
        assert len(claims(["card_numbers"])) == 1  # confirmed in code AND listed
        assert claims(["upi_details"]) == []  # listed but not confirmed
        assert claims([]) == []  # confirmed but the tenant does not list it
        assert claims(["we_never_sell_data"]) == []  # unknown key


def test_overrides_cannot_raise_the_ceiling_or_drop_the_provisional_label(app_engine, tid, people):
    cid, _ = people()
    with tenant_session(tid, app_engine) as s:
        customer = s.get(Customer, cid)
        settings = effective_settings(s)
        hostile = {
            **settings,
            "privacy_legal_ceiling_days": 365,
            "retention_provisional": False,
            "grievance_target_days": 500,
        }
        body = data_held.what_we_hold(s, customer, hostile)
        assert "legal_ceiling_days" not in body["contact"]
        assert body["contact"]["response_target_days"] <= 90
        assert "365" not in body["contact"]["response_text"]
        assert body["provisional_label"]
        assert all(i["retention_provisional"] for i in body["items"])


def test_contact_line_says_not_set_when_no_email(app_engine, tid, people):
    cid, _ = people()
    with tenant_session(tid, app_engine) as s:
        customer = s.get(Customer, cid)
        settings = effective_settings(s)
        c = data_held.what_we_hold(s, customer, {**settings, "privacy_contact_email": ""})[
            "contact"
        ]
    assert c["configured"] is False and c["email"] == "" and c["name"] == ""
    assert c["response_text"] == "Not set yet." and "30" not in c["response_text"]


def test_every_copy_key_the_page_uses_exists_in_all_languages():
    keys = [f"held.h.{k}" for k in data_held.HEADINGS]
    for item in data_held.ITEMS:
        keys += [f"held.label.{item.key}", f"held.purpose.{item.key}", f"held.use.{item.use}"]
    keys += [f"held.not_kept.{k}" for k in data_held.KNOWN_NOT_KEPT]
    keys += [
        "held.ret.messages", "held.ret.contact", "held.ret.records", "held.ret.consents",
        "held.provisional", "held.count", "held.contact.label", "held.contact.target",
        "held.contact.unset",
    ]  # fmt: skip
    for key in keys:
        for lang in LANGUAGES:
            assert TEMPLATES[key].get(lang, "").strip(), (key, lang)
    for key in TEMPLATES:  # nothing under held.* is unused by the page
        if key.startswith("held."):
            assert key in keys, key


def test_copy_follows_the_customers_language(api, app_engine, tid, people):  # noqa: F811
    cid, auth = people()
    seen = {}
    for lang in LANGUAGES:
        with tenant_session(tid, app_engine) as s:
            s.get(Customer, cid).preferred_language = lang
        body = api.get("/me/data-held", headers=auth).json()
        assert body["language"] == lang
        seen[lang] = body["items"][0]["label"]
    assert len(set(seen.values())) == 3
    assert all(k in TEMPLATES for k in ("held.label.orders", "held.contact.target"))


@pytest.mark.parametrize("role", ["hq_owner", "location_manager"])
def test_staff_cannot_use_it(api, tenant, slug, role):  # noqa: F811
    try:
        auth = staff(api, tenant, slug, role)
    except StopIteration:
        pytest.skip("no such role in this tenant")
    assert api.get("/me/data-held", headers=auth).status_code == 403


def test_anonymous_is_refused(api):
    assert api.get("/me/data-held").status_code in (401, 403)


def test_never_shows_another_tenants_customer(api, maint_engine, people, tenant):  # noqa: F811
    _, auth = people("Alice Anand")
    other = next(p for p in tenant_dirs() if p.name != tenant.name)
    other_tid = tenant_id_for(load_tenant(other).slug)
    ref = f"xt-{uuid.uuid4().hex[:10]}"
    with tenant_session(other_tid, maint_engine) as s:
        c = Customer(tenant_id=other_tid, external_ref=ref, name="Zed Zoo", phone="9000000001")
        s.add(c)
        s.flush()
        cid = c.id
    try:
        text = api.get("/me/data-held", headers=auth).text
        assert "Zed Zoo" not in text and "0000001" not in text and ref not in text
    finally:
        from sqlalchemy import delete

        with tenant_session(other_tid, maint_engine) as s:
            s.execute(delete(Customer).where(Customer.id == cid))


def test_a_rights_message_carries_the_contact(app_engine, tid):
    """Every privacy-request reply includes the tenant's contact (R6), in every language."""
    from datetime import UTC, datetime

    from app.engine.privacy import customer_message

    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    assert settings["privacy_contact_email"]
    for lang in LANGUAGES:
        text = customer_message(datetime.now(UTC), settings, lang)
        assert settings["privacy_contact_email"] in text
