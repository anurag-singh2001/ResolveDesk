"""Growth API (staff only, /growth). Off unless the tenant's `growth` feature flag is on; a
disabled module answers 404, like any other thing that isn't there."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.deps import get_clock, get_db_engine, not_found, require_staff, tenant_db
from app.core.models import Campaign, FeatureFlag, PlaybookEntry, Signal
from app.core.tenancy import TenantContext
from app.engine.proposals import ProposalError
from app.modules.growth import campaigns as camp
from app.modules.growth import signals as sig
from app.modules.growth.executor import execute_campaign
from app.modules.growth.verdict import NotReady, measure

router = APIRouter(prefix="/growth", tags=["growth"])
log = logging.getLogger(__name__)


def require_growth(
    ctx: TenantContext = Depends(require_staff), db: Session = Depends(tenant_db)
) -> TenantContext:
    on = db.scalar(select(FeatureFlag.enabled).where(FeatureFlag.key == "growth"))
    if not on:
        raise not_found()
    return ctx


class SignalOut(BaseModel):
    id: uuid.UUID
    location_id: uuid.UUID
    metric: str
    baseline_bp: int
    recent_bp: int
    baseline_n: int
    recent_n: int
    drop_bp: int
    status: str
    diagnosis: dict
    diagnosis_source: str
    recent_end: datetime


class CampaignOut(BaseModel):
    id: uuid.UUID
    signal_id: uuid.UUID
    location_id: uuid.UUID
    status: str
    payload_hash: str
    params: dict
    budget_paise: int
    expires_at: datetime
    sent_at: datetime | None
    treatment_n: int
    holdout_n: int
    approvals: list[dict]
    fully_approved: bool
    playbook: dict | None


def _signal_out(s: Signal) -> SignalOut:
    return SignalOut.model_validate(s, from_attributes=True)


def _campaign_out(db: Session, c: Campaign, now: datetime) -> CampaignOut:
    approvals = camp.approvals_of(db, c)
    entry = db.scalar(select(PlaybookEntry).where(PlaybookEntry.campaign_id == c.id))
    return CampaignOut(
        id=c.id,
        signal_id=c.signal_id,
        location_id=c.location_id,
        status=c.status,
        payload_hash=c.payload_hash,
        params=c.params,
        budget_paise=c.budget_paise,
        expires_at=c.expires_at,
        sent_at=c.sent_at,
        treatment_n=c.params["treatment_n"],
        holdout_n=c.params["holdout_n"],
        approvals=[
            {
                "decided_by": str(a.decided_by),
                "role": a.role,
                "decision": a.decision,
                "expires_at": a.expires_at.isoformat(),
            }
            for a in approvals
        ],  # fmt: skip
        fully_approved=camp.dual_approved(camp.valid_approvals(c, approvals, now)),
        playbook=None
        if entry is None
        else {
            "verdict": entry.verdict,
            "uplift_bp": entry.uplift_bp,
            "treatment_n": entry.treatment_n,
            "holdout_n": entry.holdout_n,
            "confidence_note": entry.confidence_note,
            "lesson": entry.lesson,
        },
    )


@router.get("/signals")
def list_signals(
    ctx: TenantContext = Depends(require_growth), db: Session = Depends(tenant_db)
) -> list[SignalOut]:
    rows = db.scalars(select(Signal).order_by(Signal.recent_end.desc(), Signal.id))
    return [_signal_out(s) for s in rows if camp.in_scope(ctx, s.location_id)]


@router.post("/signals/refresh")
def refresh_signals(
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> list[SignalOut]:
    """Run the signal job now (it also runs nightly). hq_owner only: it reads every location."""
    if ctx.role != "hq_owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "hq_owner only")
    return [_signal_out(s) for s in sig.run_signal_job(db, ctx.tenant_id, now)]


class ProposeIn(BaseModel):
    offer_paise: int = camp.DEFAULT_OFFER_PAISE
    window_days: int = camp.DEFAULT_WINDOW_DAYS


@router.post("/signals/{signal_id}/campaign", status_code=status.HTTP_201_CREATED)
def propose_campaign(
    signal_id: uuid.UUID,
    body: ProposeIn,
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> CampaignOut:
    try:
        # A write: proposal expiry is stamped in real time, never the dev clock (DECISIONS.md).
        c = camp.propose(db, ctx, signal_id, datetime.now(UTC), body.offer_paise, body.window_days)
    except camp.NotFound:
        raise not_found() from None
    except ProposalError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return _campaign_out(db, c, now)


@router.get("/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: uuid.UUID,
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> CampaignOut:
    try:
        c = camp.load_campaign(db, ctx, campaign_id)
    except camp.NotFound:
        raise not_found() from None
    return _campaign_out(db, c, now)


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]


def _send(engine: Engine, tenant_id: uuid.UUID, campaign_id: uuid.UUID, now: datetime) -> None:
    """After the request's transaction committed: no DB transaction is open during sends."""
    try:
        execute_campaign(engine, tenant_id, campaign_id, now)
    except Exception:
        log.exception("campaign %s: send failed; re-running is safe", campaign_id)


@router.post("/campaigns/{campaign_id}/approve")
def approve_campaign(
    campaign_id: uuid.UUID,
    body: DecisionIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
    engine: Engine = Depends(get_db_engine),
    now: datetime = Depends(get_clock),
) -> CampaignOut:
    try:
        # Approvals, their expiry and the sends run in real time; `now` is for display only.
        _, ready = camp.decide(db, ctx, campaign_id, body.decision, datetime.now(UTC))
    except camp.NotFound:
        raise not_found() from None
    except camp.AlreadyDecided as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except camp.Expired as exc:
        raise HTTPException(status.HTTP_410_GONE, str(exc)) from None
    except camp.NotEligible as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if ready:
        background.add_task(_send, engine, ctx.tenant_id, campaign_id, datetime.now(UTC))
    return _campaign_out(db, camp.load_campaign(db, ctx, campaign_id), now)


@router.post("/campaigns/{campaign_id}/verdict")
def campaign_verdict(
    campaign_id: uuid.UUID,
    ctx: TenantContext = Depends(require_growth),
    db: Session = Depends(tenant_db),
    now: datetime = Depends(get_clock),
) -> CampaignOut:
    try:
        measure(db, ctx, campaign_id, now)
        c = camp.load_campaign(db, ctx, campaign_id)
    except camp.NotFound:
        raise not_found() from None
    except NotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _campaign_out(db, c, now)
