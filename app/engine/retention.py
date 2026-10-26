"""DPDP retention for support data (S5.1). Redacts personal free text and contact data; never
deletes or rewrites anything else.

For each tenant, in one RLS-scoped transaction (no network call inside it):
1. Cases `resolved`/`closed` for longer than `support_retention_days` and not on legal hold
   have their ticket message bodies replaced by MESSAGE_MARKER.
2. Of those cases' customers, the contact fields (phone, email, name) are redacted only when
   the customer has no open case, no case changed or held inside the period, no order inside
   the period, and no login account (those are the S5.2 erasure flow's business).

Untouched by design: money columns, proposals, approvals, executions, verifications, refund
operations, and audit_events (append-only; their payloads carry ids, codes and counts, not
contact data or message text). "Closed at" is cases.updated_at: a closed case is not edited
again. Running it twice changes nothing more (already-redacted rows are not selected).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, exists, select, update

from app.core import audit
from app.core.db import tenant_session
from app.core.models import Case, Customer, Ticket, TicketMessage, Transaction
from app.core.settings_resolver import effective_settings
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine.cases import OPEN_STATUSES

log = logging.getLogger(__name__)

MESSAGE_MARKER = "[redacted after retention period]"
NAME_MARKER = "[redacted]"
SETTING = "support_retention_days"
DEFAULT_DAYS = 365
MIN_DAYS = 365  # DPDP Rule 8(3) one-year floor (provisional reading, not legal advice)
FINISHED = ("resolved", "closed")


@dataclass
class RetentionReport:
    cases: int = 0  # cases that had message text redacted this run
    messages: int = 0
    customers: int = 0


def retention_days(settings: dict) -> int:
    value = settings.get(SETTING, DEFAULT_DAYS)
    if type(value) is not int:
        return DEFAULT_DAYS
    return max(value, MIN_DAYS)


def purge_tenant(
    engine: Engine, tenant_id: uuid.UUID, now: datetime | None = None
) -> RetentionReport:
    now = now or datetime.now(UTC)
    report = RetentionReport()
    with tenant_session(tenant_id, engine) as s:
        cutoff = now - timedelta(days=retention_days(effective_settings(s)))
        eligible = select(Case.id).where(
            Case.status.in_(FINISHED), Case.updated_at < cutoff, Case.legal_hold.is_(False)
        )
        pending = TicketMessage.body != MESSAGE_MARKER
        report.cases = len(
            s.scalars(
                select(Ticket.case_id)
                .join(TicketMessage, TicketMessage.ticket_id == Ticket.id)
                .where(Ticket.case_id.in_(eligible), pending)
                .distinct()
            ).all()
        )
        report.messages = s.execute(
            update(TicketMessage)
            .where(
                TicketMessage.ticket_id.in_(select(Ticket.id).where(Ticket.case_id.in_(eligible))),
                pending,
            )
            .values(body=MESSAGE_MARKER)
        ).rowcount

        # Contact data: customers of the eligible cases who are otherwise inactive.
        recent_case = exists().where(
            Case.customer_id == Customer.id,
            (Case.status.in_(OPEN_STATUSES))
            | (Case.updated_at >= cutoff)
            | (Case.legal_hold.is_(True)),
        )
        recent_order = exists().where(
            Transaction.customer_id == Customer.id, Transaction.placed_at >= cutoff
        )
        report.customers = s.execute(
            update(Customer)
            .where(
                Customer.id.in_(select(Case.customer_id).where(Case.id.in_(eligible))),
                Customer.user_id.is_(None),
                ~recent_case,
                ~recent_order,
                (Customer.phone.is_not(None))
                | (Customer.email.is_not(None))
                | (Customer.name != NAME_MARKER),
            )
            .values(phone=None, email=None, name=NAME_MARKER)
        ).rowcount

        if report.messages or report.customers:  # counts only, never content; none = no row
            audit.record(
                s,
                tenant_id,
                actor_type="system",
                actor_id=None,
                event="retention.redacted",
                entity_type="tenant",
                entity_id=tenant_id,
                payload={
                    "cases": report.cases,
                    "msgs": report.messages,
                    "contacts": report.customers,
                },
            )
    return report


def purge_all(engine: Engine, now: datetime | None = None) -> dict[str, RetentionReport]:
    """Every tenant folder, each in its own RLS scope; one failure doesn't stop the others."""
    reports = {}
    for folder in tenant_dirs():
        slug = load_tenant(folder).slug
        try:
            reports[slug] = purge_tenant(engine, tenant_id_for(slug), now)
        except Exception:
            log.exception("retention failed for tenant %s", slug)
    return reports
