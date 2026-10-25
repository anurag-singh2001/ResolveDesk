"""The deterministic lateness rule on real order rows (E3.5), for every tenant whose pack maps
a category to lateness tiers: the order's own date picks the tiers, the tier's percent is
capped by refund_max_percent, and a customer-caused delay on record earns nothing."""

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.models import Case, Customer, Fulfilment, Transaction, User
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import tenant_id_for
from app.engine.eligibility import order_facts
from app.engine.resolver import decide_remedy, late_tier
from tests.unit.test_late_tiers import _change_dates


class _Rollback(Exception):
    pass


@pytest.fixture
def late_order(app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    email = next(u.email for u in cfg.users if u.role == "customer")
    with tenant_session(tid, app_engine) as s:
        category = next((c for c, r in tenant_pack(s).remedies.items() if r == "late_tiers"), None)
        uid = s.scalar(select(User.id).where(User.email == email))
        cust = s.scalar(select(Customer.id).where(Customer.user_id == uid))
        order_id = s.scalar(
            select(Transaction.id)
            .join(Fulfilment, Fulfilment.transaction_id == Transaction.id)
            .where(Transaction.customer_id == cust, Fulfilment.status == "completed")
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        )
    if category is None:
        pytest.skip("this tenant's pack has no lateness tiers")
    return tid, order_id, category


def _judge(s, order_id, category, placed_on, minutes, cause=None):
    """Move the order to `placed_on`, make it `minutes` late, and ask the rule."""
    order = s.get(Transaction, order_id)
    f = s.scalar(select(Fulfilment).where(Fulfilment.transaction_id == order_id))
    order.placed_at = datetime.combine(placed_on, time(12), UTC)
    f.promised_at = order.placed_at + timedelta(minutes=40)
    f.completed_at = f.promised_at + timedelta(minutes=minutes, seconds=30)
    f.attributes = {"delay_cause": cause} if cause else {}
    s.flush()
    return decide_remedy(s, Case(category=category, transaction_id=order_id))


def test_each_tier_applies_on_the_dates_it_is_in_force(app_engine, late_order):
    tid, order_id, category = late_order
    with pytest.raises(_Rollback), tenant_session(tid, app_engine) as s:
        _, facts = order_facts(s, order_id)
        tiers, cap = facts.settings["late_delivery_tiers"], facts.settings["refund_max_percent"]
        refunds = 0
        for day in _change_dates(tiers):
            for minutes in sorted({t["min_minutes_late"] for t in tiers}):
                tier = late_tier(tiers, minutes, day)
                remedy = _judge(s, order_id, category, day, minutes)
                if tier is None or tier["remedy"] == "apology":
                    assert (remedy.outcome, remedy.action) == ("apology", None), (day, minutes)
                elif tier["remedy"] == "voucher":
                    assert remedy.action == "free_item_voucher", (day, minutes)
                else:
                    assert remedy.action in ("refund", None), (day, minutes)
                    if remedy.action == "refund":  # None: nothing left to refund
                        assert f"{min(tier['percent'], cap)}% refund tier" in remedy.reason
                        refunds += 1
        if facts.refundable_paise and any(t["remedy"] == "refund_percent" for t in tiers):
            assert refunds  # the refund branch really ran
        raise _Rollback


def test_a_customer_caused_delay_earns_no_remedy(app_engine, late_order):
    tid, order_id, category = late_order
    with pytest.raises(_Rollback), tenant_session(tid, app_engine) as s:
        _, facts = order_facts(s, order_id)
        today = datetime.now(UTC).date()
        for cause in facts.settings["late_delivery_excluded_causes"]:
            remedy = _judge(s, order_id, category, today, 300, cause=cause)
            assert (remedy.outcome, remedy.action) == ("apology", None), cause
        # A cause that isn't excluded (e.g. the kitchen's) still gets the tier's remedy.
        assert _judge(s, order_id, category, today, 300, cause="kitchen_delay").action
        raise _Rollback
