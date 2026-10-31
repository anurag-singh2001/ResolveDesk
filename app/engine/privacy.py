"""Privacy / grievance requests (S5.5).

A customer marks a report as a privacy request (category `privacy_request`). The engine never
proposes a payout for it: it goes straight to a person. The customer's text is a template that
names the tenant's privacy contact and an INTERNAL response target. That target is a product
choice (`grievance_target_days`, default 30), never described as a legal deadline: the legal
ceiling is longer and not ours to restate to customers (docs/research/dpdp-and-hindi.md).
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select

from app.core import audit
from app.core.business_time import business_date
from app.core.db import tenant_session
from app.core.i18n import format_date, t
from app.core.models import AuditEvent, Case
from app.core.settings_resolver import effective_settings

PRIVACY_CATEGORY = "privacy_request"
ESCALATION_REASON = "privacy/grievance request: a person must handle it (no automatic remedy)"
DUE_SOON_EVENT = "grievance.due_soon"
DUE_SOON_FRACTION = 0.75
CLOSED_STATUSES = ("resolved", "closed")


def target_date(opened_at: datetime, settings: dict[str, Any]) -> date:
    return business_date(opened_at, settings) + timedelta(days=settings["grievance_target_days"])


def contact_line(settings: dict[str, Any]) -> str | None:
    """The privacy and grievance contact as one line, or None while the owner has set none."""
    name, email = settings.get("privacy_contact_name"), settings.get("privacy_contact_email")
    return (f"{name} ({email})" if name and email else (email or name)) or None


def close_text(reason: str, settings: dict[str, Any], language: object = None) -> str:
    """What the customer reads when a person closes the case. Templates only. The no-remedy
    wording names the contact and the National Consumer Helpline (owner decision M2); with no
    contact set it drops that clause rather than point at nobody."""
    if reason == "no_remedy":
        contact = contact_line(settings)
        days = settings["grievance_target_days"]
        if contact:
            return t("close.no_remedy", language, contact=contact, days=days)
        return t("close.no_remedy_nocontact", language)
    return t(f"close.{reason}", language)


def customer_message(opened_at: datetime, settings: dict[str, Any], language: object = None) -> str:
    """Template only: no model text, no promise beyond our own target."""
    contact = contact_line(settings)
    parts = [t("privacy.received", language)]
    if contact:
        parts.append(t("privacy.reach", language, contact=contact))
    when = format_date(target_date(opened_at, settings), language)  # month name, never 10/11
    parts.append(t("privacy.target", language, date=when))
    return " ".join(parts)


def flag_due_soon(engine: Engine, tenant_id: uuid.UUID, now: datetime) -> list[str]:
    """Audit `grievance.due_soon` once per open privacy case older than 75% of the target.
    Staff see it in the case events; the customer's text does not change."""
    flagged = []
    with tenant_session(tenant_id, engine) as s:
        settings = effective_settings(s)
        days = settings["grievance_target_days"]
        cutoff = now - timedelta(days=days * DUE_SOON_FRACTION)
        already = select(AuditEvent.id).where(
            AuditEvent.event == DUE_SOON_EVENT,
            AuditEvent.entity_type == "case",
            AuditEvent.entity_id == Case.id,
        )
        cases = s.scalars(
            select(Case)
            .where(
                Case.category == PRIVACY_CATEGORY,
                Case.status.notin_(CLOSED_STATUSES),
                Case.opened_at <= cutoff,
                ~already.exists(),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for case in cases:
            audit.record(
                s,
                tenant_id,
                actor_type="system",
                actor_id=None,
                event=DUE_SOON_EVENT,
                entity_type="case",
                entity_id=case.id,
                payload={
                    "target_days": days,
                    "internal_target_on": target_date(case.opened_at, settings).isoformat(),
                },
            )
            flagged.append(str(case.id))
    return flagged
