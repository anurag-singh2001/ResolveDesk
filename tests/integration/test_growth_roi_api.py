"""S11.3b ROI endpoints. WRITTEN BUT NOT RUN on the machine that built it (no database tests
there). Runs for every tenant folder and never names one.
"""

import uuid
from datetime import date

from sqlalchemy import func, select

from app.core.db import tenant_session
from app.core.models import AuditEvent, Campaign, CampaignMember, ManualSpend
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
