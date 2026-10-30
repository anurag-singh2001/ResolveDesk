"""The readable data export (S8.5c): the signed-in customer's own data as sections of plain text
the web page prints. The JSON export (/me/data-export) is a separate, unchanged contract.

Everything here is for ONE customer that the route took from the token (hard rule 8). Money is
formatted from integer paise by the one formatter (hard rule 3); dates are Indian time with a
month name; status words come from case_status so a refund is "confirmed" only when it is
(hard rule 7). Only customer-facing fields go out: no ids other than order numbers and the
customer's own reference, no hashes, no audit or model fields, no staff notes. Copy is in
app/core/i18n.py; nothing names a tenant. Nothing here logs or audits personal content.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import DEFAULT_TIMEZONE
from app.core.i18n import format_date, normalize, t
from app.core.models import Brand, Case, Consent, ConsentEvent, Customer, Location, Transaction
from app.core.money import format_inr
from app.engine import data_held
from app.engine import data_rights as privacy
from app.engine.case_status import case_status

FIELDS = (
    "name", "phone", "email", "reference", "order", "placed", "brand", "place", "total",
    "status", "topic", "opened", "update", "remedy", "amount", "choice", "channel", "role", "data",
)  # fmt: skip


def when(moment: datetime, settings: dict[str, Any], lang: str) -> str:
    """`27 Oct 2026, 14:05`, in the tenant's timezone (Asia/Kolkata by default)."""
    local = moment.astimezone(ZoneInfo(settings.get("business_timezone") or DEFAULT_TIMEZONE))
    return f"{format_date(local.date(), lang)}, {local:%H:%M}"


def _word(prefix: str, value: str, lang: str) -> str:
    """A plain word for a stored code; an unknown code reads as plain text, never an error."""
    try:
        return t(f"{prefix}.{value}", lang)
    except KeyError:
        return t("export.other", lang)  # never the raw stored code


def _field(label: str, value: str) -> dict[str, str]:
    return {"label": label, "value": value}


def readable_export(
    db: Session, customer: Customer, settings: dict[str, Any], now: datetime
) -> dict[str, Any]:
    lang = normalize(customer.preferred_language)
    held = {i["key"]: i for i in data_held.what_we_hold(db, customer, settings)["items"]}
    f = {k: t(f"export.f.{k}", lang) for k in FIELDS}

    def section(key: str, held_key: str | None, records: list[list[dict]], **extra) -> dict:
        h = held.get(held_key) if held_key else None
        return {
            "key": key,
            "title": t(f"export.s.{key}", lang),
            "purpose": h["purpose"] if h else None,
            "retention": h["retention"] if h else None,
            "retention_provisional": bool(h and h["retention_provisional"]),
            "records": records,
            **extra,
        }

    details = [
        _field(f[k], v)
        for k, v in (
            ("name", customer.name),
            ("phone", customer.phone),
            ("email", customer.email),
            ("reference", customer.external_ref),
        )
        if v
    ]

    orders = [
        [
            _field(f["order"], txn.external_ref),
            _field(f["placed"], when(txn.placed_at, settings, lang)),
            _field(f["brand"], brand),
            _field(f["place"], place),
            _field(f["total"], format_inr(txn.total_paise)),
            _field(f["status"], _word("export.o", txn.status, lang)),
        ]
        for txn, brand, place in db.execute(
            select(Transaction, Brand.name, Location.name)
            .join(Brand, Brand.id == Transaction.brand_id)
            .join(Location, Location.id == Transaction.location_id)
            .where(Transaction.customer_id == customer.id)
            .order_by(Transaction.placed_at.desc(), Transaction.id)
        )
    ]

    cases, remedies = [], []
    for case in db.scalars(
        select(Case).where(Case.customer_id == customer.id).order_by(Case.opened_at.desc())
    ):
        st = case_status(db, case, now, lang)
        order = db.get(Transaction, case.transaction_id) if case.transaction_id else None
        if order is not None and order.customer_id != customer.id:
            order = None  # a case can point at someone else's order: never print its number
        ref = [_field(f["order"], order.external_ref)] if order else []
        cases.append(
            [
                *ref,
                _field(f["topic"], _word("rules.category", case.category, lang)),
                _field(f["opened"], when(case.opened_at, settings, lang)),
                _field(f["update"], st.message),
            ]
        )
        # Only remedies that were approved (or later); the message states the verified stage.
        if (
            st.amount_paise is not None
            and st.action
            and st.stage not in ("awaiting_approval", "declined")
        ):
            remedies.append(
                [
                    *ref,
                    _field(f["remedy"], _word("export.r", st.action, lang)),
                    _field(f["amount"], format_inr(st.amount_paise)),
                    _field(f["status"], st.message),
                ]
            )

    on, off = t("export.f.on", lang), t("export.f.off", lang)
    choices = [
        [
            _field(f["choice"], _word("export.c", row.purpose, lang)),
            _field(f["channel"], row.channel.capitalize()),
            _field(f["status"], on if row.granted else off),
        ]
        for row in db.scalars(select(Consent).where(Consent.customer_id == customer.id))
        if row.purpose in privacy.PURPOSES
    ]
    history = [
        [
            _field(f["choice"], _word("export.c", e.purpose, lang)),
            _field(f["status"], t("export.f.agreed" if e.granted else "export.f.stopped", lang)),
            _field(f["placed"], when(e.created_at, settings, lang)),
        ]
        for e in db.scalars(
            select(ConsentEvent)
            .where(ConsentEvent.customer_id == customer.id)
            .order_by(ConsentEvent.created_at, ConsentEvent.id)
        )
        if e.purpose in privacy.PURPOSES
    ]
    processors = [
        [_field(f["name"], p["name"]), _field(f["role"], p["role"]), _field(f["data"], p["data"])]
        for p in data_held.processors(settings)
    ]

    return {
        "language": lang,
        "title": t("export.title", lang),
        "generated": t("export.generated", lang, date=when(now, settings, lang)),
        "tz_note": t("export.tz_note", lang),
        "labels": {
            "why": t("export.why", lang),
            "howlong": t("export.howlong", lang),
            "empty": t("export.empty", lang),
            "history": t("export.f.history", lang),
            "print": t("export.print", lang),
            "back": t("export.back", lang),
        },
        "provisional_label": None if data_held.RETENTION_CONFIRMED else t("held.provisional", lang),
        "sections": [
            section("details", "name", [details] if details else []),
            section("orders", "orders", orders),
            section("cases", "messages", cases),
            section("remedies", "remedies", remedies),
            section("choices", "consents", choices, history=history),
            section("processors", None, processors),
        ],
        "contact": data_held.contact(settings, lang),
    }
