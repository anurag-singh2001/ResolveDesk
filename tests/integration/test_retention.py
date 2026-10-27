"""DPDP retention (S5.1): old finished cases lose message text and customer contact data;
everything else (open, escalated or recent cases, held cases, anything with money-flow work
still in progress, money, approvals, audit) is left alone. A dry run changes nothing. Runs per
tenant under RLS, and twice changes nothing more.

Assertions are on the rows each test creates, never on global counts: the shared seed may
hold other old cases."""

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
    purge_all,
    purge_tenant,
    retention_days,
)
from scripts import retention as retention_script

NOW = datetime.now(UTC)
RAW = "my number is 9876543210 and mail me at someone@example.com"
KEPT = ("Real Person", "9876543210", "someone@example.com")
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
    rows = {"tid": [], "cases": [], "customers": [], "txns": [], "tickets": []}
    yield rows
    for tid_ in set(rows["tid"]):
        with tenant_session(tid_, maint_engine) as s:
            proposals = select(ActionProposal.id).where(ActionProposal.case_id.in_(rows["cases"]))
            s.execute(delete(RefundOperation).where(RefundOperation.proposal_id.in_(proposals)))
            s.execute(
                delete(RefundOperation).where(RefundOperation.transaction_id.in_(rows["txns"]))
            )
            tickets = select(Ticket.id).where(
                (Ticket.case_id.in_(rows["cases"])) | (Ticket.id.in_(rows["tickets"]))
            )
            s.execute(delete(TicketMessage).where(TicketMessage.ticket_id.in_(tickets)))
            s.execute(delete(Ticket).where(Ticket.id.in_(tickets)))
            s.execute(delete(Case).where(Case.id.in_(rows["cases"])))  # proposals etc. cascade
            s.execute(delete(Transaction).where(Transaction.id.in_(rows["txns"])))
            s.execute(delete(Customer).where(Customer.id.in_(rows["customers"])))


def _customer(s, tid, made):
    c = Customer(
        tenant_id=tid,
        external_ref=f"ret-{uuid.uuid4().hex[:12]}",
        name=KEPT[0],
        phone=KEPT[1],
        email=KEPT[2],
    )
    s.add(c)
    s.flush()
    made["tid"].append(tid)
    made["customers"].append(c.id)
    return SimpleNamespace(id=c.id)


def _case(s, tid, made, customer, *, status="closed", age_days=400, hold=False, ticket="closed"):
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
    tk = Ticket(
        tenant_id=tid,
        customer_id=customer.id,
        case_id=case.id,
        category="late_delivery",
        status=ticket,
        channel="app",
        opened_at=t,
    )
    s.add(tk)
    s.flush()
    for author in ("customer", "system"):
        s.add(TicketMessage(tenant_id=tid, ticket_id=tk.id, author=author, body=RAW, sent_at=t))
    made["tid"].append(tid)
    made["cases"].append(case.id)
    return SimpleNamespace(id=case.id)


def _base_txn(s):
    return s.scalars(select(Transaction).limit(1)).one()


def _order(s, tid, made, customer, days_ago):
    base = _base_txn(s)
    txn = Transaction(
        tenant_id=tid,
        customer_id=customer.id,
        brand_id=base.brand_id,
        location_id=base.location_id,
        source=base.source,
        external_ref=f"ret-{uuid.uuid4().hex[:12]}",
        placed_at=NOW - timedelta(days=days_ago),
        total_paise=12345,
        status=base.status,
    )
    s.add(txn)
    s.flush()
    made["txns"].append(txn.id)
    return SimpleNamespace(id=txn.id)


