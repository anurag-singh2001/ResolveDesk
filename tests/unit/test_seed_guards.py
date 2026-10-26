import pytest

import simulator.load
from app.config import Settings


def test_history_reseed_refused_in_prod(monkeypatch):
    prod = Settings(_env_file=None, app_env="prod", demo_auth=False, jwt_secret="s" * 48)
    monkeypatch.setattr(simulator.load, "get_settings", lambda: prod)
    with pytest.raises(RuntimeError, match="APP_ENV=prod"):
        simulator.load.load_history(engine=None, cfg=None, pack=None)
