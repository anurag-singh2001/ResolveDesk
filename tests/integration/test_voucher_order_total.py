"""S7.8 through the real rule: the voucher follows the stored order's total."""

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.models import Case, Customer, Transaction, User
from app.core.settings_resolver import tenant_pack
from app.core.tenancy import tenant_id_for
from app.engine.resolver import decide_remedy


class _Rollback(Exception):
    pass


def test_voucher_follows_the_order_total_and_tiny_orders_escalate(
    app_engine, seeded_history, tenant
):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    email = next(u.email for u in cfg.users if u.role == "customer")
    with pytest.raises(_Rollback), tenant_session(tid, app_engine) as s:
        category = next((c for c, r in tenant_pack(s).remedies.items() if r == "voucher"), None)
        assert category, "each pack has a voucher category"
        uid = s.scalar(select(User.id).where(User.email == email))
        cust = s.scalar(select(Customer.id).where(Customer.user_id == uid))
        order = s.scalars(select(Transaction).where(Transaction.customer_id == cust)).first()
        case = Case(category=category, transaction_id=order.id)

        order.total_paise = 14900  # Rs 149
        s.flush()
        r = decide_remedy(s, case)
        assert r.action == "free_item_voucher"
        assert 0 < r.params["value_paise"] <= 14900
        assert r.params["value_paise"] % 100 == 0

        order.total_paise = 999  # under Rs 10: a person decides
        s.flush()
        r = decide_remedy(s, case)
        assert (r.action, r.outcome) == (None, "escalate")
        raise _Rollback
