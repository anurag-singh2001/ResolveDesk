"""What an erasure request does, said in plain words, and how a request is shown (S8.5d, R4).

Customer-facing only. Every line in the three lists maps to something real:
- REMOVE mirrors `data_rights._redact` (ticket message text, customer name/phone/email/
  attributes, the login identity, marketing consent switched off).
- KEEP mirrors what `_redact` and retention leave alone (orders, payments, refund operations,
  proposals, approvals, executions, case rows, audit events, consent history, the customer's
  external reference). Retention years come from the same setting data_held shows.
- WAIT mirrors the block codes of `data_rights.erasure_block`.
tests/integration/test_erasure_info.py checks the lists against the code paths. Copy is in
app/core/i18n.py. Nothing here logs or audits personal content, and nothing names a tenant.

A request is only called "done" when its row is `completed`, and that is set only by the
executor (`run_erasure`) after the redaction ran (hard rule 7). The states a customer sees are
the four the code really has; there is no "in progress" because the executor runs in one
transaction and the row is never in a half-done state.
"""

from datetime import timedelta
from typing import Any

from app.core.i18n import format_date, t
from app.core.models import DataRequest
from app.engine import data_held, erasure_notice
from app.engine import data_rights as privacy

REMOVE = ("name", "contact", "messages", "profile", "login", "offers")
KEEP = ("records", "cases", "audit", "consents", "linked", "reference")
WAIT_CODES = ("open_case", "in_flight", "legal_hold")  # plus review and the one-year floor

# Request status in the database -> stage the customer sees.
STAGE = {
    "pending_approval": "received",
    "deferred": "deferred",
    "completed": "done",
    "withdrawn": "withdrawn",
}
CAN_WITHDRAW = ("pending_approval", "deferred")


def _notice_block(channels: list[str], lang: str) -> dict[str, Any]:
    """Says, before the customer confirms, where the one completion message will go (or that
    there is nowhere to send it), and that the destination is kept 7 days only for that."""
    text = (
        t("erase.notice.none", lang)
        if not channels
        else t("erase.notice.sent_to", lang, days=erasure_notice.TTL.days)
    )
    return {
        "channels": channels,
        "default": channels[0] if channels else None,
        "labels": {c: t(f"erase.notice.{c}", lang) for c in channels},
        "text": text,
        "choose": t("erase.notice.choose", lang),
    }


def info(
    settings: dict[str, Any], lang: str, channels: list[str] | tuple[str, ...] = ()
) -> dict[str, Any]:
    """The explanation shown before asking: the three lists, the timing and the contact.
    `channels` are the destinations the signed-in customer has on file (phone, email)."""
    years = data_held._years(settings)
    days = data_held.target_days(settings)
    provisional = not data_held.RETENTION_CONFIRMED
    keep = []
    for key in KEEP:
        why = t(f"erase.keep.{key}.why", lang, years=years)
        keep.append(
            {
                "key": key,
                "label": t(f"erase.keep.{key}", lang),
                "reason": why,
                "provisional": provisional and key == "records",
            }
        )
    wait = [t("erase.wait.review", lang)]
    wait += [t(f"erase.reason.{code}", lang) for code in WAIT_CODES]
    wait.append(t("erase.wait.retention_floor", lang))
    return {
        "language": lang,
        "title": t("erase.title", lang),
        "intro": t("erase.intro", lang),
        "headings": {k: t(f"erase.h.{k}", lang) for k in ("remove", "keep", "wait")},
        "remove": [t(f"erase.remove.{k}", lang) for k in REMOVE],
        "keep": keep,
        "wait": wait,
        "provisional_label": t("held.provisional", lang) if provisional else None,
        "timing": t("held.contact.target", lang, days=days, hours=data_held.ACK_HOURS),
        "target_days": days,
        "contact": data_held.contact(settings, lang),
        "buttons": {
            "request": t("erase.btn.request", lang),
            "confirm": t("erase.btn.confirm", lang),
            "back": t("erase.btn.back", lang),
            "withdraw": t("erase.btn.withdraw", lang),
        },
        "confirm": {
            "title": t("erase.confirm.title", lang),
            "body": t("erase.confirm.body", lang),
        },
        "status_title": t("erase.status.title", lang),
        "completion_notice": _notice_block(list(channels), lang),
    }


def view(req: DataRequest, settings: dict[str, Any], lang: str) -> dict:
    """One request as the customer sees it. Dates: received (created), expected-by (received +
    the tenant target). No legal deadline is stated (owner decision P2)."""
    stage = STAGE[req.status]
    days = data_held.target_days(settings)
    expected = req.created_at + timedelta(days=days)
    reason = privacy.reason_text(req.reason_code, req.deferred_until)
    text = t(f"erase.stage.{stage}.text", lang, date="")
    if stage == "deferred" and req.reason_code in privacy.REASONS:
        until = req.deferred_until.date() if req.deferred_until else None
        date = format_date(until, lang) if until else ""
        text += t(f"erase.reason.{req.reason_code}", lang, date=date)
    elif stage == "done" and req.completed_at:
        text = t("erase.stage.done.text", lang, date=format_date(req.completed_at.date(), lang))
    active = stage in ("received", "deferred")
    # Never show a date the system will not meet: a deferral that runs past the expected-by
    # date (for example the one-year floor) states its own date in the reason instead.
    promise = active and not (req.deferred_until and req.deferred_until > expected)
    return {
        "id": str(req.id),
        "status": req.status,
        "stage": stage,
        "stage_label": t(f"erase.stage.{stage}", lang),
        "stage_text": text,
        "reason_code": req.reason_code,
        "reason": reason,
        "received_at": req.created_at,
        "received_text": t(
            "erase.received_on", lang, date=format_date(req.created_at.date(), lang)
        ),
        # Dates are only promised while the request is open.
        "expected_by": expected if promise else None,
        "expected_text": t(
            "erase.expected_by",
            lang,
            date=format_date(expected.date(), lang),
        )
        if promise
        else None,
        "completed_at": req.completed_at,
        "can_withdraw": req.status in CAN_WITHDRAW,
        "contact": data_held.contact(settings, lang),
    }
