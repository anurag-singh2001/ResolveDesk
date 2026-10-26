"""Growth tables: beyond tenant isolation (test_rls.py covers every model), the app role may
not rewrite what an approval was bound to, edit a decision, or delete growth rows."""

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.core.models import Campaign, CampaignApproval, CampaignMember, PlaybookEntry, Signal

pytestmark = pytest.mark.isolation


def _denied(engine, tenant_id, stmt) -> None:
    with (
        pytest.raises(DBAPIError, match="permission denied"),
        tenant_session(tenant_id, engine) as s,
    ):
        s.execute(stmt)


@pytest.mark.parametrize(
    "stmt",
    [
        update(Campaign).values(params={"offer_paise": 1}),
        update(Campaign).values(payload_hash="1" * 64),
        update(CampaignApproval).values(decision="rejected"),
        update(CampaignMember).values(arm="holdout"),
        update(PlaybookEntry).values(verdict="worked"),
    ],
    ids=["params", "hash", "decision", "arm", "verdict"],
)
def test_app_role_cannot_rewrite_bound_columns(app_engine, tenants, stmt):
    a, _ = tenants
    _denied(app_engine, a.tenant_id, stmt)


@pytest.mark.parametrize(
    "model", [Signal, Campaign, CampaignMember, CampaignApproval, PlaybookEntry]
)
def test_app_role_cannot_delete_growth_rows(app_engine, tenants, model):
    a, _ = tenants
    _denied(app_engine, a.tenant_id, delete(model))


def test_campaign_status_is_updatable_but_only_in_own_tenant(app_engine, tenants):
    a, b = tenants
    with tenant_session(a.tenant_id, app_engine) as s:
        assert s.execute(update(Campaign).values(status="pending_approval")).rowcount == 1
    with tenant_session(b.tenant_id, app_engine) as s:
        assert s.scalar(select(Campaign.tenant_id)) == b.tenant_id
