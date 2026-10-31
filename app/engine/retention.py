"""DPDP retention for support data (S5.1). Redacts personal free text and contact data; never
deletes or rewrites anything else. IRREVERSIBLE, so it is a dry run unless apply=True.

For each tenant, in one RLS-scoped transaction (no network call inside it):
1. Cases `resolved`/`closed` for longer than `support_retention_days` and not on legal hold
   have their ticket message bodies replaced by MESSAGE_MARKER.
2. Of those cases' customers, the contact fields (phone, email, name) are redacted only when
   the customer has no open case, no case changed or held inside the period, no order inside
   the period, and no login account (those are the S5.2 erasure flow's business).

Guards (data is kept while any of these exist, because a person or the money flow may still
need it): an open ticket (on the case, or for the customer even with no case); a proposal on
the case with no decision yet; an execution not yet settled (not succeeded/failed, or succeeded
without a final verification); a refund operation still in flight (reserved, submitted,
unknown, pending_reconciliation), found via the case's proposals and, for contacts, also via
the customer's orders.

Untouched by design: money columns, proposals, approvals, executions, verifications, refund
operations, and audit_events (append-only; their payloads carry ids, codes and counts, not
contact data or message text). "Closed at" is cases.updated_at: a closed case is not edited
again. Running it twice changes nothing more (already-redacted rows are not selected). The
dry run counts with the same predicates, using SELECTs only.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, exists, func, select, update

from app.core import audit
from app.core.db import tenant_session
from app.core.models import (
    ActionProposal,
    Approval,
    Case,
    Customer,
    Execution,
    RefundOperation,
    Ticket,
    TicketMessage,
    Transaction,
    Verification,
)
from app.core.settings_resolver import effective_settings
from app.core.telemetry import run_job
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant, tenant_dirs
from app.engine.approvals import not_superseded
from app.engine.cases import OPEN_STATUSES
from app.engine.executor import TERMINAL as EXEC_FINAL
from app.engine.verifier import FINAL as VERIFY_FINAL

log = logging.getLogger(__name__)

MESSAGE_MARKER = "[redacted after retention period]"
NAME_MARKER = "[redacted]"
SETTING = "support_retention_days"
DEFAULT_DAYS = 365
MIN_DAYS = 365  # DPDP Rule 8(3) one-year floor (provisional reading, not legal advice)
FINISHED = ("resolved", "closed")
REFUND_IN_FLIGHT = ("reserved", "submitted", "unknown", "pending_reconciliation")


@dataclass
class RetentionReport:
    cases: int = 0  # cases that had (or, in a dry run, would have) message text redacted
    messages: int = 0
    customers: int = 0
    applied: bool = False


def retention_days(settings: dict) -> int:
    value = settings.get(SETTING, DEFAULT_DAYS)
    if type(value) is not int:
        return DEFAULT_DAYS
    return max(value, MIN_DAYS)


def unsettled_case_ids(tenant_id: uuid.UUID):
    """Cases with money-flow work in progress: an undecided proposal, an unsettled execution,
    or a refund still in flight."""
    p = ActionProposal
    # A superseded proposal never gets an approval (S7.10): it is not "undecided", its
    # replacement is.
    undecided = (
        ~exists().where(Approval.tenant_id == tenant_id, Approval.proposal_id == p.id)
        & not_superseded()
    )
    unsettled_exec = exists().where(
        Execution.tenant_id == tenant_id,
        Execution.proposal_id == p.id,
        (Execution.status.not_in(EXEC_FINAL))
        | (
            (Execution.status == "succeeded")
            & ~exists().where(
                Verification.tenant_id == tenant_id,
                Verification.execution_id == Execution.id,
                Verification.status.in_(VERIFY_FINAL),
            )
        ),
    )
    refund_open = exists().where(
        RefundOperation.tenant_id == tenant_id,
        RefundOperation.proposal_id == p.id,
        RefundOperation.status.in_(REFUND_IN_FLIGHT),
    )
    return select(p.case_id).where(
        p.tenant_id == tenant_id, undecided | unsettled_exec | refund_open
    )


def purge_tenant(
    engine: Engine, tenant_id: uuid.UUID, now: datetime | None = None, apply: bool = False
) -> RetentionReport:
    """Dry run by default: counts what would change with SELECTs and writes nothing."""
    now = now or datetime.now(UTC)
    report = RetentionReport(applied=apply)
    with tenant_session(tenant_id, engine) as s:
        cutoff = now - timedelta(days=retention_days(effective_settings(s)))
        unsettled = unsettled_case_ids(tenant_id)
        eligible = select(Case.id).where(
            Case.tenant_id == tenant_id,
            Case.status.in_(FINISHED),
            Case.updated_at < cutoff,
            Case.legal_hold.is_(False),
            Case.id.not_in(unsettled),
        )
        # Messages of an eligible case's tickets, only once the ticket itself is settled (an
        # open or escalated ticket is still being worked by a person).
        tickets = select(Ticket.id).where(
            Ticket.tenant_id == tenant_id,
            Ticket.case_id.in_(eligible),
            Ticket.status.in_(("resolved", "closed")),
        )
        in_scope = (
            TicketMessage.tenant_id == tenant_id,
            TicketMessage.ticket_id.in_(tickets),
            TicketMessage.body != MESSAGE_MARKER,
        )
        report.cases = (
            s.scalar(
                select(func.count(func.distinct(Ticket.case_id)))
                .select_from(TicketMessage)
                .join(Ticket, Ticket.id == TicketMessage.ticket_id)
                .where(*in_scope, Ticket.tenant_id == tenant_id)
            )
            or 0
        )
        report.messages = s.scalar(select(func.count()).select_from(TicketMessage).where(*in_scope))

        # Contact data: customers of the eligible cases who are otherwise inactive.
        busy_case = exists().where(
            Case.tenant_id == tenant_id,
            Case.customer_id == Customer.id,
            (Case.status.in_(OPEN_STATUSES))
            | (Case.updated_at >= cutoff)
            | (Case.legal_hold.is_(True))
            | (Case.id.in_(unsettled)),
        )
        recent_order = exists().where(
            Transaction.tenant_id == tenant_id,
            Transaction.customer_id == Customer.id,
            Transaction.placed_at >= cutoff,
        )
        open_ticket = exists().where(
            Ticket.tenant_id == tenant_id,
            Ticket.customer_id == Customer.id,
            Ticket.status.in_(("open", "escalated")),
        )
        refund_on_order = exists().where(
            RefundOperation.tenant_id == tenant_id,
            RefundOperation.status.in_(REFUND_IN_FLIGHT),
            RefundOperation.transaction_id.in_(
                select(Transaction.id).where(
                    Transaction.tenant_id == tenant_id, Transaction.customer_id == Customer.id
                )
            ),
        )
        contact_scope = (
            Customer.tenant_id == tenant_id,
            Customer.id.in_(
                select(Case.customer_id).where(Case.tenant_id == tenant_id, Case.id.in_(eligible))
            ),
            Customer.user_id.is_(None),
            ~busy_case,
            ~recent_order,
            ~open_ticket,
            ~refund_on_order,
            (Customer.phone.is_not(None))
            | (Customer.email.is_not(None))
            | (Customer.name != NAME_MARKER),
        )
        report.customers = s.scalar(
            select(func.count()).select_from(Customer).where(*contact_scope)
        )

        if apply:
            s.execute(update(TicketMessage).where(*in_scope).values(body=MESSAGE_MARKER))
            s.execute(
                update(Customer)
                .where(*contact_scope)
                .values(phone=None, email=None, name=NAME_MARKER)
            )
            if report.messages or report.customers:  # counts only, never content
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


def purge_all(
    engine: Engine, now: datetime | None = None, apply: bool = False
) -> dict[str, RetentionReport | None]:
    """Every tenant folder, each in its own RLS scope. One failure doesn't stop the others;
    a failed tenant maps to None so the caller can exit non-zero."""
    reports: dict[str, RetentionReport | None] = {}
    for folder in tenant_dirs():
        slug = load_tenant(folder).slug
        try:
            tid = tenant_id_for(slug)
            reports[slug] = run_job(
                engine,
                tid,
                "retention_apply" if apply else "retention_dry_run",
                lambda t=tid: purge_tenant(engine, t, now, apply),
                lambda r: {"messages": r.messages, "cases": r.cases, "customers": r.customers},
            )
        except Exception:
            log.exception("retention failed for tenant %s", slug)
            reports[slug] = None
    return reports
