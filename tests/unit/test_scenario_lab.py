"""Scenario lab (S10.1): validation, safe file names, the scratch-DB guard, one run at a time,
and the comparison with the last report. No database and no network."""

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import SecretStr

from app.core import scenario_lab as lab
from evals.scenarios import ScenarioError, scenario_file


def _first_text(folder: Path) -> str:
    return sorted((folder / "scenarios").glob("*.yaml"))[0].read_text(encoding="utf-8")


def _settings(
    scratch=None, db="postgresql://u:p@h/app_db", platform=None, migration=None, maint=None
):
    return SimpleNamespace(
        scenario_lab_database_url=SecretStr(scratch) if scratch else None,
        database_url=db,
        platform_database_url=platform,
        migration_database_url=migration,
        maint_database_url=maint,
        scenario_lab_timeout_seconds=60,
    )


SCRATCH = "postgresql://u:p@h/scratch_db"


@pytest.fixture
def lab_tenants(tenant, tmp_path, monkeypatch):
    """A temp copy of tenants/ so saves never touch the repo."""
    root = tmp_path / "tenants"
    shutil.copytree(tenant, root / tenant.name)
    monkeypatch.setattr(lab, "TENANTS_DIR", root)
    monkeypatch.setattr(lab, "LAB_REPORTS", tmp_path / "reports" / "lab")
    lab.reset_for_tests()
    yield tenant.name, root / tenant.name
    lab.reset_for_tests()


def test_an_existing_scenario_validates(lab_tenants):
    slug, folder = lab_tenants
    assert lab.validate_text(slug, _first_text(folder)).tenant == slug


@pytest.mark.parametrize(
    "mutate, expect",
    [
        (lambda t: t.replace("message:", "bogus_field: 1\nmessage:", 1), "bogus_field"),
        (lambda t: "just a string", "mapping"),
        (lambda t: "a: [unclosed", "not valid YAML"),
        (lambda t: "x" * 20_000, "too large"),
        (lambda t: "!!python/object/apply:os.system ['echo hi']", "not valid YAML"),
    ],
)
def test_bad_input_gives_a_readable_error(lab_tenants, mutate, expect):
    slug, folder = lab_tenants
    with pytest.raises(ScenarioError) as e:
        lab.validate_text(slug, mutate(_first_text(folder)))
    assert expect in " ".join(e.value.problems)


def test_a_category_outside_the_pack_is_refused(lab_tenants):
    slug, folder = lab_tenants
    data = yaml.safe_load(_first_text(folder))
    data["expect"]["category"] = "not_a_category"
    with pytest.raises(ScenarioError, match="unknown category"):
        lab.validate_text(slug, yaml.safe_dump(data))


def test_another_tenants_scenario_is_refused(lab_tenants):
    slug, folder = lab_tenants
    data = yaml.safe_load(_first_text(folder))
    data["tenant"] = "someone-else"
    with pytest.raises(ScenarioError, match="tenant"):
        lab.validate_text(slug, yaml.safe_dump(data))


@pytest.mark.parametrize(
    "name", ["../x", "..", "a/b", "a\\b", "x.yaml", "X", "", "a" * 80, "%2e%2e", "a b", "a\x00b"]
)
def test_scenario_names_cannot_leave_the_folder(lab_tenants, name):
    _, folder = lab_tenants
    with pytest.raises(ScenarioError):
        scenario_file(folder, name)


def test_save_writes_only_the_named_file(lab_tenants):
    slug, folder = lab_tenants
    data = yaml.safe_load(_first_text(folder))
    data["id"] = "lab-new-001"
    data["held_out"] = False
    lab.save_text(slug, "lab-new-001", yaml.safe_dump(data))
    assert (folder / "scenarios" / "lab-new-001.yaml").is_file()
    assert "lab-new-001" in lab.read_text(slug, "lab-new-001")
    with pytest.raises(ScenarioError, match="the name is"):  # content cannot pick the file
        lab.save_text(slug, "other-name", yaml.safe_dump(data))
    assert not (folder / "scenarios" / "other-name.yaml").exists()
    assert not list((folder / "scenarios").glob(".*.tmp"))


