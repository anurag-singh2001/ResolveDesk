"""Customer data rights (S5.2). /me/* is for the signed-in customer's own record only: the
customer is found from the token's user id, never from an id in the request (hard rule 8).
Staff cannot call /me/* for a customer. Erasure is requested here and executed by code once an
hq_owner approves it."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_context, not_found, tenant_db
from app.core import audit
from app.core.i18n import normalize
from app.core.models import (
    Brand,
    Case,
    Consent,
    ConsentEvent,
    Customer,
    DataRequest,
    Location,
    Transaction,
)
from app.core.settings_resolver import effective_settings
from app.core.tenancy import TenantContext
from app.engine import consent_benefits, data_export, data_held, erasure_info
from app.engine import data_rights as privacy
from app.engine.case_status import case_status

router = APIRouter(tags=["privacy"])


def own_customer(ctx: TenantContext, db: Session) -> Customer:
    if ctx.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customers only")
    customer = db.scalar(select(Customer).where(Customer.user_id == ctx.user_id))
    if customer is None:
        raise not_found()
    return customer


class ConsentOut(BaseModel):
    purpose: str
    channel: str
    granted: bool
    updated_at: datetime | None


class ConsentEventOut(BaseModel):
    purpose: str
    channel: str
    granted: bool
    source: str
    notice_version: str
    at: datetime


class ConsentStateOut(BaseModel):
    """The plain record of choices; this is what the data export embeds."""

    notice_version: str
    consents: list[ConsentOut]
    history: list[ConsentEventOut]


class ConsentsOut(ConsentStateOut):
    # Benefit wording, frequency cap and the always-on help note (S8.5b), in the customer's
    # language. Page copy, so it is not part of the export.
    benefits: consent_benefits.Benefits


def _consents(db: Session, customer: Customer) -> ConsentsOut:
    state, current, events = _state(db, customer)
    return ConsentsOut(
        **state.model_dump(),
        benefits=consent_benefits.build(customer.preferred_language, current, events),
    )


def _state(db: Session, customer: Customer):
    rows = {
        (c.purpose, c.channel): c
        for c in db.scalars(select(Consent).where(Consent.customer_id == customer.id))
    }
    current = []
    for purpose in privacy.PURPOSES:
        for channel in privacy.CHANNELS:
            row = rows.get((purpose, channel))  # no row means no consent
            current.append(
                ConsentOut(
                    purpose=purpose,
                    channel=channel,
                    granted=bool(row and row.granted),
                    updated_at=row.updated_at if row else None,
                )
            )
    events = db.scalars(
        select(ConsentEvent)
        .where(ConsentEvent.customer_id == customer.id)
        .order_by(ConsentEvent.created_at, ConsentEvent.id)
    )
    events = list(events)
    state = ConsentStateOut(
        notice_version=privacy.NOTICE_VERSION,
        consents=current,
        history=[
            ConsentEventOut(
                purpose=e.purpose,
                channel=e.channel,
                granted=e.granted,
                source=e.source,
                notice_version=e.notice_version,
                at=e.created_at,
            )
            for e in events
        ],
    )
    return state, current, events


@router.get("/me/consents")
def my_consents(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> ConsentsOut:
    return _consents(db, own_customer(ctx, db))


class ConsentIn(BaseModel):
    granted: bool
    channel: str = privacy.CHANNELS[0]


@router.post("/me/consents/{purpose}")
def set_my_consent(
    purpose: str,
    body: ConsentIn,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> ConsentsOut:
    """Grant or withdraw: the same single call either way. Takes effect for the next send."""
    customer = own_customer(ctx, db)
    if purpose not in privacy.PURPOSES or body.channel not in privacy.CHANNELS:
        raise not_found()
    privacy.set_consent(
        db, ctx.tenant_id, customer.id, purpose, body.channel, body.granted, actor_id=ctx.user_id
    )
    db.flush()
    return _consents(db, customer)


# --- access ------------------------------------------------------------------------------


@router.get("/me/data-export")
def my_data_export(
    response: Response,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> dict:
    """A summary of the customer's own personal data and who else processes it (DPDP s.11).
    Case text is the customer-safe status message, not internal notes or model output."""
    response.headers["Cache-Control"] = "no-store"  # personal data: no shared or disk cache
    customer = own_customer(ctx, db)
    now = datetime.now(UTC)
    orders = db.execute(
        select(Transaction, Brand.name, Location.name)
        .join(Brand, Brand.id == Transaction.brand_id)
        .join(Location, Location.id == Transaction.location_id)
        .where(Transaction.customer_id == customer.id)
        .order_by(Transaction.placed_at.desc(), Transaction.id)
    ).all()
    cases = []
    for case in db.scalars(
        select(Case).where(Case.customer_id == customer.id).order_by(Case.opened_at.desc())
    ):
        st = case_status(db, case, now)
        order = db.get(Transaction, case.transaction_id) if case.transaction_id else None
        cases.append(
            {
                "id": str(case.id),
                "order_ref": order.external_ref if order else None,
                "category": case.category,
                "opened_at": case.opened_at,
                "stage": st.stage,
                "message": st.message,
            }
        )
    consent = _state(db, customer)[0]
    return {
        "generated_at": now,
        "profile": {
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "reference": customer.external_ref,
        },
        "orders": [
            {
                "order_ref": t.external_ref,
                "placed_at": t.placed_at,
                "brand": brand,
                "location": place,
                "total_paise": t.total_paise,
                "status": t.status,
            }
            for t, brand, place in orders
        ],
        "cases": cases,
        "consents": consent.model_dump(mode="json"),
        "processors": effective_settings(db).get("data_processors", []),
    }


@router.get("/me/data-export/readable")
def my_readable_export(
    response: Response,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> dict:
    """The same customer's data as print-friendly sections in their language (S8.5c). The
    customer comes from the token; there is no id to pass. The audit row carries no personal
    content, only that an export happened."""
    response.headers["Cache-Control"] = "no-store"
    customer = own_customer(ctx, db)
    body = data_export.readable_export(db, customer, effective_settings(db), datetime.now(UTC))
    audit.record(
        db,
        ctx.tenant_id,
        actor_type="user",
        actor_id=ctx.user_id,
        event="data.exported",
        entity_type="customer",
        entity_id=customer.id,
        payload={"format": "readable"},
    )
    return body


@router.get("/me/data-held")
def my_data_held(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> dict:
    """What we hold about the signed-in customer: per item the purpose, retention (tenant
    settings, labelled provisional), use and the customer's own count. The customer comes from
    the token and there is no id to pass, so another customer's or tenant's data is unreachable."""
    customer = own_customer(ctx, db)
    return data_held.what_we_hold(db, customer, effective_settings(db))


# --- erasure -----------------------------------------------------------------------------


class DataRequestOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str  # pending_approval | deferred | completed | withdrawn
    reason: str | None  # template text, set when deferred
    deferred_until: datetime | None
    requested_at: datetime
    completed_at: datetime | None


def _request_out(r: DataRequest) -> DataRequestOut:
    return DataRequestOut(
        id=r.id,
        kind=r.kind,
        status=r.status,
        reason=privacy.reason_text(r.reason_code, r.deferred_until),
        deferred_until=r.deferred_until,
        requested_at=r.created_at,
        completed_at=r.completed_at,
    )


def _my_request(req: DataRequest, db: Session, customer: Customer) -> dict:
    """The customer's view of a request: the plain fields plus stage, dates and the contact,
    in the customer's language. The text of a stage never says more than the row proves."""
    lang = normalize(customer.preferred_language)
    body = _request_out(req).model_dump(mode="json")
    return body | erasure_info.view(req, effective_settings(db), lang) | {"id": str(req.id)}


