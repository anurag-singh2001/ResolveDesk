import pytest

from app.core.db import tenant_session


@pytest.mark.parametrize("bad", ["not-a-uuid", None, 123])
def test_tenant_session_requires_uuid(bad):
    with pytest.raises(TypeError), tenant_session(bad, engine=object()):
        pass
