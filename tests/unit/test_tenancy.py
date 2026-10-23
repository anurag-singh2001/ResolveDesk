import uuid

import pytest

from app.core.tenancy import TenantContext

LOC_A, LOC_B = uuid.uuid4(), uuid.uuid4()


def ctx(role, locations=()):
    return TenantContext(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        role=role,
        brand_ids=frozenset(),
        location_ids=frozenset(locations),
    )


def test_hq_owner_sees_every_location():
    assert ctx("hq_owner").can_see_location(LOC_B)


@pytest.mark.parametrize("role", ["location_manager", "franchisee_owner"])
def test_scoped_roles_see_only_their_locations(role):
    c = ctx(role, [LOC_A])
    assert c.can_see_location(LOC_A)
    assert not c.can_see_location(LOC_B)


@pytest.mark.parametrize("role", ["location_manager", "franchisee_owner"])
def test_scoped_role_without_scope_sees_nothing(role):
    assert not ctx(role).can_see_location(LOC_A)


def test_customer_sees_no_locations_and_is_not_staff():
    c = ctx("customer", [LOC_A])
    assert not c.can_see_location(LOC_A)
    assert not c.is_staff