def _money(s, tid, case, *, approved=True, execution=None, verified=False, refund=None, txn=None):
    """A refund proposal on the case, with whatever stage of the money flow the test wants."""
    txn_id = txn.id if txn is not None else _base_txn(s).id
    proposal = ActionProposal(
        tenant_id=tid,
        case_id=case.id,
        action="refund",
        params={"transaction_id": str(txn_id), "amount_paise": 100},
        amount_param="amount_paise",
        amount_paise=100,
        payload_hash=uuid.uuid4().hex * 2,
        risk="low",
        reason="test",
    )
    s.add(proposal)
    s.flush()
    approval = None
    if approved:
        approval = Approval(
            tenant_id=tid,
            proposal_id=proposal.id,
            payload_hash=proposal.payload_hash,
            decision="approved",
            mode="auto",
            decided_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
        s.add(approval)
        s.flush()
    if execution:
        ex = Execution(
            tenant_id=tid,
            proposal_id=proposal.id,
            approval_id=approval.id,
            idempotency_key=f"ret-{uuid.uuid4().hex}",
            status=execution,
        )
        s.add(ex)
        s.flush()
        if verified:
            s.add(Verification(tenant_id=tid, execution_id=ex.id, status="verified"))
    if refund:
        s.add(
            RefundOperation(
                tenant_id=tid,
                transaction_id=txn_id,
                proposal_id=proposal.id,
                idempotency_key=f"ret-{uuid.uuid4().hex}",
                amount_paise=100,
                status=refund,
            )
        )
    s.flush()


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


def _rows(engine, tid, made):
    """Every row this test created that a retention run could touch."""
    with tenant_session(tid, engine) as s:
        msgs = s.execute(
            select(TicketMessage.id, TicketMessage.body)
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .where(Ticket.case_id.in_(made["cases"]))
            .order_by(TicketMessage.id)
        ).all()
        custs = s.execute(
            select(Customer.id, Customer.name, Customer.phone, Customer.email)
            .where(Customer.id.in_(made["customers"]))
            .order_by(Customer.id)
        ).all()
    return msgs, custs


def test_setting_default_is_in_the_pack(app_engine, tid):
    with tenant_session(tid, app_engine) as s:
        assert effective_settings(s)["support_retention_days"] == 365


def test_old_finished_case_redacted_others_untouched(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        who = {k: _customer(s, tid, made) for k in ("old", "recent", "open", "resolved", "esc")}
        old = _case(s, tid, made, who["old"], status="closed", age_days=400)
        resolved = _case(s, tid, made, who["resolved"], status="resolved", age_days=500)
        recent = _case(s, tid, made, who["recent"], status="closed", age_days=30)
        open_ = _case(s, tid, made, who["open"], status="awaiting_info", age_days=900)
        escalated = _case(s, tid, made, who["esc"], status="escalated", age_days=900)
    before = _snapshot(app_engine, tid)

    report = purge_tenant(app_engine, tid, NOW, apply=True)

    assert report.applied and report.cases >= 2 and report.messages >= 4 and report.customers >= 2
    for c in (old, resolved):
        assert _bodies(app_engine, tid, c.id) == [MESSAGE_MARKER] * 2
    for c in (recent, open_, escalated):
        assert _bodies(app_engine, tid, c.id) == [RAW] * 2
    assert _customer_row(app_engine, tid, who["old"].id) == (NAME_MARKER, None, None)
    assert _customer_row(app_engine, tid, who["resolved"].id) == (NAME_MARKER, None, None)
    for k in ("recent", "open", "esc"):
        assert _customer_row(app_engine, tid, who[k].id) == KEPT

    after = _snapshot(app_engine, tid)
    for table, rows in before.items():  # money, approvals, executions: identical
        if table != "audit":
            assert after[table] == rows, table
    old_audit = {r[0]: r[1:] for r in before["audit"]}
    now_audit = {r[0]: r[1:] for r in after["audit"]}
    assert all(now_audit[k] == v for k, v in old_audit.items())  # none deleted or rewritten
    new = [v for k, v in now_audit.items() if k not in old_audit]
    assert len(new) == 1
    payload, event = new[0]
    assert event == "retention.redacted"
    assert payload == {
        "cases": report.cases,
        "msgs": report.messages,
        "contacts": report.customers,
    }


def test_dry_run_changes_nothing_and_matches_the_apply_run(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        _case(s, tid, made, c)
    before_rows = _rows(app_engine, tid, made)
    before = _snapshot(app_engine, tid)

    dry = purge_tenant(app_engine, tid, NOW)  # apply defaults to False

    assert not dry.applied and dry.messages >= 2 and dry.customers >= 1
    assert _rows(app_engine, tid, made) == before_rows
    assert _snapshot(app_engine, tid) == before  # not even an audit row

    done = purge_tenant(app_engine, tid, NOW, apply=True)
    assert (done.cases, done.messages, done.customers) == (dry.cases, dry.messages, dry.customers)
    assert _rows(app_engine, tid, made) != before_rows


def test_purge_all_dry_run_covers_every_tenant_and_writes_nothing(
    app_engine, maint_engine, tid, made
):
    with tenant_session(tid, maint_engine) as s:
        _case(s, tid, made, _customer(s, tid, made))
    before_rows = _rows(app_engine, tid, made)
    reports = purge_all(app_engine, NOW)
    assert len(reports) == len(tenant_dirs())
    assert all(r is not None and not r.applied for r in reports.values())
    assert _rows(app_engine, tid, made) == before_rows


def test_legal_hold_is_respected(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        held = _case(s, tid, made, c, age_days=800, hold=True)
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, held.id) == [RAW] * 2
    assert _customer_row(app_engine, tid, c.id) == KEPT


def test_customer_with_a_hold_on_another_case_keeps_contact(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        old = _case(s, tid, made, c, age_days=800)
        _case(s, tid, made, c, age_days=800, hold=True)
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, old.id) == [MESSAGE_MARKER] * 2  # messages still go
    assert _customer_row(app_engine, tid, c.id) == KEPT


def test_contact_kept_while_customer_has_a_recent_order(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        old = _case(s, tid, made, c, age_days=800)
        _order(s, tid, made, c, days_ago=10)
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, old.id) == [MESSAGE_MARKER] * 2
    assert _customer_row(app_engine, tid, c.id) == KEPT
    # once the order is also older than the period, the contact goes
    with tenant_session(tid, maint_engine) as s:
        s.execute(
            update(Transaction)
            .where(Transaction.id.in_(made["txns"]))
            .values(placed_at=NOW - timedelta(days=700))
        )
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _customer_row(app_engine, tid, c.id) == (NAME_MARKER, None, None)


# --- guards: money-flow work or a person still working keeps the data ------------------------

IN_PROGRESS = {
    "undecided_proposal": dict(approved=False),
    "execution_submitted": dict(execution="submitted"),
    "execution_processing": dict(execution="processing"),
    "execution_unknown": dict(execution="unknown"),
    "succeeded_unverified": dict(execution="succeeded"),
    "refund_reserved": dict(refund="reserved"),
    "refund_submitted": dict(refund="submitted"),
    "refund_unknown": dict(refund="unknown"),
    "refund_pending_reconciliation": dict(refund="pending_reconciliation"),
}


@pytest.mark.parametrize("stage", list(IN_PROGRESS))
def test_money_flow_in_progress_keeps_messages_and_contact(
    app_engine, maint_engine, tid, made, stage
):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        case = _case(s, tid, made, c, age_days=800)
        _money(s, tid, case, **IN_PROGRESS[stage])
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, case.id) == [RAW] * 2
    assert _customer_row(app_engine, tid, c.id) == KEPT


def test_settled_money_flow_does_not_block(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        case = _case(s, tid, made, c, age_days=800)
        _money(s, tid, case, execution="succeeded", verified=True, refund="succeeded")
        c2 = _customer(s, tid, made)
        case2 = _case(s, tid, made, c2, age_days=800)
        _money(s, tid, case2, execution="failed")
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, case.id) == [MESSAGE_MARKER] * 2
    assert _customer_row(app_engine, tid, c.id) == (NAME_MARKER, None, None)
    assert _bodies(app_engine, tid, case2.id) == [MESSAGE_MARKER] * 2


def test_refund_in_flight_on_the_customers_order_keeps_contact(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        x, y = _customer(s, tid, made), _customer(s, tid, made)
        old = _case(s, tid, made, x, age_days=800)
        order = _order(s, tid, made, x, days_ago=700)
        other = _case(s, tid, made, y, age_days=800)
        _money(s, tid, other, refund="submitted", txn=order)  # in flight on x's order
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, old.id) == [MESSAGE_MARKER] * 2
    assert _customer_row(app_engine, tid, x.id) == KEPT


def test_open_ticket_without_a_case_keeps_the_customers_contact(
    app_engine, maint_engine, tid, made
):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        old = _case(s, tid, made, c, age_days=800)
        tk = Ticket(
            tenant_id=tid,
            customer_id=c.id,
            case_id=None,
            category="other",
            status="open",
            channel="app",
            opened_at=NOW - timedelta(days=2),
        )
        s.add(tk)
        s.flush()
        made["tickets"].append(tk.id)
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, old.id) == [MESSAGE_MARKER] * 2
    assert _customer_row(app_engine, tid, c.id) == KEPT


def test_open_ticket_on_an_old_finished_case_keeps_its_messages(
    app_engine, maint_engine, tid, made
):
    with tenant_session(tid, maint_engine) as s:
        c = _customer(s, tid, made)
        case = _case(s, tid, made, c, age_days=800, ticket="open")
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, case.id) == [RAW] * 2
    assert _customer_row(app_engine, tid, c.id) == KEPT


