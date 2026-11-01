"""Run the test suite in small tracked batches, in parallel, one database per worker.

A single pytest run takes over four hours against the remote database, one network drop spoils
everything after it, and reasons only print at the end. This splits the suite into batches, saves
each result as it finishes, retries batches lost to the network, and can resume or rerun failures.

    uv run python -m scripts.run_test_batches --env a.env --env b.env        # start or resume
    uv run python -m scripts.run_test_batches --env a.env --rerun-failed     # only what failed
    uv run python -m scripts.run_test_batches --status                       # print progress
    uv run python -m scripts.run_test_batches --fresh --env a.env            # forget saved results

Each --env file holds one database's settings as KEY=value lines. Files are read, never printed.
Progress is in .test-runs/status.md and .test-runs/state.json; logs are in .test-runs/logs/.
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".test-runs"
STATE = RUNS / "state.json"
STATUS = RUNS / "status.md"
LOGS = RUNS / "logs"

DB_FOLDERS = ("tests/chaos", "tests/integration", "tests/isolation")
BATCH_WEIGHT = 60  # test functions, about 15 minutes on the remote database
HANG_SECONDS = 900  # no new log output for this long means the batch is stuck
NETWORK_RETRIES = 3
NETWORK_WAIT_SECONDS = 60
NETWORK_ERRORS = (
    "failed to resolve host",
    "getaddrinfo failed",
    "server closed the connection",
    "connection timeout expired",
    "consuming input failed",
    "connection is closed",
    "SSL connection has been closed",
    "could not receive data from server",
)
SECRET = re.compile(r"postgres\S+|ep-[\w.-]+\.neon\.tech")


def weight(path: Path) -> int:
    """Test functions in a file, the cheap stand-in for how long it takes."""
    return max(1, len(re.findall(r"^\s*(?:async\s+)?def test_", path.read_text("utf-8"), re.M)))


def split_batches(weights: dict[str, int], limit: int = BATCH_WEIGHT) -> list[list[str]]:
    """Group files, in name order, into batches of about `limit`. A big file stays whole, and
    name order keeps related files together."""
    batches: list[list[str]] = []
    current: list[str] = []
    total = 0
    for name in sorted(weights):
        if current and total + weights[name] > limit:
            batches.append(current)
            current, total = [], 0
        current.append(name)
        total += weights[name]
    if current:
        batches.append(current)
    return batches


def plan(root: Path = ROOT) -> dict[str, list[str]]:
    """Batch id -> test files. Unit tests need no database, so they are one quick batch."""
    out: dict[str, list[str]] = {"unit": ["tests/unit"]}
    for folder in DB_FOLDERS:
        files = {
            p.relative_to(root).as_posix(): p for p in sorted((root / folder).glob("test_*.py"))
        }
        weights = {name: weight(path) for name, path in files.items()}
        label = folder.rsplit("/", 1)[1]
        for number, group in enumerate(split_batches(weights), 1):
            out[f"{label}-{number:02d}"] = group
    return out


def is_network_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in NETWORK_ERRORS)


def read_junit(path: Path) -> dict:
    """Counts, failing tests and whether every failure was the network, from a junit file."""
    result = {"passed": 0, "failed": 0, "skipped": 0, "failures": [], "network_only": False}
    if not path.exists():
        return result
    try:
        cases = list(ET.parse(path).getroot().iter("testcase"))
    except ET.ParseError:
        return result
    texts = []
    for case in cases:
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is not None:
            file = case.get("classname", "").replace(".", "/") + ".py"
            detail = SECRET.sub("<hidden>", f"{bad.get('message', '')} {bad.text or ''}")
            first = next((ln for ln in detail.splitlines() if ln.strip()), "")
            result["failures"].append(
                {"file": file, "test": case.get("name", ""), "reason": first.strip()[:160]}
            )
            texts.append(detail)
        elif case.find("skipped") is not None:
            result["skipped"] += 1
        else:
            result["passed"] += 1
    result["failed"] = len(result["failures"])
    result["network_only"] = bool(texts) and all(is_network_failure(t) for t in texts)
    return result


def load_env(path: str) -> dict[str, str]:
    env = dict(os.environ)
    for raw in Path(path).read_text("utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    return env


def load_state() -> dict:
    return json.loads(STATE.read_text("utf-8")) if STATE.exists() else {"batches": {}}


LOCK = threading.Lock()


def save(state: dict, batches: dict[str, list[str]]) -> None:
    RUNS.mkdir(exist_ok=True)
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=1), "utf-8")
    temp.replace(STATE)
    STATUS.write_text(render(state, batches), "utf-8")


def render(state: dict, batches: dict[str, list[str]]) -> str:
    done = state["batches"]
    finished = [b for b in batches if done.get(b, {}).get("status") in ("passed", "failed")]
    passed = sum(done[b].get("passed", 0) for b in finished)
    failed = sum(done[b].get("failed", 0) for b in finished)
    lines = [
        "# Test run status",
        "",
        f"Updated {time.strftime('%H:%M:%S')}. Commit {state.get('commit', '?')}.",
        "",
        f"Batches finished: {len(finished)} of {len(batches)}. "
        f"Tests passed: {passed}. Failed: {failed}.",
        "",
        "| Batch | State | Passed | Failed | Skipped | Minutes | Tries |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in batches:
        row = done.get(name, {})
        minutes = f"{row['seconds'] / 60:.1f}" if "seconds" in row else ""
        lines.append(
            f"| {name} | {row.get('status', 'waiting')} | {row.get('passed', '')} | "
            f"{row.get('failed', '')} | {row.get('skipped', '')} | {minutes} | "
            f"{row.get('tries', '')} |"
        )
    failures = [f for b in batches for f in done.get(b, {}).get("failures", [])]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- `{f['file']}` `{f['test']}`: {f['reason']}" for f in failures]
    return "\n".join(lines) + "\n"


def run_pytest(name: str, targets: list[str], env: dict, attempt: int) -> tuple[dict, bool]:
    """One pytest process. Returns the junit result and whether it hung."""
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{name}.{attempt}.log"
    junit = LOGS / f"{name}.{attempt}.xml"
    junit.unlink(missing_ok=True)
    cmd = ["uv", "run", "pytest", *targets, "-q", "--tb=short", "-p", "no:cacheprovider",
           f"--junitxml={junit}", "-o", "junit_family=xunit1"]  # fmt: skip
    hung = False
    with log.open("wb") as out:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
        size, last = 0, time.monotonic()
        while proc.poll() is None:
            time.sleep(5)
            now = log.stat().st_size
            if now != size:
                size, last = now, time.monotonic()
            elif time.monotonic() - last > HANG_SECONDS:
                hung = True
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                break
    return read_junit(junit), hung


def run_batch(name: str, targets: list[str], env: dict, state: dict, batches: dict) -> None:
    row = state["batches"].setdefault(name, {})
    previous_passed = row.get("passed", 0) if row.get("rerun") else 0
    started = time.monotonic()
    for attempt in range(1, NETWORK_RETRIES + 2):
        with LOCK:
            row.update(status="running", tries=attempt)
            save(state, batches)
        result, hung = run_pytest(name, targets, env, attempt)
        ran = result["passed"] + result["failed"] + result["skipped"]
        lost = ran == 0 or hung or result["network_only"]
        if not lost or attempt > NETWORK_RETRIES:
            break
        time.sleep(NETWORK_WAIT_SECONDS)  # the network usually comes back within a minute
    status = "failed" if result["failed"] or ran == 0 or hung else "passed"
    with LOCK:
        row.update(
            status=status,
            passed=result["passed"] + previous_passed,
            failed=result["failed"],
            skipped=result["skipped"],
            failures=result["failures"],
            seconds=time.monotonic() - started,
            hung=hung,
            rerun=False,
        )
        save(state, batches)


def worker(env_file: str, jobs: queue.Queue, state: dict, batches: dict) -> None:
    env = load_env(env_file)
    while True:
        try:
            name, targets = jobs.get_nowait()
        except queue.Empty:
            return
        try:
            run_batch(name, targets, env, state, batches)
        except Exception as exc:  # one batch must not stop the rest of the run
            with LOCK:
                state["batches"][name] = {"status": "failed", "failed": 1, "failures": [
                    {"file": name, "test": "runner", "reason": type(exc).__name__}]}  # fmt: skip
                save(state, batches)


def commit() -> str:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True)
    return out.stdout.decode().strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", action="append", default=[], help="env file, one per worker")
    ap.add_argument("--rerun-failed", action="store_true", help="rerun only the failing files")
    ap.add_argument("--fresh", action="store_true", help="forget saved results first")
    ap.add_argument("--status", action="store_true", help="print progress and stop")
    ap.add_argument("--only", help="comma-separated batch names")
    args = ap.parse_args()

    batches = plan()
    state = {"batches": {}} if args.fresh else load_state()
    if args.status:
        print(render(state, batches))
        return 0
    if not args.env:
        ap.error("give at least one --env file")
    if state.get("commit") not in (None, commit()) and not args.fresh:
        print(f"saved results are from {state['commit']}, now at {commit()}: use --fresh")
        return 2
    state["commit"] = commit()

    wanted = set(args.only.split(",")) if args.only else set(batches)
    jobs: queue.Queue = queue.Queue()
    for name, targets in batches.items():
        row = state["batches"].get(name, {})
        if name not in wanted:
            continue
        if args.rerun_failed:
            files = sorted({f["file"] for f in row.get("failures", [])})
            if row.get("status") == "failed":
                row["rerun"] = True
                jobs.put((name, files or targets))
        elif row.get("status") != "passed":
            jobs.put((name, targets))
    save(state, batches)

    threads = [
        threading.Thread(target=worker, args=(path, jobs, state, batches)) for path in args.env
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    save(state, batches)
    print(render(state, batches))
    return 1 if any(state["batches"].get(b, {}).get("status") != "passed" for b in batches) else 0


if __name__ == "__main__":
    sys.exit(main())
