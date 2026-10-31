"""Scenario lab (S10.1): edit scenario files and run a subset on a scratch database.

Scenario files are repo data (tenants/<slug>/scenarios/*.yaml), not DB rows, so the platform
role needs no new grant. A run is `python -m evals.run` in a child process, started from a
background thread: never on a request thread, and no DB transaction is open anywhere here.
The child gets the SCRATCH url as DATABASE_URL (and none of the other DB urls); if no scratch
database is configured, or it is the same database as the app's own, nothing starts.
One run at a time, in this process. Status is held in memory (lost on restart, by design).
"""

import json
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings
from app.core.tenant_config import ROOT, TENANTS_DIR, load_tenant, tenant_dirs
from app.core.verticals import load_pack
from evals.scenarios import (
    Scenario,
    ScenarioError,
    load_scenarios,
    parse_scenario_text,
    scenario_file,
)

MAIN_REPORTS = ROOT / "evals" / "reports"
LAB_REPORTS = MAIN_REPORTS / "lab"  # a sub-folder: the alert rule only reads eval-*.md above it
PIPELINES = ("agents", "baseline", "both")
MAX_IDS = 40


class LabRefused(Exception):
    """The run must not start. The message is safe to show."""


def tenant_folder(slug: str) -> Path:
    for p in tenant_dirs(TENANTS_DIR):
        if p.name == slug:
            return p
    raise ScenarioError(["unknown tenant"])


def _tenant_pack(slug: str):
    folder = tenant_folder(slug)
    cfg = load_tenant(folder)
    return folder, cfg, load_pack(cfg.vertical_pack)


def list_tenants() -> list[str]:
    return [p.name for p in tenant_dirs(TENANTS_DIR)]


def list_scenarios(slug: str) -> list[Scenario]:
    folder, cfg, pack = _tenant_pack(slug)
    return load_scenarios(folder, cfg.slug, pack)


def read_text(slug: str, scenario_id: str) -> str:
    path = scenario_file(tenant_folder(slug), scenario_id)
    if not path.is_file():
        raise FileNotFoundError(scenario_id)
    return path.read_text(encoding="utf-8")


def validate_text(slug: str, text: str) -> Scenario:
    _, _, pack = _tenant_pack(slug)
    return parse_scenario_text(text, slug, pack)


def save_text(slug: str, scenario_id: str, text: str) -> Scenario:
    """Validate, then write tenants/<slug>/scenarios/<id>.yaml atomically. The id inside the
    text must be the id in the name, so the file name can never be steered by the content."""
    sc = validate_text(slug, text)
    if sc.id != scenario_id:
        raise ScenarioError([f"id: the text says {sc.id!r} but the name is {scenario_id!r}"])
    path = scenario_file(tenant_folder(slug), scenario_id)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return sc


# --- scratch database guard -------------------------------------------------------------


def _db_name(url: str | None) -> str | None:
    return (urlparse(url).path.lstrip("/") or None) if url else None


def scratch_url(s: Settings) -> str:
    """The scratch DB url, or LabRefused. Fails closed: unset, or the same database name as
    the app's own (demo) database, or as the platform database, means no run."""
    secret = s.scenario_lab_database_url
    raw = secret.get_secret_value().strip() if secret else ""
    if not raw:
        raise LabRefused("no scratch database is configured for the lab")
    name = _db_name(raw)
    if name is None or name in {_db_name(s.database_url), _db_name(s.platform_database_url)}:
        raise LabRefused("the lab's scratch database is the same as an app database; refusing")
    return raw


def scratch_configured(s: Settings) -> bool:
    try:
        scratch_url(s)
    except LabRefused:
        return False
    return True


# --- one run at a time ------------------------------------------------------------------


@dataclass
class RunState:
    run_id: str = ""
    status: str = "idle"  # idle | running | succeeded | failed
    tenant: str = ""
    ids: list[str] = field(default_factory=list)
    pipeline: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    message: str = ""
    report: str | None = None  # "<run id>/<file>.json", inside LAB_REPORTS


_lock = threading.Lock()
_state = RunState()


def current() -> RunState:
    with _lock:
        return RunState(**asdict(_state))


def reset_for_tests() -> None:
    global _state
    with _lock:
        _state = RunState()


def start_run(
    s: Settings, slug: str, ids: list[str], pipeline: str, *, wait: bool = False
) -> RunState:
    """Validate the request, then launch the child in a background thread. Raises LabRefused
    (no scratch / already running) or ScenarioError (bad selection)."""
    global _state
    url = scratch_url(s)
    if pipeline not in PIPELINES:
        raise ScenarioError(["pipeline: choose agents, baseline or both"])
    if not ids or len(ids) > MAX_IDS or len(set(ids)) != len(ids):
        raise ScenarioError([f"choose between 1 and {MAX_IDS} different scenarios"])
    known = {sc.id for sc in list_scenarios(slug)}
    if any(i not in known for i in ids):
        raise ScenarioError(["unknown scenario in the selection"])
    with _lock:
        if _state.status == "running":
            raise LabRefused("a run is already in progress")
        run_id = uuid.uuid4().hex[:12]
        _state = RunState(
            run_id=run_id, status="running", tenant=slug, ids=list(ids), pipeline=pipeline,
            started_at=datetime.now(UTC).isoformat(),
        )  # fmt: skip
        snapshot = RunState(**asdict(_state))
    t = threading.Thread(
        target=_execute, args=(s, url, run_id, slug, ids, pipeline), daemon=True, name="lab-run"
    )
    t.start()
    if wait:
        t.join()
    return snapshot


