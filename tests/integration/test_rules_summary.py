"""S8.2: the plain-language rules summary stays true. For every tenant, each category's numbers
equal what `decide_remedy` actually allows on a sample order; a setting change shows up with
its date; a customer sees no setting keys, staff do; one tenant's rules never leak into another's.
Categories and options are read from each tenant's own pack (no tenant is named)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.i18n import LANGUAGES
from app.core.models import Case, Customer, Fulfilment, LineItem, TenantSetting, Transaction, User
from app.core.money import format_inr, percent_of
from app.core.settings_resolver import effective_settings, tenant_pack
from app.core.tenancy import tenant_id_for
from app.core.verticals import load_pack, rule_options
from app.engine.eligibility import order_facts
from app.engine.resolver import MIN_VOUCHER_PAISE, decide_remedy
from app.engine.rules_summary import RuleLine, build_rules_summary
from tests.helpers import login
from tests.integration.test_late_tiers_db import _judge


class _Rollback(Exception):
    pass


@pytest.fixture
def sample(app_engine, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    tid = tenant_id_for(cfg.slug)
    email = next(u.email for u in cfg.users if u.role == "customer")
    with tenant_session(tid, app_engine) as s:
        uid = s.scalar(select(User.id).where(User.email == email))
        cust = s.scalar(select(Customer.id).where(Customer.user_id == uid))
        order_id = s.scalar(
            select(Transaction.id)
            .join(Fulfilment, Fulfilment.transaction_id == Transaction.id)
            .where(Transaction.customer_id == cust, Fulfilment.status == "completed")
            .order_by(Transaction.placed_at.desc())
            .limit(1)
        )
    assert order_id is not None
    return cfg, tid, order_id


def _check_line(line: RuleLine, remedy, total: int, refundable: int, missing: int | None = None):
    """The summary line's numbers vs the remedy the resolver produced."""
    if line.kind == "voucher":
        scaled = min(line.max_paise, percent_of(total, line.percent))
        want = scaled - scaled % 100
        if want < MIN_VOUCHER_PAISE:
            assert remedy.action is None
        else:
            assert (remedy.action, remedy.params["value_paise"]) == ("free_item_voucher", want)
        assert line.approval == "instant"  # the voucher action's own auto-approve rule
        assert format_inr(line.max_paise) in line.text
    elif line.kind in ("refund", "refund_missing"):
        want = min(percent_of(total, line.percent), refundable)
        if line.kind == "refund_missing":
            want = min(want, missing)
        if want <= 0:
            assert remedy.action is None
        else:
            assert (remedy.action, remedy.params["amount_paise"]) == ("refund", want)
        assert line.approval == "team"  # refunds are never auto-approved
        assert f"{line.percent}%" in line.text
    else:
        assert (remedy.outcome, remedy.action) == ("apology", None)


def test_every_category_summary_equals_what_the_rule_allows(app_engine, sample):
    _, tid, order_id = sample
    with pytest.raises(_Rollback), tenant_session(tid, app_engine) as s:
        now = datetime.now(UTC)
        summary = build_rules_summary(s, "en", now, staff=False)
        pack = tenant_pack(s)
        by_cat = {c.category: c for c in summary.categories}
        assert set(pack.remedies) <= set(by_cat)
        order, facts = order_facts(s, order_id)
        # The summary is organisation level; the sample order must not be narrowed further.
        assert facts.settings == effective_settings(s)
        items = list(s.scalars(select(LineItem).where(LineItem.transaction_id == order_id)))
        for li in items:  # nothing arrived, for the missing-items rule
            li.quantity_fulfilled = 0
        s.flush()
        missing = sum(li.unit_price_paise * li.quantity for li in items)
        checked = 0
        for category, rule in pack.remedies.items():
            cat = by_cat[category]
            if any(o == "late_tiers" for o in rule_options(rule)):
                assert cat.tiers, "late tiers in force must be listed"
                for tier in cat.tiers:
                    remedy = _judge(s, order_id, category, now.date(), tier.min_minutes_late)
                    refundable = order_facts(s, order_id)[1].refundable_paise
                    _check_line(tier, remedy, order.total_paise, refundable)
                    checked += 1
            several = len(cat.options) > 1
            for line in cat.options:
                remedy = decide_remedy(
                    s,
                    Case(category=category, transaction_id=order_id),
                    choice=line.code if several else None,
                )
                _check_line(line, remedy, order.total_paise, facts.refundable_paise, missing)
                checked += 1
        assert checked, "the pack must map at least one category to a rule"
        raise _Rollback


