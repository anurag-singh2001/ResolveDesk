"""cases.owner_user_id (S7.2) cannot cross tenants: the composite FK refuses another tenant's
user, and RLS hides one tenant's cases (and so their owners) from another."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.db import tenant_session
from app.core.models import Case, Customer, User
from app.core.tenancy import tenant_id_for


def test_owner_must_be_a_user_of_the_same_tenant(app_engine, maint_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    others = [c for c in seeded.values() if c.slug != cfg.slug]
    assert others, "isolation tests need at least two tenants"
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tenant_id_for(others[0].slug), app_engine) as s:
        foreign_user = s.scalars(select(User.id)).first()
    with tenant_session(tid, app_engine) as s:
        customer = s.scalars(select(Customer.id)).first()
    if customer is None:
        pytest.skip("no customer in this tenant")
    cid = uuid.uuid4()
    try:
        with pytest.raises(IntegrityError), tenant_session(tid, app_engine) as s:
            s.add(
                Case(
                    id=cid,
                    tenant_id=tid,
                    customer_id=customer,
                    status="escalated",
                    channel="app",
                    opened_at=datetime.now(UTC),
                    owner_user_id=foreign_user,
                )
            )
    finally:
        with tenant_session(tid, maint_engine) as s:
            s.execute(delete(Case).where(Case.id == cid))


def test_other_tenants_cases_and_owners_are_invisible(app_engine, maint_engine, seeded, tenant):
    cfg = seeded[tenant.name]
    others = [c for c in seeded.values() if c.slug != cfg.slug]
    tid = tenant_id_for(cfg.slug)
    with tenant_session(tid, app_engine) as s:
        owner = s.scalars(select(User.id)).first()
        customer = s.scalars(select(Customer.id)).first()
    if customer is None:
        pytest.skip("no customer in this tenant")
    cid = uuid.uuid4()
    with tenant_session(tid, app_engine) as s:
        s.add(
            Case(
                id=cid,
                tenant_id=tid,
                customer_id=customer,
                status="escalated",
                channel="app",
                opened_at=datetime.now(UTC),
                owner_user_id=owner,
            )
        )
    try:
        for other in others:
            with tenant_session(tenant_id_for(other.slug), app_engine) as s:
                assert s.scalars(select(Case.id).where(Case.owner_user_id == owner)).all() == []
                assert s.get(Case, cid) is None
    finally:
        with tenant_session(tid, maint_engine) as s:
            s.execute(delete(Case).where(Case.id == cid))
