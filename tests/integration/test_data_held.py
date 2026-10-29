"""S8.5a: "what we hold" for the signed-in customer, and the privacy contact.

Runs for every tenant and names none. Each test builds the customers it needs and removes them
afterwards (fixtures reused from the data-rights and retention tests).
"""

import uuid

import pytest

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES, TEMPLATES
from app.core.models import Customer
from app.core.settings_resolver import effective_settings
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine import data_held
from tests.integration import test_retention as ret
from tests.integration.test_data_rights import SimpleId, people, slug, staff  # noqa: F401
from tests.integration.test_retention import _case, _money, _order

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
        _order(s, tid, made, SimpleId(a), 10)
        for _ in range(3):
            _order(s, tid, made, SimpleId(b), 10)
        case_a = _case(s, tid, made, SimpleId(a), status="closed", age_days=10)
        _money(s, tid, case_a)
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
    assert other["orders"]["count"] == 3 and other["messages"]["count"] == 4
    assert other["consents"]["count"] == 0 and other["remedies"]["count"] == 0


def test_retention_comes_from_tenant_settings(api, app_engine, tid, people):  # noqa: F811
    _, auth = people()
    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    items = _by_key(api.get("/me/data-held", headers=auth).json())
    assert str(max(settings["support_retention_days"], 365)) in items["messages"]["retention"]
    assert str(settings["payment_retention_years"]) in items["orders"]["retention"]


def test_processors_and_contact_come_from_settings(api, app_engine, tid, people):  # noqa: F811
    _, auth = people()
    with tenant_session(tid, app_engine) as s:
        settings = effective_settings(s)
    body = api.get("/me/data-held", headers=auth).json()
    assert body["processors"] == settings["data_processors"] and body["processors"]
    c = body["contact"]
    assert c["label"] == "Privacy contact"
    assert c["name"] == settings["privacy_contact_name"]
    assert c["email"] == settings["privacy_contact_email"]
    assert c["response_target_days"] == settings["grievance_target_days"] == 30
    assert c["legal_ceiling_days"] == settings["privacy_legal_ceiling_days"] == 90
    assert "30" in c["response_text"] and "90" in c["response_text"]


def test_not_kept_line_is_hidden_unless_a_setting_backs_it(api, app_engine, tid, made, people):  # noqa: F811
    cid, auth = people()
    assert api.get("/me/data-held", headers=auth).json()["not_kept"] == []  # default: hidden
    with tenant_session(tid, app_engine) as s:
        customer = s.get(Customer, cid)
        settings = effective_settings(s)
        assert data_held.what_we_hold(s, customer, settings)["not_kept"] == []
        backed = {**settings, "data_not_kept": ["card_numbers"]}
        assert len(data_held.what_we_hold(s, customer, backed)["not_kept"]) == 1
        # An unknown claim key is never shown, even if a setting lists it.
        unknown = {**settings, "data_not_kept": ["we_never_sell_data"]}
        assert data_held.what_we_hold(s, customer, unknown)["not_kept"] == []


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

