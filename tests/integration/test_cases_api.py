"""The no-LLM refund flow over HTTP, for every tenant (PROJECT.md section 19, day 2 done-when:
"a refund resolves via API with no LLM, for both tenants")."""

import uuid

import pytest
from sqlalchemy import delete, select, update

from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Case,
    Customer,
    LineItem,
    Location,
    RefundOperation,
    Ticket,
    TicketMessage,
    Transaction,
    User,
)
from app.core.tenancy import tenant_id_for
from mocks.base import Chaos
from mocks.registry import get_mock, merchant_id_for, reset_mocks
from tests.helpers import login


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


@pytest.fixture
def flow(api, app_engine, maint_engine, seeded_history, tenant):
    """A demo customer, one of their orders with one item marked missing, and staff logins."""
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    customer = next(u for u in cfg.users if u.role == "customer")
    with tenant_session(tid, app_engine) as s:
        user_id = s.scalar(select(User.id).where(User.email == customer.email))
        customer_id = s.scalar(select(Customer.id).where(Customer.user_id == user_id))
        order = s.scalars(
            select(Transaction)
            .where(Transaction.customer_id == customer_id)
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        ).one()
        line = s.scalars(
            select(LineItem)
            .where(LineItem.transaction_id == order.id)
            .order_by(LineItem.unit_price_paise.desc())
            .limit(1)
        ).one()
        info = {
            "tid": tid,
            "cfg": cfg,
            "order_id": order.id,
            "line_id": line.id,
            "missing_paise": line.unit_price_paise,
            "qty": line.quantity,
            "customer_email": customer.email,
        }
        s.execute(
            update(LineItem)
            .where(LineItem.id == line.id)
            .values(quantity_fulfilled=line.quantity - 1)
        )
    info["customer"] = login(api, cfg.slug, customer.email)
    info["hq"] = login(api, cfg.slug, next(u.email for u in cfg.users if u.role == "hq_owner"))
    yield info
    with tenant_session(tid, app_engine) as s:
        s.execute(
            update(LineItem)
            .where(LineItem.id == info["line_id"])
            .values(quantity_fulfilled=info["qty"])
        )
    with tenant_session(tid, maint_engine) as s:
        # Tickets opened with the case go first (deleting a case only unlinks its ticket).
        case_ids = select(Case.id).where(
            Case.tenant_id == tid, Case.transaction_id == info["order_id"]
        )
        s.execute(delete(Ticket).where(Ticket.tenant_id == tid, Ticket.case_id.in_(case_ids)))
        s.execute(
            delete(RefundOperation).where(
                RefundOperation.tenant_id == tid,
                RefundOperation.transaction_id == info["order_id"],
            )
        )
        s.execute(
            delete(Case).where(Case.tenant_id == tid, Case.transaction_id == info["order_id"])
        )