def test_an_unknown_tenant_is_refused(lab_tenants):
    with pytest.raises(ScenarioError, match="unknown tenant"):
        lab.validate_text("../etc", "id: x")


def test_no_scratch_database_means_no_run(lab_tenants):
    slug, _ = lab_tenants
    with pytest.raises(lab.LabRefused):
        lab.start_run(_settings(None), slug, ["x"], "agents")
    assert lab.current().status == "idle"
    assert not lab.scratch_configured(_settings(None))


def test_selection_is_checked_against_the_files(lab_tenants):
    slug, _ = lab_tenants
    s = _settings(SCRATCH)
    for ids in ([], ["no-such-scenario"], ["a", "a"]):
        with pytest.raises(ScenarioError):
            lab.start_run(s, slug, ids, "agents")
    with pytest.raises(ScenarioError):
        lab.start_run(s, slug, [lab.list_scenarios(slug)[0].id], "bogus")
    assert lab.current().status == "idle"


def test_comparison_with_the_last_report(tmp_path):
    (tmp_path / "eval-20260101-000000.md").write_text(
        "# r\n\n## Failing scenarios\n\n- bad-1 [agents]: expected x; got y (why)\n"
    )
    last = lab.last_report(tmp_path)
    assert last["failing"] == {"bad-1"} and last["passing"] is None
    new = {
        "scenarios": [
            {"id": "bad-1", "pipeline": "agents", "passed": True},
            {"id": "ok-1", "pipeline": "agents", "passed": False},
            {"id": "ok-2", "pipeline": "agents", "passed": True},
        ]
    }
    got = {e["id"]: e["change"] for e in lab.compare(new, last)["scenarios"]}
    assert got == {"bad-1": "improved", "ok-1": "regressed", "ok-2": "same"}
    assert lab.compare(new, None)["last_report"] is None
    assert lab.last_report(tmp_path / "missing") is None


@pytest.mark.parametrize(
    "scratch",
    [
        "postgresql://u:p@h/app_db",  # same host, same name
        "postgresql://other:x@H:5432/APP_DB",  # user, case and explicit default port differ
        "postgresql://u:p@h/app%5Fdb",  # percent-encoded name
        "postgresql://u:p@h/ap%70_db",
        "postgresql://u:p@h-pooler/app_db",  # pooled endpoint of the same server
        "postgresql://u:p@h/scratch_db?dbname=app_db",  # query overrides
        "postgresql://u:p@h/scratch_db?options=-c%20search_path%3Dx",
        "postgresql://u:p@h/scratch_db?host=elsewhere",
        "postgresql://u:p@h",  # no database
        "mysql://u:p@h/scratch_db",
        "not a url",
    ],
)
def test_the_apps_own_database_is_never_a_scratch_database(scratch):
    with pytest.raises(lab.LabRefused):
        lab.scratch_url(_settings(scratch))


def test_every_app_target_is_protected_and_other_hosts_are_not():
    kw = {
        "migration": "postgresql://o:p@h/mig_db",
        "maint": "postgresql://o:p@h/maint_db",
        "platform": "postgresql://a:b@h/plat_db",
    }
    for protected in ("mig_db", "maint_db", "plat_db", "app_db"):
        with pytest.raises(lab.LabRefused):
            lab.scratch_url(_settings(f"postgresql://u:p@h/{protected}", **kw))
    # Neon branches share one database name on different hosts: allowed.
    assert lab.scratch_url(_settings("postgresql://u:p@branch.example/app_db", **kw))
    assert lab.scratch_url(_settings("postgresql://u:p@h:5433/app_db", **kw))
    assert lab.scratch_url(_settings(SCRATCH, **kw)).endswith("scratch_db")


def test_no_protected_target_known_means_refuse():
    with pytest.raises(lab.LabRefused):
        lab.scratch_url(_settings(SCRATCH, db=None))


