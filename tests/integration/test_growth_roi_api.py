"""S11.3b ROI endpoints. WRITTEN BUT NOT RUN on the machine that built it (no database tests
there). Runs for every tenant folder and never names one.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.api.deps import get_clock
from app.core.db import tenant_session
from app.core.models import AuditEvent, Campaign, CampaignMember, ManualSpend
from tests.helpers import login
from tests.integration.test_growth import ctx_of, gt, propose_for  # noqa: F401
from tests.integration.test_growth_calendar_api import cal  # noqa: F401


def _campaign_ids(app_engine, tid):
    with tenant_session(tid, app_engine) as s:
        return [c.id for c in s.scalars(select(Campaign).order_by(Campaign.id))]


def test_roi_is_read_only_and_every_send_state_is_shown(cal, app_engine):  # noqa: F811
    api, cfg, tid, headers, staff, hq = cal
    cid = _campaign_ids(app_engine, tid)[0]
    with tenant_session(tid, app_engine) as s:
        audits = s.scalar(select(func.count()).select_from(AuditEvent))
        members = s.scalar(select(func.count()).select_from(CampaignMember))
    resp = api.get(f"/growth/campaigns/{cid}/roi", headers=headers[hq])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Not sent yet: the window is open, so no ROI headline is shown.
    assert body["gate"] == "window_open" and body["headline"] is None
    assert set(body["send_states"]) == {
        "pending", "submitted", "processing", "succeeded", "failed", "unknown", "skipped"
    }  # fmt: skip
    assert body["send_states"]["pending"] == body["arms"]["treatment"]["customers"]
    assert body["holdout_advice"]["detectable_lift_bp"] is not None
    with tenant_session(tid, app_engine) as s:
        assert s.scalar(select(func.count()).select_from(AuditEvent)) == audits
        assert s.scalar(select(func.count()).select_from(CampaignMember)) == members


def test_holdout_members_are_never_contacted(cal, app_engine):  # noqa: F811
    api, cfg, tid, headers, staff, hq = cal
    api.get(f"/growth/campaigns/{_campaign_ids(app_engine, tid)[0]}/roi", headers=headers[hq])
    with tenant_session(tid, app_engine) as s:
        sent = s.scalar(
            select(func.count())
            .select_from(CampaignMember)
            .where(CampaignMember.arm == "holdout", CampaignMember.send_status != "pending")
        )
    assert sent == 0


def test_unknown_campaign_is_404(cal):  # noqa: F811
    api, cfg, tid, headers, staff, hq = cal
    assert api.get(f"/growth/campaigns/{uuid.uuid4()}/roi", headers=headers[hq]).status_code == 404


def test_manual_spend_is_hq_only_audited_and_integer(cal, app_engine):  # noqa: F811
    api, cfg, tid, headers, staff, hq = cal
    body = {
        "channel": "aggregator_ads",
        "amount_paise": 123456,
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
    }
    for u in staff:
        if u.role != "hq_owner":
            assert api.post("/growth/spend", json=body, headers=headers[u.email]).status_code == 403
    assert api.post("/growth/spend", json={**body, "amount_paise": 10.5}, headers=headers[hq]
                    ).status_code == 422  # fmt: skip
    resp = api.post("/growth/spend", json=body, headers=headers[hq])
    assert resp.status_code == 201, resp.text
    assert resp.json()["verification"] == "entered by hand, not verified"
    with tenant_session(tid, app_engine) as s:
        row = s.scalar(select(ManualSpend))
        assert row.amount_paise == 123456 and row.period_start == date(2026, 10, 1)
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event == "growth.spend_entered")
            )
            >= 1
        )
    mix = api.get("/growth/channel-mix", headers=headers[hq]).json()
    assert mix["manual_spend"][0]["amount_paise"] == 123456
    for u in staff:
        if u.role != "hq_owner":
            other = api.get("/growth/channel-mix", headers=headers[u.email])
            assert other.status_code == 200 and other.json()["manual_spend"] == []


def test_app_role_cannot_update_or_delete_manual_spend(cal, app_engine):  # noqa: F811
    api, cfg, tid, headers, staff, hq = cal
    body = {
        "channel": "aggregator_ads",
        "amount_paise": 5000,
        "period_start": datetime.now(UTC).date().isoformat(),
        "period_end": datetime.now(UTC).date().isoformat(),
    }
    assert api.post("/growth/spend", json=body, headers=headers[hq]).status_code == 201
    for sql in (
        "UPDATE growth_manual_spend SET amount_paise = 1",
        "DELETE FROM growth_manual_spend",
    ):
        with (
            pytest.raises(DBAPIError, match="permission denied"),
            tenant_session(tid, app_engine) as s,
        ):
            s.execute(text(sql))


def test_spend_bounds_give_422_not_500(cal):  # noqa: F811
    api, cfg, tid, headers, staff, hq = cal
    ok = {"channel": "aggregator_ads", "period_start": "2026-10-01", "period_end": "2026-10-31"}
    assert api.post("/growth/spend", json={**ok, "amount_paise": 10**12 + 1}, headers=headers[hq]
                    ).status_code == 422  # fmt: skip
    assert api.post("/growth/spend", json={**ok, "amount_paise": 10**18}, headers=headers[hq]
                    ).status_code == 422  # fmt: skip
    far = {**ok, "amount_paise": 100, "period_start": "1900-01-01"}
    assert api.post("/growth/spend", json=far, headers=headers[hq]).status_code == 422
    far = {**ok, "amount_paise": 100, "period_end": "2999-01-01"}
    assert api.post("/growth/spend", json=far, headers=headers[hq]).status_code == 422


def test_another_tenants_campaign_is_404(cal, seeded_history, app_engine):  # noqa: F811
    api, cfg, tid, headers, staff, hq = cal
    others = [c for c in seeded_history.values() if c.slug != cfg.slug]
    if not others:
        pytest.skip("only one tenant is seeded")
    other = others[0]
    if not other.feature_flags.get("growth"):
        pytest.skip("growth is off for the other tenant")
    other_hq = next(u.email for u in other.users if u.role == "hq_owner")
    # Tokens are stamped with the real clock, so log in with the test clock lifted.
    clock = api.app.dependency_overrides.pop(get_clock)
    try:
        other_headers = login(api, other.slug, other_hq)
    finally:
        api.app.dependency_overrides[get_clock] = clock
    cid = _campaign_ids(app_engine, tid)[0]
    assert api.get(f"/growth/campaigns/{cid}/roi", headers=other_headers).status_code == 404


def test_inconclusive_verdict_hides_result_and_failed_unknown_stay_in_treatment(
    cal,  # noqa: F811
    app_engine,
    gt,  # noqa: F811
):
    api, cfg, tid, headers, staff, hq = cal
    _, _, as_of = gt
    cid = _campaign_ids(app_engine, tid)[0]
    with tenant_session(tid, app_engine) as s:
        c = s.get(Campaign, cid)
        c.status, c.sent_at = "sent", as_of - timedelta(days=60)
        treat = list(
            s.scalars(
                select(CampaignMember)
                .where(CampaignMember.campaign_id == cid, CampaignMember.arm == "treatment")
                .order_by(CampaignMember.customer_id)
            )
        )
        failed = unknown = 0
        for i, m in enumerate(treat):
            if i % 3 == 0:
                m.send_status, failed = "failed", failed + 1
            elif i % 3 == 1:
                m.send_status, unknown = "unknown", unknown + 1
        n_treat = len(treat)
    body = api.get(f"/growth/campaigns/{cid}/roi", headers=headers[hq]).json()
    assert body["arms"]["treatment"]["customers"] == n_treat  # failed and unknown still counted
    assert body["send_states"]["failed"] == failed and body["send_states"]["unknown"] == unknown
    if body["gate"] != "inconclusive":
        pytest.skip("this audience is big enough for a verdict")
    assert body["headline"] is None and body["incremental_revenue_paise"] is None
    assert body["message"] == "Not enough people to tell"
