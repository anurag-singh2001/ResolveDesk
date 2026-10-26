"""DPDP retention (S5.1): old finished cases lose message text and customer contact data;
everything else (open or recent cases, held cases, money, approvals, audit) is left alone.
Runs per tenant under RLS, and twice changes nothing more."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update

from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    AuditEvent,
    Case,
    Customer,
    Execution,
    Payment,
    RefundOperation,
    Ticket,
    TicketMessage,
    Transaction,
    Verification,
)
from app.core.settings_resolver import effective_settings
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine.case_timeline import case_timeline
from app.engine.retention import (
    MESSAGE_MARKER,
    MIN_DAYS,
    NAME_MARKER,
    purge_tenant,
    retention_days,
)

NOW = datetime.now(UTC)
RAW = "my number is 9876543210 and mail me at someone@example.com"
PROTECTED = (Transaction, Payment, ActionProposal, Approval, Execution, Verification)


def test_retention_days_has_floor_and_default():
    assert retention_days({}) == 365
    assert retention_days({"support_retention_days": 30}) == MIN_DAYS
    assert retention_days({"support_retention_days": 400}) == 400
    assert retention_days({"support_retention_days": "x"}) == 365


@pytest.fixture
def tid(tenant, seeded_history):
    return tenant_id_for(load_tenant(tenant).slug)


@pytest.fixture
def made(maint_engine):
    """Rows a test created, removed afterwards (audit rows stay: append-only)."""
    rows = {"tid": [], "cases": [], "customers": [], "txns": []}
    yield rows
    for tid_ in set(rows["tid"]):
        with tenant_session(tid_, maint_engine) as s:
            tickets = select(Ticket.id).where(Ticket.case_id.in_(rows["cases"]))
            s.execute(delete(TicketMessage).where(TicketMessage.ticket_id.in_(tickets)))
            s.execute(delete(Ticket).where(Ticket.case_id.in_(rows["cases"])))
            s.execute(delete(Case).where(Case.id.in_(rows["cases"])))
            s.execute(delete(Transaction).where(Transaction.id.in_(rows["txns"])))
            s.execute(delete(Customer).where(Customer.id.in_(rows["customers"])))


def _customer(s, tid, made):
    c = Customer(
        tenant_id=tid,
        external_ref=f"ret-{uuid.uuid4().hex[:12]}",
        name="Real Person",
        phone="9876543210",
        email="someone@example.com",
    )
    s.add(c)
    s.flush()
    made["tid"].append(tid)
    made["customers"].append(c.id)
    return SimpleNamespace(id=c.id)


def _case(s, tid, made, customer, *, status, age_days, hold=False):
    t = NOW - timedelta(days=age_days)
    case = Case(
        tenant_id=tid,
        customer_id=customer.id,
        category="late_delivery",
        status=status,
        channel="app",
        opened_at=t,
        updated_at=t,
        legal_hold=hold,
    )
    s.add(case)
    s.flush()
    ticket = Ticket(
        tenant_id=tid,
        customer_id=customer.id,
        case_id=case.id,
        category="late_delivery",
        status="closed",
        channel="app",
        opened_at=t,
    )
    s.add(ticket)
    s.flush()
    for author in ("customer", "system"):
        s.add(TicketMessage(tenant_id=tid, ticket_id=ticket.id, author=author, body=RAW, sent_at=t))
    made["tid"].append(tid)
    made["cases"].append(case.id)
    return SimpleNamespace(id=case.id)


def _bodies(engine, tid, case_id):
    with tenant_session(tid, engine) as s:
        return s.scalars(
            select(TicketMessage.body)
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .where(Ticket.case_id == case_id)
        ).all()


def _customer_row(engine, tid, customer_id):
    with tenant_session(tid, engine) as s:
        c = s.get(Customer, customer_id)
        return c.name, c.phone, c.email


def _snapshot(engine, tid):
    with tenant_session(tid, engine) as s:
        out = {
            m.__tablename__: s.execute(select(*m.__table__.c).order_by(m.id)).all()
            for m in PROTECTED
        }
        out["refund_operations"] = s.execute(
            select(*RefundOperation.__table__.c).order_by(RefundOperation.id)
        ).all()
        out["audit"] = s.execute(
            select(AuditEvent.id, AuditEvent.payload, AuditEvent.event).order_by(AuditEvent.id)
        ).all()
    return out


def test_setting_default_is_in_the_pack(app_engine, tid):
    with tenant_session(tid, app_engine) as s:
        assert effective_settings(s)["support_retention_days"] == 365


def test_old_finished_case_redacted_recent_and_open_untouched(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        who = {k: _customer(s, tid, made) for k in ("old", "recent", "open", "closed_old")}
        old = _case(s, tid, made, who["old"], status="closed", age_days=400)
        resolved = _case(s, tid, made, who["closed_old"], status="resolved", age_days=500)
        recent = _case(s, tid, made, who["recent"], status="closed", age_days=30)
        open_ = _case(s, tid, made, who["open"], status="awaiting_info", age_days=900)
    before = _snapshot(app_engine, tid)

    report = purge_tenant(app_engine, tid, NOW)

    assert report.cases == 2 and report.messages == 4 and report.customers == 2
    for c in (old, resolved):
        assert _bodies(app_engine, tid, c.id) == [MESSAGE_MARKER] * 2
    for c in (recent, open_):
        assert _bodies(app_engine, tid, c.id) == [RAW] * 2
    assert _customer_row(app_engine, tid, who["old"].id) == (NAME_MARKER, None, None)
    assert _customer_row(app_engine, tid, who["recent"].id) == (
        "Real Person",
        "9876543210",
        "someone@example.com",
    )
    assert _customer_row(app_engine, tid, who["open"].id)[1] == "9876543210"

    after = _snapshot(app_engine, tid)
    for table, rows in before.items():  # money, approvals, executions, audit: byte-identical
        if table != "audit":
            assert after[table] == rows, table
    old_audit = {r[0]: r[1:] for r in before["audit"]}
    now_audit = {r[0]: r[1:] for r in after["audit"]}
    assert all(now_audit[k] == v for k, v in old_audit.items())  # none deleted or rewritten
    new = [v for k, v in now_audit.items() if k not in old_audit]
    assert len(new) == 1
    payload, event = new[0]
    assert event == "retention.redacted" and payload == {"cases": 2, "msgs": 4, "contacts": 2}


def test_legal_hold_is_respected(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        held = _case(s, tid, made, c, status="closed", age_days=800, hold=True)
    report = purge_tenant(app_engine, tid, NOW)
    assert report.messages == 0 and report.customers == 0
    assert _bodies(app_engine, tid, held.id) == [RAW] * 2
    assert _customer_row(app_engine, tid, c.id)[1] == "9876543210"


def test_customer_with_a_hold_on_another_case_keeps_contact(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        old = _case(s, tid, made, c, status="closed", age_days=800)
        _case(s, tid, made, c, status="closed", age_days=800, hold=True)
    purge_tenant(app_engine, tid, NOW)
    assert _bodies(app_engine, tid, old.id) == [MESSAGE_MARKER] * 2  # messages still go
    assert _customer_row(app_engine, tid, c.id)[1] == "9876543210"  # contact kept


def test_contact_kept_while_customer_has_a_recent_order(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        old = _case(s, tid, made, c, status="closed", age_days=800)
        base = s.scalars(select(Transaction).limit(1)).one()
        txn = Transaction(
            tenant_id=tid,
            customer_id=c.id,
            brand_id=base.brand_id,
            location_id=base.location_id,
            source=base.source,
            external_ref=f"ret-{uuid.uuid4().hex[:12]}",
            placed_at=NOW - timedelta(days=10),
            total_paise=12345,
            status=base.status,
        )
        s.add(txn)
        s.flush()
        made["txns"].append(txn.id)
    report = purge_tenant(app_engine, tid, NOW)
    assert report.customers == 0
    assert _bodies(app_engine, tid, old.id) == [MESSAGE_MARKER] * 2
    assert _customer_row(app_engine, tid, c.id) == (
        "Real Person",
        "9876543210",
        "someone@example.com",
    )
    # once the order is also older than the period, the contact goes
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            update(Transaction)
            .where(Transaction.id == made["txns"][-1])
            .values(placed_at=NOW - timedelta(days=700))
        )
    assert purge_tenant(app_engine, tid, NOW).customers == 1
    assert _customer_row(app_engine, tid, c.id) == (NAME_MARKER, None, None)


def test_idempotent(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        _case(s, tid, made, _customer(s, tid, made), status="closed", age_days=400)
    first = purge_tenant(app_engine, tid, NOW)
    assert first.messages == 2
    mid = _snapshot(app_engine, tid)
    second = purge_tenant(app_engine, tid, NOW)
    assert (second.cases, second.messages, second.customers) == (0, 0, 0)
    assert _snapshot(app_engine, tid) == mid  # not even a second audit row


def test_redacted_case_stays_readable_in_the_timeline(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        case = _case(s, tid, made, _customer(s, tid, made), status="closed", age_days=400)
    purge_tenant(app_engine, tid, NOW)
    with tenant_session(tid, app_engine) as s:
        got = s.get(Case, case.id)
        assert got.status == "closed"
        assert case_timeline(s, got)  # still renders
        assert s.scalars(select(Ticket).where(Ticket.case_id == case.id)).one().status == "closed"
    assert set(_bodies(app_engine, tid, case.id)) == {MESSAGE_MARKER}


def test_runs_only_inside_the_given_tenant(app_engine, maint_engine, tid, made):
    others = [tenant_id_for(load_tenant(d).slug) for d in tenant_dirs()]
    others = [o for o in others if o != tid]
    assert others
    mine = {}
    with tenant_session(tid, maint_engine) as s:
        mine = _case(s, tid, made, _customer(s, tid, made), status="closed", age_days=400)
    theirs = []
    for o in others:
        with tenant_session(o, maint_engine) as s:
            theirs.append(
                (o, _case(s, o, made, _customer(s, o, made), status="closed", age_days=400))
            )
    purge_tenant(app_engine, tid, NOW)
    assert _bodies(app_engine, tid, mine.id) == [MESSAGE_MARKER] * 2
    for o, case in theirs:
        assert _bodies(app_engine, o, case.id) == [RAW] * 2


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)(?:\+?91)?[6-9]\d{9}(?!\d)")


def test_audit_payloads_hold_no_contact_data(app_engine, tid):
    with tenant_session(tid, app_engine) as s:
        payloads = s.scalars(select(AuditEvent.payload)).all()
    text = "\n".join(str(p) for p in payloads)
    assert not EMAIL.search(text) and not PHONE.search(text)