def test_the_child_refuses_by_itself(monkeypatch, tmp_path):
    from evals import run

    monkeypatch.setenv("ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("EVAL_PROTECTED_DB_TARGETS", '[["h", 5432, "app_db"]]')
    for url, refused in (
        ("postgresql://u:p@h/app%5Fdb", True),
        ("postgresql://u:p@h/x?dbname=app_db", True),
        ("postgresql://u:p@h/scratch_db", False),
        ("postgresql://u:p@other/app_db", False),
    ):
        monkeypatch.setenv("DATABASE_URL", url)
        assert (run.refuses_scratch_check() is not None) is refused, url
    monkeypatch.delenv("DATABASE_URL")
    assert run.refuses_scratch_check()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/scratch_db")
    monkeypatch.delenv("EVAL_PROTECTED_DB_TARGETS")
    assert run.refuses_scratch_check()  # nothing to compare with: fail closed
    assert run.main(["--no-seed", "--require-scratch"]) == 2  # refuses before touching a DB


def test_the_child_command_always_requires_scratch():
    cmd = lab.child_command("t", ["a", "b"], "agents", Path("r"))
    assert "--no-seed" in cmd and "--require-scratch" in cmd and "--i-know" not in cmd
    assert cmd[cmd.index("--only") + 1] == "a,b"


def test_secrets_and_dotenv_do_not_reach_the_child(tmp_path, monkeypatch):
    from app.config import Settings

    (tmp_path / ".env").write_text(
        "MIGRATION_DATABASE_URL=postgresql://o:dotenv-secret@h/mig\n"
        "PLATFORM_JWT_SECRET=dotenv-platform-secret\n"
        "TEST_DATABASE_URL=postgresql://t:dotenv-secret@h/t\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JWT_SECRET", "parent-env-secret-parent-env-secret-0123")
    monkeypatch.setenv("TEST_MIGRATION_DATABASE_URL", "postgresql://o:parent-secret@h/t")
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD_HASH", "parent-hash")
    monkeypatch.setenv("MAINT_DATABASE_URL", "postgresql://o:parent-secret@h/maint")
    parent = Settings(_env_file=None, gemini_api_key=SecretStr("llm-key"), llm_provider="groq")
    env = lab.child_env(parent, SCRATCH, tmp_path / "no.env")
    blob = " ".join(env.values())
    assert not any(
        x in blob for x in ("dotenv-secret", "parent-secret", "parent-env-secret", "parent-hash")
    )
    assert env["DATABASE_URL"] == SCRATCH and env["GEMINI_API_KEY"] == "llm-key"
    assert env["LLM_PROVIDER"] == "groq" and not (tmp_path / "no.env").exists()
    code = (
        "import sys, json; sys.path.insert(0, sys.argv[1]);"
        "from app.config import get_settings; s = get_settings();"
        "print(json.dumps([s.migration_database_url, s.maint_database_url, s.test_database_url,"
        " s.jwt_secret, str(s.platform_jwt_secret), s.database_url, s.llm_provider,"
        " s.gemini_api_key.get_secret_value()]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(lab.ROOT)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120, check=True,
    )  # fmt: skip
    mig, maint, test_db, jwt, plat, db, prov, key = json.loads(out.stdout)
    assert (mig, maint, test_db, plat) == (None, None, None, "None")
    assert "parent-env-secret" not in jwt and db == SCRATCH and prov == "groq" and key == "llm-key"


class FakeProc:
    pid = 0

    def __init__(self, wait):
        self._wait = wait

    def wait(self, timeout=None):
        return self._wait(timeout)

    def kill(self):
        pass


def test_one_run_at_a_time_and_status_is_clear(lab_tenants, monkeypatch):
    slug, _ = lab_tenants
    sid = lab.list_scenarios(slug)[0].id
    release, started = threading.Event(), threading.Event()

    def fake_popen(cmd, **kw):
        started.set()
        out = Path(cmd[cmd.index("--report-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        row = {"id": sid, "tenant": slug, "pipeline": "agents", "passed": True}
        (out / "eval-1.json").write_text(json.dumps({"meta": {}, "rows": [], "scenarios": [row]}))
        return FakeProc(lambda t: release.wait(5) and 0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    s = _settings(SCRATCH)
    assert lab.start_run(s, slug, [sid], "agents").status == "running" and started.wait(5)
    with pytest.raises(lab.LabRefused, match="already"):
        lab.start_run(s, slug, [sid], "agents")
    assert lab.current().status == "running"
    release.set()
    for t in threading.enumerate():
        if t.name == "lab-run":
            t.join(5)
    done = lab.current()
    assert done.status == "succeeded" and done.report
    assert lab.run_result(done)["scenarios"][0]["now"] == "passed"


def test_a_refused_or_timed_out_child_ends_as_failed_and_is_killed(lab_tenants, monkeypatch):
    slug, _ = lab_tenants
    sid = lab.list_scenarios(slug)[0].id
    s = _settings(SCRATCH)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc(lambda t: 2))
    lab.start_run(s, slug, [sid], "agents", wait=True)
    assert lab.current().status == "failed" and "refused" in lab.current().message

    def slow(t):
        raise subprocess.TimeoutExpired("x", t)

    proc, killed = FakeProc(slow), []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(lab, "kill_tree", killed.append)
    lab.start_run(s, slug, [sid], "agents", wait=True)  # not stuck in 'running'
    assert lab.current().status == "failed" and "timed out" in lab.current().message
    assert killed == [proc]  # the whole tree is stopped, not just waited on


def test_child_output_goes_to_a_file_not_memory(lab_tenants, monkeypatch):
    slug, _ = lab_tenants
    sid = lab.list_scenarios(slug)[0].id
    seen = {}

    def popen(cmd, **kw):
        seen.update(kw)
        return FakeProc(lambda t: 2)

    monkeypatch.setattr(subprocess, "Popen", popen)
    lab.start_run(_settings(SCRATCH), slug, [sid], "agents", wait=True)
    assert seen["stdout"].name.endswith("child.log") and seen["stderr"] == subprocess.STDOUT
    assert seen["stdin"] == subprocess.DEVNULL


def test_the_same_id_in_another_file_is_refused(lab_tenants):
    slug, folder = lab_tenants
    data = yaml.safe_load(_first_text(folder))
    (folder / "scenarios" / "copy-of-it.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(ScenarioError, match="already uses"):
        lab.save_text(slug, data["id"], yaml.safe_dump(data))


def test_audit_detail_is_a_safe_short_token():
    from app.api.routes_platform import _tag

    assert _tag("a-1") == "a-1"
    assert _tag("../x y\n;drop") == "..?x?y??drop"
    assert len(_tag("x" * 500, 200)) == 200


def test_held_out_scenarios_are_read_only(lab_tenants):
    slug, folder = lab_tenants
    data = yaml.safe_load(_first_text(folder))
    data["id"] = "lab-held-001"
    data["held_out"] = True
    # Text that claims held_out cannot be saved, so no new file appears.
    with pytest.raises(ScenarioError, match="read-only"):
        lab.save_text(slug, "lab-held-001", yaml.safe_dump(data))
    assert not (folder / "scenarios" / "lab-held-001.yaml").exists()
    # An existing held-out file cannot be edited, even with held_out switched off in the text.
    (folder / "scenarios" / "lab-held-001.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    before = (folder / "scenarios" / "lab-held-001.yaml").read_text(encoding="utf-8")
    data["held_out"] = False
    data["message"] = "changed"
    with pytest.raises(ScenarioError, match="read-only"):
        lab.save_text(slug, "lab-held-001", yaml.safe_dump(data))
    assert (folder / "scenarios" / "lab-held-001.yaml").read_text(encoding="utf-8") == before
    # Reading it is still allowed.
    assert "lab-held-001" in lab.read_text(slug, "lab-held-001")