@router.get("/me/erasure-info")
def my_erasure_info(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> dict:
    """What erasure removes, keeps and may wait for, in the customer's language."""
    customer = own_customer(ctx, db)
    return erasure_info.info(effective_settings(db), normalize(customer.preferred_language))


@router.post("/me/erasure-request", status_code=status.HTTP_201_CREATED)
def request_erasure(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> dict:
    """File a request. If one is already open the same request comes back (not a second one)."""
    customer = own_customer(ctx, db)
    req = privacy.request_erasure(
        db, ctx.tenant_id, customer.id, datetime.now(UTC), actor_id=ctx.user_id
    )
    return _my_request(req, db, customer)


@router.get("/me/erasure-request")
def my_erasure_request(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> dict | None:
    """The latest request, or null when there is none."""
    customer = own_customer(ctx, db)
    req = db.scalar(
        select(DataRequest)
        .where(DataRequest.customer_id == customer.id)
        .order_by(DataRequest.created_at.desc(), DataRequest.id)
        .limit(1)
    )
    return _my_request(req, db, customer) if req else None


@router.post("/me/erasure-request/cancel")
def withdraw_my_erasure_request(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> dict:
    """Withdraw the open request. 404 when there is none; 409 once it has been carried out
    (it cannot be undone, and we do not pretend otherwise)."""
    customer = own_customer(ctx, db)
    req = privacy.withdraw_erasure(db, ctx.tenant_id, customer.id, actor_id=ctx.user_id)
    if req is None:
        raise not_found()
    if req.status == "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "this request has already been carried out")
    return _my_request(req, db, customer)


class StaffRequestOut(DataRequestOut):
    customer_ref: str


def _hq(ctx: TenantContext) -> None:
    if ctx.role != "hq_owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hq owner only")


@router.get("/data-requests")
def list_data_requests(
    ctx: TenantContext = Depends(get_tenant_context), db: Session = Depends(tenant_db)
) -> list[StaffRequestOut]:
    _hq(ctx)
    rows = db.execute(
        select(DataRequest, Customer.external_ref)
        .join(Customer, Customer.id == DataRequest.customer_id)
        .order_by(DataRequest.created_at.desc(), DataRequest.id)
        .limit(200)
    )
    return [StaffRequestOut(**_request_out(r).model_dump(), customer_ref=ref) for r, ref in rows]


@router.post("/data-requests/{request_id}/approve")
def approve_data_request(
    request_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> DataRequestOut:
    """Approve an erasure: code re-checks the guards, then redacts or stays deferred with the
    reason. Safe to call again on a deferred request (it re-checks) or a completed one."""
    _hq(ctx)
    req = privacy.run_erasure(db, ctx.tenant_id, request_id, ctx.user_id, datetime.now(UTC))
    if req is None:
        raise not_found()
    if req.status == "withdrawn":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the customer withdrew this request; nothing was erased"
        )
    return _request_out(req)
