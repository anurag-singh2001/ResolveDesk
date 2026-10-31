"""The plain-language "what you get when..." summary (S8.2).

Generated in code from the same sources the executor path uses: the tenant's pack rules
(`remedies`, `late_delivery_tiers`) and the effective settings. The amounts are the ones
`resolver` applies (`voucher_ceiling_paise`, `refund_max_percent`), "instant" vs "a team member
decides" comes from the action's own `can_auto_approve`, money goes through `format_inr`, and
every sentence is an i18n template: no model text, so the words cannot drift from the rule.
tests/integration/test_rules_summary.py pins the figures to `decide_remedy`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.base import Facts, get_action
from app.core.business_time import business_date
from app.core.i18n import TEMPLATES, format_date, normalize, t
from app.core.models import PolicyDocument, TenantSetting, VerticalPackRow
from app.core.money import format_inr
from app.core.settings_resolver import effective_settings, tenant_pack
from app.core.verticals import RefundPercentOption, VerticalPack, option_code, rule_options
from app.engine.privacy import PRIVACY_CATEGORY
from app.engine.resolver import voucher_ceiling_paise

# Categories the customer picks only to ask a question: no remedy to describe.
_NO_RULE_CATEGORIES = {"status_question"}

_VOUCHER_KEYS = ["voucher_max_paise", "voucher_auto_approve_max_paise", "voucher_percent"]
_FAIR_USE_KEY = "fair_use_max_grants_30d"
_REFUND_KEYS = ["refund_max_percent"]
_LATE_KEYS = ["late_delivery_tiers", "late_delivery_excluded_causes"]


@dataclass
class RuleLine:
    """One thing a customer may get. The numbers are for tests and the staff view; `text` is
    what customers read."""

    code: str  # voucher | refund_50pct | refund_missing | apology (the option code)
    kind: str  # voucher | refund | refund_missing | apology
    text: str
    approval: str | None  # instant | team | None (an apology needs no approval)
    approval_text: str | None
    max_paise: int | None = None
    percent: int | None = None  # of the order total
    min_minutes_late: int | None = None
    label: str | None = None  # tier heading


@dataclass
class CategoryRule:
    category: str
    title: str
    options: list[RuleLine] = field(default_factory=list)  # choose between these
    tiers: list[RuleLine] = field(default_factory=list)  # by minutes late (ascending)
    notes: list[str] = field(default_factory=list)
    decided_by: str = "team"  # instant | team | mixed
    setting_keys: list[str] = field(default_factory=list)


@dataclass
class RulesSummary:
    language: str
    pack_name: str
    pack_version: int
    pack_updated: date
    settings_updated: date | None
    in_force_since: date
    in_force_text: str
    categories: list[CategoryRule]
    settings: list[dict[str, Any]]  # key, value, source (staff view only)


def _title(category: str, language: str) -> str:
    key = f"rules.category.{category}"
    return t(key, language) if key in TEMPLATES else category.replace("_", " ").capitalize()


def _approval(action: str, amount_paise: int, settings: dict) -> str:
    """The same check approvals.auto_decide makes for the action, minus the customer's own
    history (that is the fair-use note)."""
    cls = get_action(action)
    if not cls.auto_approvable or amount_paise <= 0 or cls.amount_field is None:
        return "team"
    inp = cls.Input.model_validate(
        {
            "transaction_id": uuid.UUID(int=0),
            cls.amount_field: amount_paise,
            "reason": "rules summary",
        }
    )
    return "instant" if cls().can_auto_approve(inp, Facts(settings=settings)) else "team"


def _timing(approval: str, language: str) -> str:
    return t(f"option.timing.{approval}", language)


def _voucher(settings: dict, language: str) -> RuleLine:
    cap = voucher_ceiling_paise(settings)
    pct = settings.get("voucher_percent", 100)
    key = "rules.voucher.order" if pct >= 100 else "rules.voucher.percent"
    approval = _approval("free_item_voucher", cap, settings)
    return RuleLine(
        "voucher",
        "voucher",
        t(key, language, amount=format_inr(cap), percent=pct),
        approval,
        _timing(approval, language),
        max_paise=cap,
        percent=pct,
    )


def _refund_percent(percent: int, settings: dict, language: str, code: str) -> RuleLine:
    pct = min(percent, settings["refund_max_percent"])  # the tenant's ceiling, as the resolver
    return RuleLine(
        code,
        "refund",
        t("rules.refund.percent", language, percent=pct),
        "team",
        _timing("team", language),
        percent=pct,
    )


def _refund_missing(settings: dict, language: str) -> RuleLine:
    pct = settings["refund_max_percent"]
    return RuleLine(
        "refund_missing",
        "refund_missing",
        t("rules.refund.missing", language, percent=pct),
        "team",
        _timing("team", language),
        percent=pct,
    )


def _option_line(option: Any, settings: dict, language: str) -> RuleLine:
    if isinstance(option, RefundPercentOption):
        return _refund_percent(option.refund_percent, settings, language, option_code(option))
    if option == "refund_missing":
        return _refund_missing(settings, language)
    return _voucher(settings, language)  # "voucher"


def _in_force(tier: dict, today: date) -> bool:
    start, end = tier.get("effective_from"), tier.get("effective_to")
    return (start is None or date.fromisoformat(start) <= today) and (
        end is None or today < date.fromisoformat(end)
    )


def _tier_lines(settings: dict, language: str, today: date) -> list[RuleLine]:
    """Tiers in force today (the dated-tier rule `late_tier` applies to an order's date)."""
    lines: list[RuleLine] = []
    tiers = sorted(settings["late_delivery_tiers"], key=lambda x: x["min_minutes_late"])
    for tier in tiers:
        if not _in_force(tier, today):
            continue
        if tier["remedy"] == "apology":
            line = RuleLine("apology", "apology", t("rules.apology", language), None, None)
        elif tier["remedy"] == "voucher":
            line = _voucher(settings, language)
        else:
            line = _refund_percent(tier.get("percent", 0), settings, language, "refund")
        line.min_minutes_late = tier["min_minutes_late"]
        line.label = t("rules.tier.label", language, minutes=tier["min_minutes_late"])
        lines.append(line)
    return lines


def _decided_by(lines: list[RuleLine]) -> str:
    kinds = {line.approval for line in lines if line.approval}
    if kinds == {"instant"}:
        return "instant"
    return "mixed" if "instant" in kinds else "team"


def _category(
    category: str, pack: VerticalPack, settings: dict, language: str, today: date
) -> CategoryRule:
    row = CategoryRule(category, _title(category, language))
    if category == PRIVACY_CATEGORY:
        row.notes.append(t("rules.privacy", language))
        return row
    rule = pack.remedies.get(category)
    if rule is None:
        row.notes.append(t("rules.escalate", language))
        return row
    for option in rule_options(rule):
        if option == "late_tiers":
            row.tiers = _tier_lines(settings, language, today)
            row.setting_keys += _LATE_KEYS + _REFUND_KEYS + _VOUCHER_KEYS
            if settings["late_delivery_excluded_causes"]:
                row.notes.append(t("rules.late.excluded", language))
        else:
            line = _option_line(option, settings, language)
            row.options.append(line)
            row.setting_keys += _VOUCHER_KEYS if line.kind == "voucher" else _REFUND_KEYS
    lines = row.options + row.tiers
    row.decided_by = _decided_by(lines)
    if any(line.kind == "voucher" and line.approval == "instant" for line in lines):
        row.notes.append(t("rules.fair_use", language, count=settings[_FAIR_USE_KEY]))
        row.setting_keys.append(_FAIR_USE_KEY)
    row.setting_keys = list(dict.fromkeys(row.setting_keys))
    return row


def build_rules_summary(
    session: Session, language: object, now: datetime, *, staff: bool
) -> RulesSummary:
    """The summary for the session's tenant at organisation level (brand and outlet overrides
    can only lower a limit further). `staff` adds the setting keys with the level that set them."""
    lang = normalize(language)
    pack = tenant_pack(session)
    settings = effective_settings(session)
    today = business_date(now, settings)
    cats = [
        _category(c, pack, settings, lang, today)
        for c in pack.issue_categories
        if c not in _NO_RULE_CATEGORIES
    ]
    overrides = {
        row.key: row
        for row in session.scalars(
            select(TenantSetting).where(
                TenantSetting.brand_id.is_(None), TenantSetting.location_id.is_(None)
            )
        )
    }
    used = list(dict.fromkeys(k for c in cats for k in c.setting_keys))
    pack_row = session.scalars(
        select(VerticalPackRow).where(VerticalPackRow.slug == pack.slug)
    ).one()
    pack_updated = business_date(pack_row.updated_at, settings)
    stamps = [business_date(overrides[k].updated_at, settings) for k in used if k in overrides]
    # "In force since" must be a real date. pack_row.updated_at is only when the pack was last
    # refreshed from its files (every `make refresh`), so it is NOT used. The dates that mean
    # something: when the policies in force took effect, and when an owner last changed a setting
    # these rules use. With neither, the pack's first load.
    docs_from = session.scalars(
        select(PolicyDocument.effective_from).where(
            PolicyDocument.brand_id.is_(None),
            PolicyDocument.location_id.is_(None),
            PolicyDocument.effective_from <= today,
            (PolicyDocument.effective_to.is_(None)) | (PolicyDocument.effective_to > today),
        )
    ).all()
    since = max(
        [*docs_from, *stamps] or [business_date(pack_row.created_at, settings)],
    )
    detail = []
    if staff:
        detail = [
            {
                "key": k,
                "value": settings[k],
                "source": "tenant_override" if k in overrides else "pack_default",
            }
            for k in used
            if k in settings  # a pack stored before this key existed must not break the page
        ]
    return RulesSummary(
        language=lang,
        pack_name=pack.name,
        pack_version=pack.version,
        pack_updated=pack_updated,
        settings_updated=max(stamps) if stamps else None,
        in_force_since=since,
        in_force_text=t("rules.in_force", lang, date=format_date(since, lang)),
        categories=cats,
        settings=detail,
    )
