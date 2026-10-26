"""E8.2: send an approved campaign, once per customer.

Same recipe as the support executors (app/engine/voucher_executor.py):

1. A short transaction locks the campaign, refuses unless it is `approved`/`executing` with
   two valid approvals for the stored payload hash and an intact audience, and lists who still
   needs a send. Commit.
2. Each message goes out through the messaging connector with the member's stable key
   (`C-<campaign>:<customer>:send:1`), outside any DB transaction (hard rule 5).
3. Each answer is stored in its own short transaction, moving forward only. A timeout is
   `unknown`, never "sent" (hard rule 7).
4. Running it again (a retry, a second worker, the double-click on approve) sends the same
   keys, which the provider de-duplicates, so there are zero duplicate sends.

Holdout members are never contacted.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from app.connectors.base import connector_for
from app.core import audit
from app.core.db import tenant_session
from app.core.models import Campaign, CampaignMember, Customer, Location
from app.core.settings_resolver import effective_settings
from app.engine.dispatch import system_context
from app.modules.growth.campaigns import (
    approvals_of,
    dual_approved,
    hash_is_intact,
    valid_approvals,
)

# Connector outcome -> member send_status. "unavailable" means nothing was applied: the member
# stays as it was and the same key is retried on the next run.
STATUS_MAP = {
    "succeeded": "succeeded",
    "failed": "failed",
    "processing": "processing",
    "unknown": "unknown",
}
TERMINAL = ("succeeded", "failed")
OPEN_STATUSES = ("pending", "submitted", "processing", "unknown")


@dataclass(frozen=True)
class CampaignRun:
    outcome: str  # refused | sent | in_progress
    detail: str = ""
    succeeded: int = 0
    failed: int = 0
    outstanding: int = 0


def execute_campaign(
    engine: Engine, tenant_id: uuid.UUID, campaign_id: uuid.UUID, now: datetime | None = None
) -> CampaignRun:
    """Safe to call any number of times, concurrently or not. `tenant_id` comes from the auth
    context or the system job, never from a request body."""
    now = now or datetime.now(UTC)
    ctx = system_context(tenant_id)
    with tenant_session(tenant_id, engine) as s:
        campaign = s.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
        if campaign is None:
            return CampaignRun("refused", "campaign not found")
        if campaign.status not in ("approved", "executing", "sent"):
            return CampaignRun("refused", f"campaign is {campaign.status}")
        if campaign.status != "sent":
            if now >= campaign.expires_at:
                return CampaignRun("refused", "proposal expired")
            if not hash_is_intact(s, campaign):
                return CampaignRun("refused", "payload hash mismatch")
            if not dual_approved(valid_approvals(campaign, approvals_of(s, campaign), now)):
                return CampaignRun("refused", "needs two valid approvals incl. an hq_owner")
        settings = effective_settings(s, location_id=campaign.location_id)
        connector = connector_for(settings, "messaging")
        template = campaign.params["template"]
        offer = str(campaign.params["offer_paise"])
        place = s.scalar(select(Location.name).where(Location.id == campaign.location_id))
        todo = [
            (m.id, m.idempotency_key, phone)
            for m, phone in s.execute(
                select(CampaignMember, Customer.phone)
                .join(Customer, Customer.id == CampaignMember.customer_id)
                .where(
                    CampaignMember.campaign_id == campaign.id,
                    CampaignMember.arm == "treatment",
                    CampaignMember.send_status.in_(OPEN_STATUSES),
                )
                .order_by(CampaignMember.customer_id)
            )
        ]
        if campaign.status == "approved":
            campaign.status = "executing"
            audit.record(
                s,
                tenant_id,
                actor_type="system",
                actor_id=None,
                event="campaign.executing",
                entity_type="campaign",
                entity_id=campaign.id,
                payload={"payload_hash": campaign.payload_hash},
            )
    params = {"offer_paise": offer, "location": place or ""}
    for member_id, key, phone in todo:  # no transaction is open here
        outcome = connector.send(ctx, key, phone, template, params)
        status = STATUS_MAP.get(outcome.status)
        if status is None:
            continue
        with tenant_session(tenant_id, engine) as s:
            s.execute(
                update(CampaignMember)
                .where(CampaignMember.id == member_id, CampaignMember.send_status.notin_(TERMINAL))
                .values(send_status=status, provider_reference=outcome.provider_reference)
            )
    return _finish(engine, tenant_id, campaign_id, now)


def _finish(engine: Engine, tenant_id: uuid.UUID, campaign_id: uuid.UUID, now: datetime):
    with tenant_session(tenant_id, engine) as s:
        campaign = s.scalar(select(Campaign).where(Campaign.id == campaign_id).with_for_update())
        counts = dict.fromkeys((*TERMINAL, *OPEN_STATUSES), 0)
        for status in s.scalars(
            select(CampaignMember.send_status).where(
                CampaignMember.campaign_id == campaign_id, CampaignMember.arm == "treatment"
            )
        ):
            counts[status] += 1
        outstanding = sum(counts[k] for k in OPEN_STATUSES)
        if outstanding == 0 and campaign.status == "executing":
            campaign.status = "sent"
            campaign.sent_at = now
        outcome = "sent" if campaign.status in ("sent", "measured") else "in_progress"
        return CampaignRun(outcome, "", counts["succeeded"], counts["failed"], outstanding)