def _open(api, f, category="missing_items"):
    resp = api.post(
        "/cases",
        headers=f["customer"],
        json={
            "transaction_id": str(f["order_id"]),
            "category": category,
            "message": "One item was missing from my order.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_refund_resolves_over_http_with_no_llm(api, flow):
    f = flow
    opened = _open(api, f)
    assert opened["stage"] == "awaiting_approval" and opened["action"] == "refund"
    assert opened["amount_paise"] == f["missing_paise"]

    queue = api.get("/approvals", headers=f["hq"]).json()
    item = next(p for p in queue if p["case_id"] == opened["id"])
    assert item["eligible"] and item["amount_paise"] == f["missing_paise"]

    decided = api.post(
        f"/approvals/{item['proposal_id']}/decision", headers=f["hq"], json={"decision": "approved"}
    )
    assert decided.status_code == 200 and decided.json()["execution"] == "queued"

    final = api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()
    assert final["stage"] == "confirmed", final
    assert len(get_mock("payment").operations(merchant_id_for(f["tid"]))) == 1


def test_customer_sees_processing_not_success_after_a_timeout(api, flow):
    f = flow
    opened = _open(api, f)
    get_mock("payment").set_chaos(Chaos(accept_then_timeout_rate=1.0), merchant_id_for(f["tid"]))
    api.post(
        f"/approvals/{opened['proposal_id']}/decision",
        headers=f["hq"],
        json={"decision": "approved"},
    )
    mid = api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()
    assert mid["stage"] == "processing"  # never "confirmed" without the provider saying so
    get_mock("payment").set_chaos(Chaos(), merchant_id_for(f["tid"]))
    assert (
        api.post(f"/approvals/{opened['proposal_id']}/reconcile", headers=f["hq"]).status_code
        == 202
    )
    assert api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()["stage"] == "confirmed"
    assert len(get_mock("payment").operations(merchant_id_for(f["tid"]))) == 1


def test_rejection_is_reported_honestly(api, flow):
    f = flow
    opened = _open(api, f)
    api.post(
        f"/approvals/{opened['proposal_id']}/decision",
        headers=f["hq"],
        json={"decision": "rejected", "note": "photo shows all items"},
    )
    assert api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()["stage"] == "declined"
    assert get_mock("payment").operations(merchant_id_for(f["tid"])) == []


def test_second_decision_is_409(api, flow):
    f = flow
    opened = _open(api, f)
    url = f"/approvals/{opened['proposal_id']}/decision"
    assert api.post(url, headers=f["hq"], json={"decision": "approved"}).status_code == 200
    assert api.post(url, headers=f["hq"], json={"decision": "rejected"}).status_code == 409


def test_unmapped_category_escalates(api, flow):
    f = flow
    opened = _open(api, f, category="payment_issue")
    assert opened["stage"] == "escalated" and opened["proposal_id"] is None


def test_staff_cannot_open_cases_and_customers_cannot_decide(api, flow):
    f = flow
    body = {"transaction_id": str(f["order_id"]), "category": "missing_items", "message": "x"}
    assert api.post("/cases", headers=f["hq"], json=body).status_code == 403
    opened = _open(api, f)
    resp = api.post(
        f"/approvals/{opened['proposal_id']}/decision",
        headers=f["customer"],
        json={"decision": "approved"},
    )
    assert resp.status_code == 403


def test_customer_cannot_open_a_case_on_someone_elses_order(api, app_engine, flow):
    f = flow
    with tenant_session(f["tid"], app_engine) as s:
        own = s.scalar(
            select(Customer.id)
            .join(User, User.id == Customer.user_id)
            .where(User.email == f["customer_email"])
        )
        other = s.scalar(select(Transaction.id).where(Transaction.customer_id != own).limit(1))
    resp = api.post(
        "/cases",
        headers=f["customer"],
        json={"transaction_id": str(other), "category": "missing_items", "message": "mine?"},
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "not found"}
    resp = api.post(
        "/cases",
        headers=f["customer"],
        json={"transaction_id": str(uuid.uuid4()), "category": "missing_items", "message": "x"},
    )
    assert resp.status_code == 404


def test_case_events_are_staff_only_and_redacted(api, flow):
    f = flow
    opened = _open(api, f)
    assert api.get(f"/cases/{opened['id']}/events", headers=f["customer"]).status_code == 403
    events = api.get(f"/cases/{opened['id']}/events", headers=f["hq"]).json()
    opened_event = next(e for e in events if e["event"] == "case.opened")
    assert opened_event["payload"]["message"] == "[redacted]"


def test_missing_items_refund_never_exceeds_the_percent_cap(api, app_engine, flow):
    """Everything missing: the proposal is capped, so it stays approvable."""
    from app.core.money import percent_of
    from app.engine.eligibility import order_facts

    f = flow
    with tenant_session(f["tid"], app_engine) as s:
        lines = s.scalars(select(LineItem).where(LineItem.transaction_id == f["order_id"])).all()
        saved = {li.id: li.quantity_fulfilled for li in lines}
        s.execute(
            update(LineItem)
            .where(LineItem.transaction_id == f["order_id"])
            .values(quantity_fulfilled=0)
        )
        order, facts = order_facts(s, f["order_id"])
        cap = percent_of(order.total_paise, facts.settings["refund_max_percent"])
    try:
        opened = _open(api, f)
        assert opened["amount_paise"] <= cap
        item = next(
            p for p in api.get("/approvals", headers=f["hq"]).json() if p["case_id"] == opened["id"]
        )
        assert item["eligible"], item["errors"]
    finally:
        with tenant_session(f["tid"], app_engine) as s:
            for line_id, qty in saved.items():
                s.execute(
                    update(LineItem).where(LineItem.id == line_id).values(quantity_fulfilled=qty)
                )


def test_reopening_the_same_order_returns_the_open_case(api, app_engine, flow):
    f = flow
    first, again = _open(api, f), _open(api, f)
    assert again["id"] == first["id"]
    pending = [
        p for p in api.get("/approvals", headers=f["hq"]).json() if p["case_id"] == first["id"]
    ]
    assert len(pending) == 1  # no second proposal
    with tenant_session(f["tid"], app_engine) as s:
        thread = s.scalars(
            select(TicketMessage.id)
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .where(Ticket.case_id == uuid.UUID(first["id"]))
        ).all()
    assert len(thread) == 2  # the second report is kept on the same thread


def test_an_approved_but_stuck_refund_is_not_shown_as_progressing(api, app_engine, flow):
    """Approved long ago and never executed: the customer is told it needs a check."""
    from datetime import UTC, datetime, timedelta

    from app.core.tenancy import load_context
    from app.engine.approvals import decide

    f = flow
    opened = _open(api, f)
    hq_email = next(u.email for u in f["cfg"].users if u.role == "hq_owner")
    with tenant_session(f["tid"], app_engine) as s:
        hq = load_context(s, f["tid"], s.scalar(select(User.id).where(User.email == hq_email)))
        decide(
            s,
            hq,
            uuid.UUID(opened["proposal_id"]),
            "approved",
            datetime.now(UTC) - timedelta(days=2),
        )
    stage = api.get(f"/cases/{opened['id']}", headers=f["customer"]).json()["stage"]
    assert stage == "escalated"
    assert _stages(api, opened["id"], f["customer"])[-1] == "escalated"  # timeline agrees


def test_case_list_is_scoped_to_the_caller(api, app_engine, flow):
    f = flow
    opened = _open(api, f)
    mine = api.get("/cases", headers=f["customer"]).json()
    assert opened["id"] in {c["id"] for c in mine}
    assert opened["id"] in {c["id"] for c in api.get("/cases", headers=f["hq"]).json()}
    others = [u for u in f["cfg"].users if u.role == "customer" and u.email != f["customer_email"]]
    for other in others:
        theirs = api.get("/cases", headers=login(api, f["cfg"].slug, other.email)).json()
        assert opened["id"] not in {c["id"] for c in theirs}


@pytest.fixture
def agents_mode(monkeypatch):
    import app.api.routes_cases as routes

    runs = []
    agents = routes.get_settings().model_copy(update={"engine_mode": "agents"})
    monkeypatch.setattr(routes, "get_settings", lambda: agents)
    monkeypatch.setattr(routes, "run_agents", lambda *a: runs.append(a))
    return runs


def test_free_text_case_is_queued_for_the_agents(api, app_engine, flow, agents_mode):
    f = flow
    resp = api.post(
        "/cases",
        headers=f["customer"],
        json={"transaction_id": str(f["order_id"]), "message": "Something was missing."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["stage"], body["category"], body["proposal_id"]) == ("investigating", None, None)
    assert len(agents_mode) == 1  # exactly one run scheduled
    with tenant_session(f["tid"], app_engine) as s:
        ticket = s.scalar(select(Ticket.category).where(Ticket.case_id == uuid.UUID(body["id"])))
    assert ticket == "unknown"
    again = api.post(
        "/cases",
        headers=f["customer"],
        json={"transaction_id": str(f["order_id"]), "message": "Hello? Still missing."},
    )
    assert again.json()["id"] == body["id"]  # same open case


def test_category_is_required_outside_agents_mode(api, flow):
    f = flow
    resp = api.post(
        "/cases",
        headers=f["customer"],
        json={"transaction_id": str(f["order_id"]), "message": "Something was missing."},
    )
    assert resp.status_code == 422


def test_cases_and_approvals_carry_the_frontend_fields(api, app_engine, flow):
    f = flow
    opened = _open(api, f)
    with tenant_session(f["tid"], app_engine) as s:
        order = s.get(Transaction, f["order_id"])
        location_name = s.scalar(select(Location.name).where(Location.id == order.location_id))
        order_ref = order.external_ref
    assert opened["order_ref"] == order_ref
    assert opened["created_at"]
    cases = api.get("/cases", headers=f["customer"]).json()
    assert next(c for c in cases if c["id"] == opened["id"])["order_ref"] == order_ref

    queue = api.get("/approvals", headers=f["hq"]).json()
    item = next(p for p in queue if p["case_id"] == opened["id"])
    assert item["customer_message"] == "One item was missing from my order."
    assert item["location_name"] == location_name
    assert item["created_at"]
    assert isinstance(item["citations"], list)
    assert all(isinstance(c["section_ref"], str) for c in item["citations"])


def _stages(api, case_id, headers):
    resp = api.get(f"/cases/{case_id}/timeline", headers=headers)
    assert resp.status_code == 200, resp.text
    return [step["stage"] for step in resp.json()]


def test_timeline_follows_the_refund_in_code_written_steps(api, app_engine, flow):
    f = flow
    opened = _open(api, f)
    assert _stages(api, opened["id"], f["customer"]) == [
        "received",
        "investigating",
        "awaiting_approval",
    ]
    api.post(
        f"/approvals/{opened['proposal_id']}/decision",
        headers=f["hq"],
        json={"decision": "approved", "note": "internal note"},
    )
    steps = api.get(f"/cases/{opened['id']}/timeline", headers=f["customer"]).json()
    assert [s["stage"] for s in steps] == [
        "received",
        "investigating",
        "awaiting_approval",
        "processing",
        "confirmed",
    ]
    times = [s["at"] for s in steps]
    assert times == sorted(times)
    with tenant_session(f["tid"], app_engine) as s:
        reason = s.scalar(
            select(ActionProposal.reason).where(
                ActionProposal.id == uuid.UUID(opened["proposal_id"])
            )
        )
    text = " ".join(s["title"] + " " + s["text"] for s in steps)
    assert reason not in text and "internal note" not in text  # templates only
    assert _stages(api, opened["id"], f["hq"]) == [s["stage"] for s in steps]


def test_declined_case_timeline_ends_declined(api, flow):
    f = flow
    opened = _open(api, f)
    api.post(
        f"/approvals/{opened['proposal_id']}/decision",
        headers=f["hq"],
        json={"decision": "rejected"},
    )
    assert _stages(api, opened["id"], f["customer"])[-1] == "declined"


def test_timeline_has_the_same_visibility_as_the_case(api, seeded, flow):
    f = flow
    opened = _open(api, f)
    others = [u for u in f["cfg"].users if u.role == "customer" and u.email != f["customer_email"]]
    for other in others:
        headers = login(api, f["cfg"].slug, other.email)
        assert api.get(f"/cases/{opened['id']}", headers=headers).status_code == 404
        resp = api.get(f"/cases/{opened['id']}/timeline", headers=headers)
        assert resp.status_code == 404 and resp.json() == {"detail": "not found"}
    for cfg in (c for c in seeded.values() if c.slug != f["cfg"].slug):
        for user in cfg.users:
            resp = api.get(
                f"/cases/{opened['id']}/timeline", headers=login(api, cfg.slug, user.email)
            )
            assert resp.status_code == 404, user.email
    assert api.get(f"/cases/{uuid.uuid4()}/timeline", headers=f["customer"]).status_code == 404
