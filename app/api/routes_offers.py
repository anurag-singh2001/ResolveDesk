"""Ask the customer (S8.10): staff offer two remedies, the customer picks, a person reviews."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_context, not_found, require_staff, tenant_db
from app.api.routes_cases import visible_case
from app.core.tenancy import TenantContext
from app.engine import ask_customer
from app.engine.approvals import AlreadyDecided, NotEligible, NotFound
from app.engine.offer_view import customer_offer

router = APIRouter(tags=["offers"])


class OfferedOptionOut(BaseModel):
    code: str
    action: str
    amount_paise: int


class SuggestionOut(BaseModel):
    proposal_id: uuid.UUID
    can_ask: bool
    blocked_reason: str | None
    answer_days: int
    options: list[OfferedOptionOut]


@router.get("/approvals/{proposal_id}/ask-customer")
def get_suggestion(
    proposal_id: uuid.UUID,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> SuggestionOut:
    """The default two options (a voucher and a partial refund at their maximums) and whether
    asking is allowed. A guide for the screen: POST re-checks everything."""
    try:
        proposal, options, reason, days = ask_customer.suggestion(
            db, ctx, proposal_id, datetime.now(UTC)
        )
    except NotFound:
        raise not_found() from None
    except AlreadyDecided:
        raise HTTPException(status.HTTP_409_CONFLICT, "no longer pending") from None
    return SuggestionOut(
        proposal_id=proposal.id,
        can_ask=reason is None,
        blocked_reason=reason,
        answer_days=days,
        options=[OfferedOptionOut(**o.as_json()) for o in options],
    )


class AskOptionIn(BaseModel):
    action: str = Field(max_length=64)
    # A request, never a fact: strict int (or omitted for the maximum), checked server-side.
    amount_paise: int | None = Field(None, strict=True, gt=0)


class AskIn(BaseModel):
    options: list[AskOptionIn] = Field(min_length=2, max_length=2)


class AskOut(BaseModel):
    proposal_id: uuid.UUID
    expires_at: datetime
    options: list[OfferedOptionOut]


@router.post("/approvals/{proposal_id}/ask-customer", status_code=status.HTTP_201_CREATED)
def post_ask_customer(
    proposal_id: uuid.UUID,
    body: AskIn,
    ctx: TenantContext = Depends(require_staff),
    db: Session = Depends(tenant_db),
) -> AskOut:
    """Offer the customer two remedies the rules allow. 404 out of scope or another tenant, 403
    customers, 409 not pending or not allowed (allergen, illness, foreign object), 422 an option
    outside the rule. The proposal stays undecided and can't be approved while this is open."""
    try:
        offer = ask_customer.ask_customer(
            db,
            ctx,
            proposal_id,
            [o.model_dump() for o in body.options],
        )
    except NotFound:
        raise not_found() from None
    except AlreadyDecided:
        raise HTTPException(status.HTTP_409_CONFLICT, "no longer pending") from None
    except ask_customer.CannotAsk as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.reason) from None
    except NotEligible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors) from None
    return AskOut(
        proposal_id=offer.proposal_id,
        expires_at=offer.expires_at,
        options=[OfferedOptionOut(**o) for o in offer.options],
    )


class CustomerOptionOut(BaseModel):
    code: str
    kind: str
    title: str
    summary: str
    amount_paise: int
    approval: str
    timing: str


class CustomerOfferOut(BaseModel):
    state: str  # none | open | chosen | expired
    heading: str
    intro: str
    expires_note: str
    status_text: str = ""
    options: list[CustomerOptionOut]
    expires_at: datetime | None = None


def _customer_only(ctx: TenantContext) -> None:
    if ctx.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customers only")


@router.get("/cases/{case_id}/offer")
def get_offer(
    case_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> CustomerOfferOut:
    """The question a team member put to the customer on their own case (else 404)."""
    _customer_only(ctx)
    case = visible_case(db, ctx, case_id)
    return CustomerOfferOut(**customer_offer(db, case, datetime.now(UTC)))


class OfferChoiceIn(BaseModel):
    option: str = Field(min_length=1, max_length=32)


@router.put("/cases/{case_id}/offer-choice")
def put_offer_choice(
    case_id: uuid.UUID,
    body: OfferChoiceIn,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(tenant_db),
) -> CustomerOfferOut:
    """The customer's one pick, on their own case only (someone else's is a 404). It must be one
    of the stored options. It does not pay anything: a team member reviews it."""
    _customer_only(ctx)
    case = visible_case(db, ctx, case_id)
    try:
        ask_customer.choose(db, ctx, case.id, body.option)
    except NotFound:
        raise not_found() from None
    except ask_customer.OfferClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except ask_customer.InvalidPick as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except NotEligible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors) from None
    return CustomerOfferOut(**customer_offer(db, case, datetime.now(UTC)))
