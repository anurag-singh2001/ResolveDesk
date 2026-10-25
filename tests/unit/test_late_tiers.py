"""Late-delivery tiers (E3.5): dated tiers follow the order-date rule, and the tenant data and
the policy prose agree. Runs for every tenant; tenants without lateness tiers check nothing."""

import re
from datetime import date, timedelta

from app.core.settings_resolver import resolve
from app.core.tenant_config import load_tenant
from app.core.verticals import load_pack
from app.engine.resolver import late_tier
from app.rag.policy_files import policy_files

CHANGE = "2026-10-26"
R = "refund_percent"
TIERS = [
    {"min_minutes_late": 0, "remedy": "apology"},
    {"min_minutes_late": 20, "remedy": "voucher"},
    {"min_minutes_late": 45, "remedy": R, "percent": 50, "effective_to": CHANGE},
    {"min_minutes_late": 45, "remedy": R, "percent": 25, "effective_from": CHANGE},
    {"min_minutes_late": 60, "remedy": R, "percent": 50, "effective_from": CHANGE},
]
BEFORE, ON = date(2026, 10, 25), date(2026, 10, 26)


def _pick(minutes, placed_on):
    t = late_tier(TIERS, minutes, placed_on)
    return t and (t["remedy"], t.get("percent"))


def test_graduated_tiers_apply_from_their_start_date():
    assert [_pick(m, ON) for m in (0, 19, 20, 44, 45, 59, 60, 200)] == [
        ("apology", None), ("apology", None), ("voucher", None), ("voucher", None),
        ("refund_percent", 25), ("refund_percent", 25), ("refund_percent", 50),
        ("refund_percent", 50),
    ]  # fmt: skip


def test_older_orders_keep_the_tiers_in_force_when_they_were_placed():
    assert _pick(45, BEFORE) == ("refund_percent", 50)
    assert _pick(59, BEFORE) == ("refund_percent", 50)
    assert _pick(30, BEFORE) == ("voucher", None)


def test_no_tier_reached_means_none():
    assert late_tier([{"min_minutes_late": 20, "remedy": "voucher"}], 5, ON) is None


def _org_settings(tenant):
    cfg = load_tenant(tenant)
    pack = load_pack(cfg.vertical_pack)
    return pack, resolve(pack.settings, cfg.settings.org)


def _change_dates(tiers):
    dates = {date(2000, 1, 1)}
    for t in tiers:
        for key in ("effective_from", "effective_to"):
            if t.get(key):
                d = date.fromisoformat(t[key])
                dates |= {d, d - timedelta(days=1)}
    return sorted(dates)


def test_tenant_tiers_are_well_formed_on_every_date(tenant):
    _, s = _org_settings(tenant)
    tiers = s["late_delivery_tiers"]
    for t in tiers:
        assert t["remedy"] in {"apology", "voucher", "refund_percent"}, t
        assert type(t["min_minutes_late"]) is int and t["min_minutes_late"] >= 0
        if t["remedy"] == "refund_percent":
            assert type(t["percent"]) is int and 0 < t["percent"] <= 100
    for day in _change_dates(tiers):
        in_force = [t["min_minutes_late"] for t in tiers if late_tier([t], 10**6, day)]
        assert len(in_force) == len(set(in_force)), (day, in_force)  # one tier per boundary


def test_late_policy_percents_match_the_tiers_in_force(tenant):
    """Prose percents must not drift from the tiers code applies on that version's dates."""
    _, s = _org_settings(tenant)
    tiers = s["late_delivery_tiers"]
    for f in policy_files(tenant):
        if f.meta.topic != "late_delivery" or f.meta.scope != "org":
            continue
        text = " ".join(sec.content for sec in f.sections)
        stated = {int(p) for p in re.findall(r"Refund (\d+)% of the order", text)}
        if not stated:
            continue  # an older version without refund tiers, judged by its own text
        day = f.meta.effective_from
        applied = {
            t["percent"]
            for t in tiers
            if t["remedy"] == "refund_percent" and late_tier([t], 10**6, day)
        }
        assert stated == applied, (f.meta.id, stated, applied)


WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}


def test_fair_use_policy_states_the_configured_threshold(tenant):
    _, s = _org_settings(tenant)
    checked = 0
    for f in policy_files(tenant):
        if f.meta.topic != "fair_use":
            continue
        text = " ".join(sec.content for sec in f.sections)
        for word in re.findall(r"had (\w+) or more refunds or vouchers approved", text):
            assert WORDS[word] == s["fair_use_max_grants_30d"], (f.meta.id, word)
            checked += 1
    assert checked, "each tenant's fair-use policy states its threshold"


def test_voucher_auto_approve_cap_is_a_lowerable_pack_default(tenant):
    pack, s = _org_settings(tenant)
    spec = pack.settings["voucher_auto_approve_max_paise"]
    assert spec.kind == "limit" and spec.default == 15000  # Rs 150 (decision 2026-10-26)
    assert s["voucher_auto_approve_max_paise"] <= spec.default
    assert pack.settings["fair_use_max_grants_30d"].kind == "limit"


def test_every_auto_approvable_action_counts_toward_fair_use():
    """Fair use only guards what it counts: an auto-approvable action that gives the customer
    something of value (it has an amount) but skipped the count would bypass the check."""
    import app.actions  # noqa: F401  (registers every action)
    from app.actions.base import registered_actions

    actions = registered_actions()
    valued = {n: c for n, c in actions.items() if c.auto_approvable and c.amount_field}
    assert valued  # the check is not vacuous
    for name, cls in valued.items():
        if cls.auto_approvable:
            assert cls.counts_as_grant, name


def test_business_date_uses_the_tenant_calendar():
    from datetime import UTC, datetime

    from app.core.business_time import business_date

    just_after_midnight_ist = datetime(2026, 10, 25, 19, 30, tzinfo=UTC)  # 01:00 IST on 26th
    assert business_date(just_after_midnight_ist, {"business_timezone": "Asia/Kolkata"}).day == 26
    assert business_date(just_after_midnight_ist, {"business_timezone": "UTC"}).day == 25
