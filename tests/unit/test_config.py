import pytest
from pydantic import ValidationError

from app.config import DEV_JWT_SECRET, Settings

REAL_SECRET = "s" * 48


def test_demo_auth_is_off_unless_enabled(monkeypatch):
    monkeypatch.delenv("DEMO_AUTH", raising=False)
    assert Settings(_env_file=None, app_env="dev").demo_auth is False


def test_unset_app_env_is_prod_and_refuses_dev_secret(monkeypatch):
    for var in ("APP_ENV", "DEMO_AUTH", "JWT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


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


def test_prod_refuses_llm_cache():
    """The dev cache writes full prompts and replies (customer text) to disk."""
    with pytest.raises(ValidationError, match="LLM_CACHE"):
        Settings(
            _env_file=None, app_env="prod", demo_auth=False, jwt_secret=REAL_SECRET, llm_cache=True
        )
    assert Settings(_env_file=None, app_env="dev", llm_cache=True).llm_cache is True


FAKE_KEY = "fake-key-ab12cd34ef56"


def test_api_keys_are_secret_in_str_and_repr():
    s = Settings(_env_file=None, app_env="test", gemini_api_key=FAKE_KEY, groq_api_key=FAKE_KEY)
    assert FAKE_KEY not in str(s) and FAKE_KEY not in repr(s)
    assert FAKE_KEY not in repr(s.gemini_api_key) and FAKE_KEY not in str(s.groq_api_key)
    assert s.gemini_api_key.get_secret_value() == FAKE_KEY


def test_validation_error_never_echoes_values():
    with pytest.raises(ValidationError) as err:
        Settings(_env_file=None, app_env="test", groq_api_key=FAKE_KEY, llm_cache=FAKE_KEY)
    assert FAKE_KEY not in str(err.value) and FAKE_KEY not in repr(err.value)


def test_short_jwt_secret_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="dev", jwt_secret="too-short")
