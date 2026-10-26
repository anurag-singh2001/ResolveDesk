"""Privacy contact and grievance requests (S5.5), for every tenant: the contact is the caller's
own tenant's, a privacy request goes to a person with templated text and no payout, and the
sweeper flags it once at 75% of the internal target."""

import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    AuditEvent,
    Case,
    Customer,
    Ticket,
    Transaction,
    User,
)
from app.core.tenancy import tenant_id_for
from app.engine.privacy import DUE_SOON_EVENT, PRIVACY_CATEGORY
from app.engine.sweeper import sweep_tenant
from tests.helpers import login


@pytest.fixture
def world(api, app_engine, maint_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    customer = next(u for u in cfg.users if u.role == "customer")
    hq_email = next(u.email for u in cfg.users if u.role == "hq_owner")
    with tenant_session(tid, app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == customer.email))
        customer_id = s.scalar(select(Customer.id).where(Customer.user_id == user_id))
        order_id = s.scalars(
            select(Transaction.id)
            .where(Transaction.customer_id == customer_id)
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
    w = {
        "cfg": cfg,
        "tid": tid,
        "order_id": order_id,
        "customer": login(api, cfg.slug, customer.email),
        "hq": login(api, cfg.slug, hq_email),
    }
    yield w
    with tenant_session(tid, maint_engine) as s:
        case_ids = select(Case.id).where(Case.tenant_id == tid, Case.transaction_id == order_id)
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(case_ids)))
        s.execute(delete(Case).where(Case.tenant_id == tid, Case.transaction_id == order_id))


def _open_privacy(api, w):
    resp = api.post(
        "/cases",
        headers=w["customer"],
        json={
            "transaction_id": str(w["order_id"]),
            "category": PRIVACY_CATEGORY,
            "message": "Please tell me what data you hold about me.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_privacy_contact_is_the_callers_own_tenants_for_every_role(api, seeded, tenant):
    cfg = seeded[tenant.name]
    expected = {
        "name": cfg.settings.org["privacy_contact_name"],
        "email": cfg.settings.org["privacy_contact_email"],
    }
    assert expected["email"]
    others = {
        c.settings.org["privacy_contact_email"] for c in seeded.values() if c.slug != cfg.slug
    }
    for user in cfg.users:
        resp = api.get("/meta/privacy", headers=login(api, cfg.slug, user.email))
        assert resp.status_code == 200
        assert resp.json() == expected
        assert resp.json()["email"] not in others


def test_privacy_contact_needs_a_valid_token(api):
    assert api.get("/meta/privacy").status_code == 401


def test_a_privacy_request_goes_to_a_person_with_templated_text(api, app_engine, world):
    w = world
    out = _open_privacy(api, w)
    assert out["category"] == PRIVACY_CATEGORY
    assert out["stage"] == "escalated"
    assert out["proposal_id"] is None and out["action"] is None and out["amount_paise"] is None
    with tenant_session(w["tid"], app_engine) as s:
        assert (
            s.scalar(
                select(ActionProposal.id).where(ActionProposal.case_id == uuid.UUID(out["id"]))
            )
            is None
        )
        reason = s.scalar(
            select(AuditEvent.payload["reason"].astext).where(
                AuditEvent.entity_id == uuid.UUID(out["id"]), AuditEvent.event == "case.escalate"
            )
        )
    assert "privacy" in reason
    text = out["message"]
    org = w["cfg"].settings.org
    assert org["privacy_contact_email"] in text and org["privacy_contact_name"] in text
    assert re.search(r"respond by \d{1,2} [A-Z][a-z]{2} \d{4}\.", text)
    again = api.get(f"/cases/{out['id']}", headers=w["customer"]).json()
    assert again["message"] == text


def test_customer_text_never_calls_the_internal_target_legal(api, world):
    out = _open_privacy(api, world)
    lowered = out["message"].lower()
    for banned in ("statutory", "legally", "law requires", "by law", "legal deadline"):
        assert banned not in lowered
    assert "internal target" in lowered


def test_due_soon_fires_once_at_75_percent_and_not_before(api, app_engine, world):
    w = world
    out = _open_privacy(api, w)
    case_id = uuid.UUID(out["id"])
    with tenant_session(w["tid"], app_engine) as s:
        opened = s.get(Case, case_id).opened_at
    # 30-day default target: 22.5 days is the 75% mark.
    before = opened + timedelta(days=22)
    report = sweep_tenant(app_engine, w["tid"], now=before, min_age=timedelta(0))
    assert str(case_id) not in report.grievances_flagged

    at = opened + timedelta(days=23)
    first = sweep_tenant(app_engine, w["tid"], now=at, min_age=timedelta(0))
    assert str(case_id) in first.grievances_flagged
    second = sweep_tenant(app_engine, w["tid"], now=at + timedelta(days=1), min_age=timedelta(0))
    assert str(case_id) not in second.grievances_flagged

    events = api.get(f"/cases/{case_id}/events", headers=w["hq"]).json()
    flagged = [e for e in events if e["event"] == DUE_SOON_EVENT]
    assert len(flagged) == 1
    assert flagged[0]["payload"]["target_days"] == 30
    # The customer's text is unchanged by the flag.
    assert api.get(f"/cases/{case_id}", headers=w["customer"]).json()["message"] == out["message"]


def test_a_closed_privacy_case_is_not_flagged(api, app_engine, world):
    w = world
    out = _open_privacy(api, w)
    case_id = uuid.UUID(out["id"])
    with tenant_session(w["tid"], app_engine) as s:
        case = s.get(Case, case_id)
        opened = case.opened_at
        case.status = "resolved"
    report = sweep_tenant(
        app_engine, w["tid"], now=opened + timedelta(days=40), min_age=timedelta(0)
    )
    assert str(case_id) not in report.grievances_flagged
