"""`make eval` reseeds, so it refuses to run on the dotenv's default (demo) database."""

from evals import run


def _env(tmp_path, monkeypatch, default: str, effective: str | None):
    f = tmp_path / "dot.env"
    f.write_text(f"DATABASE_URL={default}\n")
    monkeypatch.setenv("ENV_FILE", str(f))
    if effective is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", effective)


def test_same_database_is_refused(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, "postgresql://u:p@h/demo_db", "postgresql://x:y@other/demo_db")
    assert run.reseeds_default_db()


def test_dotenv_only_counts_as_default(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, "postgresql://u:p@h/demo_db", None)
    assert run.reseeds_default_db()


def test_scratch_database_is_allowed(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, "postgresql://u:p@h/demo_db", "postgresql://u:p@h/scratch_db")
    assert not run.reseeds_default_db()


def test_main_refuses_without_flag(tmp_path, monkeypatch, capsys):
    _env(tmp_path, monkeypatch, "postgresql://u:p@h/demo_db", "postgresql://u:p@h/demo_db")
    assert run.main([]) == 2
    assert "refusing to reseed" in capsys.readouterr().err
