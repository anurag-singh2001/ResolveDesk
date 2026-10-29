# ruff: noqa: F811
"""S8.5c: the readable data export for the signed-in customer.

Runs for every tenant and names none. Fixtures come from the data-rights and retention tests.
"""

import json
import uuid

from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES
from app.core.models import AuditEvent, Customer, Transaction
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from tests.integration import test_retention as ret
from tests.integration.test_data_rights import SimpleId, people, slug, staff  # noqa: F401
from tests.integration.test_retention import _case, _money, _order

made = ret.made
tid = ret.tid


def _flat(body) -> list[str]:
    """Every label and value in the readable body, as text."""
    out = []
    for sec in body["sections"]:
        for rec in sec["records"] + sec.get("history", []):
            out += [f["value"] for f in rec] + [f["label"] for f in rec]
    return out


def test_readable_has_only_the_callers_data_with_labels(api, app_engine, tid, made, people):
    a, auth_a = people("Alice Anand")
    b, auth_b = people("Bruno Bose")
    with tenant_session(tid, app_engine) as s:
        order_a = _order(s, tid, made, SimpleId(a), 10)
        order_b = _order(s, tid, made, SimpleId(b), 10)
        _case(s, tid, made, SimpleId(a), status="closed", age_days=10)
        _case(s, tid, made, SimpleId(b), status="closed", age_days=10)
        ref_a = s.get(Transaction, order_a.id).external_ref
        ref_b = s.get(Transaction, order_b.id).external_ref
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth_a)
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth_b)

    r = api.get("/me/data-export/readable", headers=auth_a)
    assert r.status_code == 200, r.text
    body = r.json()
    keys = [s["key"] for s in body["sections"]]
    assert keys == ["details", "orders", "cases", "remedies", "choices", "processors"]
    sections = {s["key"]: s for s in body["sections"]}
    assert "Alice Anand" in _flat(body)
    assert ref_a in _flat(body)
    assert ref_b not in r.text and "Bruno" not in r.text
    assert len(sections["orders"]["records"]) == 1 and len(sections["cases"]["records"]) == 1
    # Each data section carries the S8.5a purpose and retention line, labelled provisional.
    for key in ("details", "orders", "cases", "remedies", "choices"):
        assert sections[key]["purpose"] and sections[key]["retention"]
        assert sections[key]["retention_provisional"] is True
    assert body["provisional_label"] and body["contact"]["response_text"]
    assert any(len(rec) == 3 for rec in sections["processors"]["records"])


def test_money_comes_from_paise_and_dates_have_month_names(api, app_engine, tid, made, people):
    a, auth = people("Alice Anand")
    with tenant_session(tid, app_engine) as s:
        order = _order(s, tid, made, SimpleId(a), 10)
        s.get(
            Transaction, order.id
        ).total_paise = 123456789  # 12,34,567.89 rupees: Indian grouping from integer paise
        case = _case(s, tid, made, SimpleId(a), status="closed", age_days=10)
        _money(s, tid, case, execution="succeeded", verified=True)  # a 100 paise refund
    body = api.get("/me/data-export/readable", headers=auth).json()
    values = _flat(body)
    assert "₹12,34,567.89" in values
    assert "₹1.00" in values  # the refund amount
    assert not any("123456789" in v for v in values)  # never raw paise
    placed = next(
        f["value"]
        for rec in body["sections"][1]["records"]
        for f in rec
        if f["label"] == "Placed on"
    )
    assert any(
        m in placed
        for m in (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
    )
    remedies = body["sections"][3]["records"]
    assert remedies and any(f["value"] == "Refund" for f in remedies[0])


def test_unconfirmed_money_is_not_reported_as_paid(api, app_engine, tid, made, people):
    a, auth = people("Alice Anand")
    with tenant_session(tid, app_engine) as s:
        case = _case(s, tid, made, SimpleId(a), status="open", age_days=1)
        _money(s, tid, case, execution=None)  # approved, nothing run yet
    body = api.get("/me/data-export/readable", headers=auth).json()
    rows = body["sections"][3]["records"]
    assert rows
    text = " ".join(f["value"] for rec in rows for f in rec).lower()
    assert "confirmed" not in text and "paid" not in text


def test_internal_fields_are_absent_from_both_exports(api, app_engine, tid, made, people):
    a, auth = people("Alice Anand")
    with tenant_session(tid, app_engine) as s:
        order = _order(s, tid, made, SimpleId(a), 10)
        case = _case(s, tid, made, SimpleId(a), status="closed", age_days=10)
        _money(s, tid, case, execution="succeeded", verified=True)
        ids = {str(order.id), str(case.id), str(tid), str(a)}
        s.flush()
    api.post("/me/consents/marketing", json={"granted": True}, headers=auth)
    for path in ("/me/data-export/readable", "/me/data-export"):
        text = api.get(path, headers=auth).text
        for forbidden in (
            "payload_hash",
            "idempotency",
            "approval",
            "prompt",
            "reasoning",
            "tenant_id",
        ):
            assert forbidden not in text, (path, forbidden)
        if path.endswith("readable"):  # code-only ids never appear (the JSON export keeps case ids)
            for i in ids:
                assert i not in text, (path, i)


def test_json_export_contract_is_unchanged(api, people):
    _, auth = people("Alice Anand")
    body = api.get("/me/data-export", headers=auth).json()
    assert set(body) == {"generated_at", "profile", "orders", "cases", "consents", "processors"}
    assert set(body["profile"]) == {"name", "phone", "email", "reference"}


def test_each_language_renders_and_hindi_uses_month_names(api, app_engine, tid, made, people):
    a, auth = people("Alice Anand")
    with tenant_session(tid, app_engine) as s:
        _order(s, tid, made, SimpleId(a), 10)
    for lang in LANGUAGES:
        r = api.put("/me/preferences", json={"language": lang}, headers=auth)
        assert r.status_code == 200, r.text
        body = api.get("/me/data-export/readable", headers=auth).json()
        assert body["language"] == lang
        assert body["title"] and body["sections"][0]["title"]
    hindi = api.get("/me/data-export/readable", headers=auth).json()
    assert any(ch >= "à¤€" for ch in hindi["title"])  # Devanagari for hi


def test_audit_event_has_no_personal_content(api, app_engine, tid, people):
    c, auth = people("Alice Anand")
    api.get("/me/data-export/readable", headers=auth)
    with tenant_session(tid, app_engine) as s:
        payloads = list(
            s.scalars(
                select(AuditEvent.payload).where(
                    AuditEvent.event == "data.exported", AuditEvent.entity_id == c
                )
            )
        )
    assert payloads == [{"format": "readable"}]
    assert "Alice" not in json.dumps(payloads)


def test_staff_and_anonymous_cannot_use_it(api, tenant, slug):
    assert api.get("/me/data-export/readable").status_code == 401
    auth = staff(api, tenant, slug, "hq_owner")
    assert api.get("/me/data-export/readable", headers=auth).status_code == 403


def test_other_tenants_customer_never_appears(api, maint_engine, people, tenant):
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
        text = api.get("/me/data-export/readable", headers=auth).text
        assert ref not in text and "Zed Zoo" not in text and "9000000001" not in text
    finally:
        with tenant_session(other_tid, maint_engine) as s:
            s.execute(delete(Customer).where(Customer.id == cid))
