"""Scenario lab (S10.1): validation, safe file names, the scratch-DB guard, one run at a time,
and the comparison with the last report. No database and no network."""

import json
import shutil
import subprocess
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


def _settings(scratch=None, db="postgresql://u:p@h/app_db", platform=None, timeout=60):
    return SimpleNamespace(
        scenario_lab_database_url=SecretStr(scratch) if scratch else None,
        database_url=db,
        platform_database_url=platform,
        scenario_lab_timeout_seconds=timeout,
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


def test_the_apps_own_database_is_never_a_scratch_database(lab_tenants):
    slug, _ = lab_tenants
    same = _settings("postgresql://other:x@elsewhere/app_db")  # same database name
    with pytest.raises(lab.LabRefused):
        lab.start_run(same, slug, ["x"], "agents")
    plat = _settings("postgresql://u:p@h/plat_db", platform="postgresql://a:b@h/plat_db")
    with pytest.raises(lab.LabRefused):
        lab.scratch_url(plat)
    assert lab.scratch_url(_settings(SCRATCH)).endswith("scratch_db")


def test_the_child_only_sees_the_scratch_url(monkeypatch):
    others = ("MIGRATION_DATABASE_URL", "MAINT_DATABASE_URL", "PLATFORM_DATABASE_URL")
    for k in others:
        monkeypatch.setenv(k, "postgresql://u:p@h/demo")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/demo")
    env = lab.child_env("postgresql://u:p@h/scratch")
    assert env["DATABASE_URL"].endswith("/scratch")
    assert not set(others) & set(env)
    cmd = lab.child_command("t", ["a", "b"], "agents", Path("r"))
    assert "--no-seed" in cmd and "--i-know" not in cmd and cmd[cmd.index("--only") + 1] == "a,b"


def test_selection_is_checked_against_the_files(lab_tenants):
    slug, _ = lab_tenants
    s = _settings(SCRATCH)
    for ids in ([], ["no-such-scenario"], ["a", "a"]):
        with pytest.raises(ScenarioError):
            lab.start_run(s, slug, ids, "agents")
    with pytest.raises(ScenarioError):
        lab.start_run(s, slug, [lab.list_scenarios(slug)[0].id], "bogus")
    assert lab.current().status == "idle"


def test_one_run_at_a_time_and_status_is_clear(lab_tenants, monkeypatch):
    slug, _ = lab_tenants
    sid = lab.list_scenarios(slug)[0].id
    release, started = threading.Event(), threading.Event()

    def fake_run(cmd, **kw):
        started.set()
        release.wait(5)
        out = Path(cmd[cmd.index("--report-dir") + 1])
        out.mkdir(parents=True)
        row = {"id": sid, "tenant": slug, "pipeline": "agents", "passed": True}
        (out / "eval-1.json").write_text(json.dumps({"meta": {}, "rows": [], "scenarios": [row]}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
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


def test_a_refused_or_crashed_child_ends_as_failed(lab_tenants, monkeypatch):
    slug, _ = lab_tenants
    sid = lab.list_scenarios(slug)[0].id
    s = _settings(SCRATCH)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="")
    )
    lab.start_run(s, slug, [sid], "agents", wait=True)
    assert lab.current().status == "failed" and "refused" in lab.current().message

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(subprocess, "run", boom)
    lab.start_run(s, slug, [sid], "agents", wait=True)  # not stuck in 'running'
    assert lab.current().status == "failed" and "timed out" in lab.current().message


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