def test_idempotent(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        _case(s, tid, made, _customer(s, tid, made))
    first = purge_tenant(app_engine, tid, NOW, apply=True)
    assert first.messages >= 2
    mid = _snapshot(app_engine, tid)
    mid_rows = _rows(app_engine, tid, made)
    second = purge_tenant(app_engine, tid, NOW, apply=True)
    assert (second.cases, second.messages, second.customers) == (0, 0, 0)
    assert _snapshot(app_engine, tid) == mid  # not even a second audit row
    assert _rows(app_engine, tid, made) == mid_rows


def test_redacted_case_stays_readable_in_the_timeline(app_engine, maint_engine, tid, made):
    with tenant_session(tid, maint_engine) as s:
        case = _case(s, tid, made, _customer(s, tid, made))
    purge_tenant(app_engine, tid, NOW, apply=True)
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
    with tenant_session(tid, maint_engine) as s:
        mine = _case(s, tid, made, _customer(s, tid, made))
    theirs = []
    for o in others:
        with tenant_session(o, maint_engine) as s:
            theirs.append((o, _case(s, o, made, _customer(s, o, made))))
    purge_tenant(app_engine, tid, NOW, apply=True)
    assert _bodies(app_engine, tid, mine.id) == [MESSAGE_MARKER] * 2
    for o, case in theirs:
        assert _bodies(app_engine, o, case.id) == [RAW] * 2


# --- the script: refuses without an explicit APP_ENV, dry run by default, exit codes ----------


def _settings(env="test"):
    return SimpleNamespace(app_env=env)


def _stub(monkeypatch, result):
    calls = []

    def fake(engine, now=None, apply=False):
        calls.append(apply)
        return result

    monkeypatch.setattr(retention_script, "purge_all", fake)
    return calls


def test_script_refuses_when_app_env_is_not_set_explicitly(monkeypatch):
    calls = _stub(monkeypatch, {})
    assert retention_script.run(["--apply"], _settings("prod"), engine=1, environ={}) == 2
    assert calls == []


def test_script_is_a_dry_run_unless_apply(monkeypatch, capsys):
    from app.engine.retention import RetentionReport

    ok = {load_tenant(d).slug: RetentionReport() for d in tenant_dirs()}
    calls = _stub(monkeypatch, ok)
    assert retention_script.run([], _settings(), engine=1, environ={"APP_ENV": "test"}) == 0
    assert (
        retention_script.run(["--apply"], _settings("prod"), engine=1, environ={"APP_ENV": "test"})
        == 0
    )
    assert calls == [False, True]
    assert "WARNING" in capsys.readouterr().err  # prod + apply


def test_script_exits_non_zero_when_a_tenant_failed_or_is_missing(monkeypatch):
    from app.engine.retention import RetentionReport

    slugs = [load_tenant(d).slug for d in tenant_dirs()]
    _stub(monkeypatch, {slugs[0]: None, **{s: RetentionReport() for s in slugs[1:]}})
    assert retention_script.run([], _settings(), engine=1, environ={"APP_ENV": "test"}) == 1
    _stub(monkeypatch, {slugs[0]: RetentionReport()})  # others missing
    assert retention_script.run([], _settings(), engine=1, environ={"APP_ENV": "test"}) == 1


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Word boundaries, not digit-only: a hex hash in a payload can contain ten digits in a row.
PHONE = re.compile(r"(?<!\w)(?:\+?91)?[6-9]\d{9}(?!\w)")


def test_audit_payloads_hold_no_contact_data(app_engine, tid):
    with tenant_session(tid, app_engine) as s:
        payloads = s.scalars(select(AuditEvent.payload)).all()
    text = "\n".join(str(p) for p in payloads)
    assert not EMAIL.search(text) and not PHONE.search(text)
