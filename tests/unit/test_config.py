import pytest
from pydantic import ValidationError

from app.config import DEV_JWT_SECRET, Settings

REAL_SECRET = "s" * 48


def test_demo_auth_is_off_unless_enabled(monkeypatch):
    monkeypatch.delenv("DEMO_AUTH", raising=False)
    assert Settings(_env_file=None).demo_auth is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"demo_auth": True, "jwt_secret": REAL_SECRET},
        {"demo_auth": False, "jwt_secret": DEV_JWT_SECRET},
    ],
)
def test_prod_refuses_dev_shortcuts(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod", **overrides)


def test_prod_with_real_secret_and_no_demo_auth_is_fine():
    s = Settings(_env_file=None, app_env="prod", demo_auth=False, jwt_secret=REAL_SECRET)
    assert s.app_env == "prod"


def test_short_jwt_secret_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="too-short")
