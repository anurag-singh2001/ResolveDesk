"""What the business holds about one customer (S8.5a, DPDP access, plain language).

Everything is read for ONE customer that the route took from the token, never from the request
(hard rule 8). Each item carries a purpose, a retention line built from tenant settings
(labelled provisional while the owner has not confirmed the figures), whether it serves help
or marketing, and the customer's own count or masked value. Copy comes from app/core/i18n.py;
nothing here names a tenant. Nothing in this module logs or audits personal content.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.i18n import normalize, t
from app.core.models import (
    ActionProposal,
    Case,
    ConsentEvent,
    Customer,
    Execution,
    Payment,
    Ticket,
    TicketMessage,
    Transaction,
)
from app.engine.retention import retention_days

# Facts the page states are decided in CODE, never by a tenant override (safety review B1).
# Claims under "what we do not keep" show only when the key is in CONFIRMED_NOT_KEPT (empty
# until the owner has checked each claim against the payment mock) AND the tenant setting
# `data_not_kept` lists it; the setting alone never enables a claim.
KNOWN_NOT_KEPT = ("card_numbers", "upi_details")
CONFIRMED_NOT_KEPT: frozenset[str] = frozenset()
# Retention figures stay labelled provisional until counsel confirms them; flip in code only.
RETENTION_CONFIRMED = False
# The statutory outer limit for answering a request; the internal target is a setting.
LEGAL_CEILING_DAYS = 90
DEFAULT_RECORD_YEARS = 7
HEADINGS = ("title", "item", "yours", "purpose", "keep", "use", "processors", "not_kept", "contact")
RETENTION_FLOOR_DAYS = 365  # same one-year floor the retention job applies


@dataclass(frozen=True)
class Item:
    key: str
    use: str  # help | marketing
    retention: str  # contact | messages | records | consents


ITEMS = (
    Item("name", "help", "contact"),
    Item("phone", "help", "contact"),
    Item("email", "help", "contact"),
    Item("orders", "help", "records"),
    Item("messages", "help", "messages"),
    Item("payments", "help", "records"),
    Item("remedies", "help", "records"),
    Item("consents", "marketing", "consents"),
)


def mask_phone(phone: str) -> str:
    digits = phone.strip()
    return "*" * max(len(digits) - 4, 0) + digits[-4:]


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _count(db: Session, stmt) -> int:
    return db.scalar(stmt) or 0


def _counts(db: Session, customer: Customer) -> dict[str, int]:
    cid = customer.id
    return {
        "orders": _count(
            db, select(func.count()).select_from(Transaction).where(Transaction.customer_id == cid)
        ),
        "messages": _count(
            db,
            select(func.count())
            .select_from(TicketMessage)
            .join(Ticket, Ticket.id == TicketMessage.ticket_id)
            .where(Ticket.customer_id == cid),
        ),
        "payments": _count(
            db,
            select(func.count())
            .select_from(Payment)
            .join(Transaction, Transaction.id == Payment.transaction_id)
            .where(Transaction.customer_id == cid),
        ),
        # Money remedies proposed on this customer's cases (refunds and vouchers).
        "remedies": _count(
            db,
            select(func.count())
            .select_from(ActionProposal)
            .join(Case, Case.id == ActionProposal.case_id)
            .where(
                Case.customer_id == cid,
                ActionProposal.amount_paise.is_not(None),
                # Only remedies that were approved and run, not proposals still waiting.
                exists().where(Execution.proposal_id == ActionProposal.id),
            ),
        ),
        "consents": _count(
            db,
            select(func.count()).select_from(ConsentEvent).where(ConsentEvent.customer_id == cid),
        ),
    }


def _years(settings: dict[str, Any]) -> int:
    value = settings.get("payment_retention_years")
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else DEFAULT_RECORD_YEARS
    )


def _retention(kind: str, settings: dict[str, Any], lang: str) -> str:
    # Mirrors app/engine/retention.py: message text goes only after the retention period for
    # closed cases with nothing unsettled; contact data of a signed-in customer is not removed
    # by that job at all (only by an erasure request).
    if kind == "messages":
        return t("held.ret.messages", lang, days=retention_days(settings))
    if kind == "contact":
        return t("held.ret.contact", lang)
    if kind == "records":
        return t("held.ret.records", lang, years=_years(settings))
    return t("held.ret.consents", lang)


def processors(settings: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for p in settings.get("data_processors") or []:
        if isinstance(p, dict) and all(
            isinstance(p.get(k), str) and p[k] for k in ("name", "role", "data")
        ):
            out.append({"name": p["name"], "role": p["role"], "data": p["data"]})
    return out


def contact(settings: dict[str, Any], lang: str) -> dict[str, Any]:
    days = settings.get("grievance_target_days")
    days = days if isinstance(days, int) and 0 < days <= LEGAL_CEILING_DAYS else 30
    name = str(settings.get("privacy_contact_name") or "")
    email = str(settings.get("privacy_contact_email") or "")
    configured = bool(email)
    return {
        "label": t("held.contact.label", lang),
        "configured": configured,
        "name": name if configured else "",
        "email": email,
        "response_target_days": days,
        "legal_ceiling_days": LEGAL_CEILING_DAYS,
        "response_text": t("held.contact.target", lang, days=days, ceiling=LEGAL_CEILING_DAYS)
        if configured
        else t("held.contact.unset", lang),
    }


def what_we_hold(db: Session, customer: Customer, settings: dict[str, Any]) -> dict[str, Any]:
    lang = normalize(customer.preferred_language)
    counts = _counts(db, customer)
    values = {
        "name": customer.name or None,
        "phone": mask_phone(customer.phone) if customer.phone else None,
        "email": mask_email(customer.email) if customer.email else None,
    }
    provisional = not RETENTION_CONFIRMED
    items = []
    for item in ITEMS:
        if item.key in values and values[item.key] is None:
            continue  # we hold nothing under this heading for this customer
        if item.key in values:
            value, count = values[item.key], None
            summary = value
        else:
            value, count = None, counts[item.key]
            summary = t("held.count", lang, n=count)
        items.append(
            {
                "key": item.key,
                "label": t(f"held.label.{item.key}", lang),
                "purpose": t(f"held.purpose.{item.key}", lang),
                "use": item.use,
                "use_label": t(f"held.use.{item.use}", lang),
                "retention": _retention(item.retention, settings, lang),
                "retention_provisional": provisional,
                "value": value,
                "count": count,
                "summary": summary,
            }
        )
    claims = [
        t(f"held.not_kept.{k}", lang)
        for k in (settings.get("data_not_kept") or [])
        if k in KNOWN_NOT_KEPT and k in CONFIRMED_NOT_KEPT
    ]
    return {
        "language": lang,
        "headings": {k: t(f"held.h.{k}", lang) for k in HEADINGS},
        "items": items,
        "processors": processors(settings),
        "not_kept": claims,  # empty (hidden) unless the tenant setting backs a claim
        "provisional_label": t("held.provisional", lang) if provisional else None,
        "contact": contact(settings, lang),
    }
