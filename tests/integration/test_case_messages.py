"""The case page shows the customer's own words (S7.1), separate from our template text."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.models import Location, Ticket, TicketMessage, Transaction
from tests.helpers import login
from tests.integration.test_cases_api import _open, clean_mocks, flow  # noqa: F401

REPORT = "One item was missing from my order."


def test_case_detail_carries_the_customers_own_words(api, flow):  # noqa: F811
    f = flow
    opened = _open(api, f)
    # The list stays light: messages are only on the detail view.
    assert (
        api.get("/cases", headers=f["customer"]).json()[0].keys().isdisjoint({"customer_messages"})
    )
    for headers in (f["customer"], f["hq"]):
        detail = api.get(f"/cases/{opened['id']}", headers=headers).json()
        msgs = detail["customer_messages"]
        assert msgs[0]["text"] == REPORT
        assert all(set(m) == {"at", "text"} for m in msgs)
        assert detail["message"] != REPORT  # template status text stays separate


def test_case_detail_messages_include_replies_oldest_first(api, app_engine, flow):  # noqa: F811
    f = flow
    opened = _open(api, f)
    with tenant_session(f["tid"], app_engine) as s:
        ticket_id = s.scalar(select(Ticket.id).where(Ticket.case_id == uuid.UUID(opened["id"])))
        for author, body, minutes in (
            ("customer", "It was the biryani.", 1),
            ("staff", "internal note", 2),
        ):
            s.add(
                TicketMessage(
                    tenant_id=f["tid"],
                    ticket_id=ticket_id,
                    author=author,
                    body=body,
                    sent_at=datetime.now(UTC) + timedelta(minutes=minutes),
                )
            )
    for headers in (f["hq"], f["customer"]):
        detail = api.get(f"/cases/{opened['id']}", headers=headers).json()
        assert [m["text"] for m in detail["customer_messages"]] == [REPORT, "It was the biryani."]


def test_another_customer_cannot_read_the_messages(api, flow):  # noqa: F811
    f = flow
    opened = _open(api, f)
    others = [u for u in f["cfg"].users if u.role == "customer" and u.email != f["customer_email"]]
    assert others, "needs a second customer"
    for other in others:
        headers = login(api, f["cfg"].slug, other.email)
        assert api.get(f"/cases/{opened['id']}", headers=headers).status_code == 404


def test_staff_outside_the_orders_outlet_get_404(api, app_engine, flow):  # noqa: F811
    f = flow
    opened = _open(api, f)
    with tenant_session(f["tid"], app_engine) as s:
        slug = s.scalar(
            select(Location.slug)
            .join(Transaction, Transaction.location_id == Location.id)
            .where(Transaction.id == f["order_id"])
        )
    scoped = [u for u in f["cfg"].users if u.role != "customer" and u.locations]
    outside = [u for u in scoped if slug not in u.locations]
    inside = [u for u in scoped if slug in u.locations]
    if not outside:
        pytest.skip("no location-scoped staff outside this order's outlet")
    for u in outside:
        headers = login(api, f["cfg"].slug, u.email)
        assert api.get(f"/cases/{opened['id']}", headers=headers).status_code == 404, u.email
    for u in inside:
        headers = login(api, f["cfg"].slug, u.email)
        assert api.get(f"/cases/{opened['id']}", headers=headers).status_code == 200, u.email