_OTHER_DB_VARS = {
    "MIGRATION_DATABASE_URL",
    "MAINT_DATABASE_URL",
    "PLATFORM_DATABASE_URL",
    "SCENARIO_LAB_DATABASE_URL",
}


def child_env(url: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in _OTHER_DB_VARS}
    env["DATABASE_URL"] = url
    return env


def child_command(slug: str, ids: list[str], pipeline: str, report_dir: Path) -> list[str]:
    # --no-seed: the child never reseeds; --i-know is never passed.
    return [
        sys.executable, "-m", "evals.run", "--tenant", slug, "--only", ",".join(ids), "--all",
        "--no-seed", "--pipeline", pipeline, "--report-dir", str(report_dir),
    ]  # fmt: skip


def _finish(run_id: str, status: str, message: str, report: str | None) -> None:
    with _lock:
        if _state.run_id == run_id:
            _state.status, _state.message, _state.report = status, message, report
            _state.finished_at = datetime.now(UTC).isoformat()


def _execute(s: Settings, url: str, run_id: str, slug: str, ids: list[str], pipeline: str) -> None:
    try:
        report_dir = LAB_REPORTS / run_id
        proc = subprocess.run(  # noqa: S603 - fixed argv, ids already checked against files
            child_command(slug, ids, pipeline, report_dir),
            cwd=ROOT, env=child_env(url), capture_output=True, text=True,
            timeout=s.scenario_lab_timeout_seconds, check=False,
        )  # fmt: skip
        twin = next(iter(sorted(report_dir.glob("eval-*.json"))), None)
        if twin is not None:
            note = "finished"
            if proc.returncode:
                note = "finished; a scenario errored or went past the business rule"
            _finish(run_id, "succeeded", note, f"{run_id}/{twin.name}")
        elif proc.returncode == 2:
            _finish(run_id, "failed", "the eval refused to run on this database", None)
        else:
            _finish(run_id, "failed", f"stopped without a report (exit {proc.returncode})", None)
    except subprocess.TimeoutExpired:
        _finish(run_id, "failed", "the run timed out and was stopped", None)
    except Exception as exc:  # noqa: BLE001 - the lab must always leave 'running'
        _finish(run_id, "failed", f"the run could not start ({type(exc).__name__})", None)


# --- comparison with the last report ----------------------------------------------------


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _failing_ids_from_md(path: Path) -> set[str]:
    out, on = set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Failing scenarios"):
            on = True
        elif on and line.startswith("- ") and " [" in line:
            out.add(line[2:].split(" [", 1)[0].strip())
    return out


def last_report(main_dir: Path = MAIN_REPORTS) -> dict | None:
    """The newest full eval report. The json twin names passing and failing ids; an older
    md-only report names only the failing ones (passing is then None)."""
    files = sorted(main_dir.glob("eval-*.md")) if main_dir.is_dir() else []
    if not files:
        return None
    md = files[-1]
    twin = _load_json(md.with_suffix(".json"))
    if twin:
        sc = twin.get("scenarios", [])
        return {
            "name": md.name, "when": twin.get("meta", {}).get("when", ""),
            "rows": twin.get("rows", []),
            "failing": {x["id"] for x in sc if not x["passed"]},
            "passing": {x["id"] for x in sc if x["passed"]},
        }  # fmt: skip
    return {
        "name": md.name, "when": md.stem.removeprefix("eval-"), "rows": [],
        "failing": _failing_ids_from_md(md), "passing": None,
    }  # fmt: skip


def _before(sid: str, last: dict | None) -> str:
    if last is None:
        return "unknown"
    if sid in last["failing"]:
        return "failed"
    if last["passing"] is None:
        return "not failing"  # md-only report: passed or not run, cannot tell
    return "passed" if sid in last["passing"] else "unknown"


def compare(new: dict, last: dict | None) -> dict:
    """Per scenario of the new run: now, and what the last report said. `change` is
    regressed / improved / same / unknown."""
    entries = []
    for x in new.get("scenarios", []):
        before, now = _before(x["id"], last), "passed" if x["passed"] else "failed"
        if before in ("unknown", "not failing") and now == "passed":
            change = "unknown" if before == "unknown" else "same"
        elif before == "unknown":
            change = "unknown"
        elif before == "not failing":
            change = "regressed"
        elif before == now:
            change = "same"
        else:
            change = "regressed" if now == "failed" else "improved"
        entries.append(
            {"id": x["id"], "pipeline": x["pipeline"], "before": before, "now": now,
             "change": change}
        )  # fmt: skip
    return {
        "last_report": None if last is None else {"name": last["name"], "when": last["when"]},
        "scenarios": entries,
        "new_rows": new.get("rows", []),
        "last_rows": [] if last is None else last["rows"],
    }


def run_result(state: RunState) -> dict | None:
    if state.status != "succeeded" or not state.report:
        return None
    rel = Path(state.report)
    if len(rel.parts) != 2 or ".." in rel.parts:
        return None
    new = _load_json(LAB_REPORTS / rel)
    return None if new is None else compare(new, last_report())
