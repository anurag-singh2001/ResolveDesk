"""Read-only tools for the investigation step (PROJECT.md section 9).

Tenant and customer come from the run's scope (the case), never from arguments: an order id
supplied by a model or customer only resolves if it belongs to the case's customer, otherwise
the tool answers `not_found` exactly as for an id that doesn't exist (hard rule 8). Every
result is structured: {ok: true, data} or {ok: false, error_code, retryable, message}.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Case, Customer, Fulfilment, LineItem, Payment, Transaction


@dataclass(frozen=True)
class Scope:
    tenant_id: uuid.UUID
    case_id: uuid.UUID
    customer_id: uuid.UUID


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def error(code: str, message: str, retryable: bool = False) -> dict:
    return {"ok": False, "error_code": code, "retryable": retryable, "message": message}


def _own_order(session: Session, scope: Scope, transaction_id: str) -> Transaction | None:
    try:
        tid = uuid.UUID(str(transaction_id))
    except ValueError:
        return None
    return session.scalar(
        select(Transaction).where(
            Transaction.id == tid,
            Transaction.tenant_id == scope.tenant_id,
            Transaction.customer_id == scope.customer_id,
        )
    )


def get_customer(session: Session, scope: Scope) -> dict:
    c = session.get(Customer, scope.customer_id)
    if c is None:
        return error("not_found", "customer not found")
    orders = session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.tenant_id == scope.tenant_id, Transaction.customer_id == c.id)
    )
    return ok({"customer_ref": c.external_ref, "orders": orders})


def get_transaction(session: Session, scope: Scope, transaction_id: str) -> dict:
    t = _own_order(session, scope, transaction_id)
    if t is None:
        return error("not_found", "order not found")
    items = session.scalars(select(LineItem).where(LineItem.transaction_id == t.id))
    return ok(
        {
            "transaction_id": str(t.id),
            "external_ref": t.external_ref,
            "placed_at": t.placed_at.isoformat(),
            "total_paise": t.total_paise,
            "status": t.status,
            "brand_id": str(t.brand_id),
            "location_id": str(t.location_id),
            "items": [
                {
                    "sku": li.sku,
                    "name": li.name,
                    "quantity": li.quantity,
                    "quantity_fulfilled": li.quantity_fulfilled,
                    "unit_price_paise": li.unit_price_paise,
                }
                for li in items
            ],
        }
    )


def get_payment(session: Session, scope: Scope, transaction_id: str) -> dict:
    t = _own_order(session, scope, transaction_id)
    if t is None:
        return error("not_found", "order not found")
    payments = session.scalars(select(Payment).where(Payment.transaction_id == t.id))
    return ok(
        [{"method": p.method, "amount_paise": p.amount_paise, "status": p.status} for p in payments]
    )


def get_fulfilment(session: Session, scope: Scope, transaction_id: str) -> dict:
    t = _own_order(session, scope, transaction_id)
    if t is None:
        return error("not_found", "order not found")
    f = session.scalar(select(Fulfilment).where(Fulfilment.transaction_id == t.id))
    if f is None:
        return error("not_found", "no fulfilment recorded")
    late = None
    if f.completed_at is not None:
        late = int((f.completed_at - f.promised_at).total_seconds() // 60)
    return ok(
        {
            "kind": f.kind,
            "promised_at": f.promised_at.isoformat(),
            "completed_at": f.completed_at.isoformat() if f.completed_at else None,
            "minutes_late": late,
            "status": f.status,
            "wrong_item": bool(f.attributes.get("wrong_item")),
        }
    )


def get_case_history(session: Session, scope: Scope) -> dict:
    cases = session.scalars(
        select(Case)
        .where(
            Case.tenant_id == scope.tenant_id,
            Case.customer_id == scope.customer_id,
            Case.id != scope.case_id,
        )
        .order_by(Case.opened_at.desc())
        .limit(10)
    )
    return ok([{"category": c.category, "status": c.status} for c in cases])