def test_a_changed_setting_appears_with_its_amount_and_date(app_engine, sample):
    _, tid, _ = sample
    with pytest.raises(_Rollback), tenant_session(tid, app_engine) as s:
        now = datetime.now(UTC)
        before = build_rules_summary(s, "en", now, staff=True)
        if not any(r["key"] == "voucher_auto_approve_max_paise" for r in before.settings):
            pytest.skip("this pack offers no voucher")
        row = s.scalar(
            select(TenantSetting).where(
                TenantSetting.key == "voucher_auto_approve_max_paise",
                TenantSetting.brand_id.is_(None),
                TenantSetting.location_id.is_(None),
            )
        )
        if row is None:
            s.add(TenantSetting(tenant_id=tid, key="voucher_auto_approve_max_paise", value=12000))
        else:
            row.value = 12000
        s.flush()
        after = build_rules_summary(s, "en", now, staff=True)
        lines = [
            ln for c in after.categories for ln in [*c.options, *c.tiers] if ln.kind == "voucher"
        ]
        assert lines and all(ln.max_paise <= 12000 for ln in lines)
        assert all(format_inr(ln.max_paise) in ln.text for ln in lines)
        src = {r["key"]: r["source"] for r in after.settings}
        assert src["voucher_auto_approve_max_paise"] == "tenant_override"
        assert after.settings_updated is not None
        assert after.in_force_since >= before.in_force_since
        raise _Rollback


def test_api_customer_and_staff_views(api, sample):
    cfg, _, _ = sample
    customer = next(u for u in cfg.users if u.role == "customer")
    hq = next(u for u in cfg.users if u.role == "hq_owner")
    c = api.get("/policies/rules-summary", headers=login(api, cfg.slug, customer.email))
    h = api.get("/policies/rules-summary", headers=login(api, cfg.slug, hq.email))
    assert c.status_code == 200 and h.status_code == 200, c.text
    cj, hj = c.json(), h.json()
    assert cj["settings"] == [] and hj["settings"]
    assert {r["source"] for r in hj["settings"]} <= {"pack_default", "tenant_override"}
    assert [x["category"] for x in cj["categories"]] == [x["category"] for x in hj["categories"]]
    assert cj["in_force_since"] and cj["in_force_text"]
    assert any(x["options"] or x["tiers"] for x in cj["categories"])
    hq_headers = login(api, cfg.slug, hq.email)
    for lang in (*LANGUAGES, "xx"):  # an unsupported language falls back to English
        r = api.get(f"/policies/rules-summary?language={lang}", headers=hq_headers)
        assert r.status_code == 200
        assert r.json()["language"] == (lang if lang in LANGUAGES else "en")
    assert api.get("/policies/rules-summary").status_code == 401


def test_each_tenant_shows_only_its_own_rules(api, seeded_history, tenant):
    cfg = seeded_history[tenant.name]
    pack_of = {}
    for other in seeded_history.values():
        hq = next(u.email for u in other.users if u.role == "hq_owner")
        body = api.get("/policies/rules-summary", headers=login(api, other.slug, hq)).json()
        pack_of[other.slug] = (body["pack_name"], {c["category"] for c in body["categories"]})
    own_name, own_cats = pack_of[cfg.slug]
    assert own_cats == set(load_pack(cfg.vertical_pack).issue_categories) - {"status_question"}
    for slug, (name, _) in pack_of.items():
        if slug != cfg.slug:
            assert name != own_name or len(pack_of) == 1


def test_a_pack_stored_before_a_setting_existed_still_loads(api, sample, monkeypatch):
    """A database whose stored pack predates a setting must not break the page for staff."""
    cfg, _, _ = sample
    hq = next(u for u in cfg.users if u.role == "hq_owner")

    def older_pack(session):
        return {k: v for k, v in effective_settings(session).items() if k != "voucher_percent"}

    monkeypatch.setattr("app.engine.rules_summary.effective_settings", older_pack)
    r = api.get("/policies/rules-summary", headers=login(api, cfg.slug, hq.email))
    assert r.status_code == 200, r.text
    assert "voucher_percent" not in {row["key"] for row in r.json()["settings"]}
