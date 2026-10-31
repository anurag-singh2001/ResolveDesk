"""make eval: seed fresh, run every tenant's scenarios through the agent pipeline and the
single-call baseline, print a per-tenant table and write evals/reports/eval-<time>.md.

    make eval                                   # all tenants, tuning set, both pipelines
    make eval ARGS="--tenant <slug> --held-out" # held-out set only
    make eval ARGS="--all --no-seed"            # every scenario, on the DB as it is

Needs DATABASE_URL (+ MIGRATION_/MAINT_DATABASE_URL for the reseed) and the LLM keys.
Exit code 1 if any proposal goes beyond the business rule (must never happen) or a scenario
errors; scores below target don't fail the run, they are what is being measured.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings
from app.core.db import get_engine
from app.core.tenant_config import TENANTS_DIR, load_tenant, tenant_dirs
from app.core.verticals import load_pack
from app.engine.agent_runner import PIPELINES, run_agents
from app.llm.providers import model_name
from evals.harness import existing_case_orders, run_scenarios
from evals.metrics import COLUMNS, failure_line, score, summarize
from evals.scenarios import load_scenarios

REPORTS = Path(__file__).resolve().parent / "reports"
LEGEND = (
    "Columns: pass = category, outcome, action and amount rule all right; amt=rule /"
    " amt<=rule over proposals with an amount; esc P/R = escalation precision/recall; inj held"
    " = injection scenarios with no action beyond the expected one; over rule = proposals the"
    " business rule doesn't allow (target 0); LLM/case = logical calls; cost/1k = list-price"
    " estimate for 1,000 cases (cache hits cost 0)."
)


def table(rows: list[tuple[str, str, dict[str, str]]]) -> str:
    head = ["tenant", "pipeline"] + [label for _, label in COLUMNS]
    body = [[t, p] + [m[k] for k, _ in COLUMNS] for t, p, m in rows]
    widths = [max(len(str(x)) for x in col) for col in zip(head, *body, strict=True)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return "\n".join([fmt.format(*head), fmt.format(*["-" * w for w in widths])] +
                     [fmt.format(*r) for r in body])  # fmt: skip


def markdown(rows, failures: list[str], meta: dict[str, str]) -> str:
    head = ["tenant", "pipeline"] + [label for _, label in COLUMNS]
    lines = [f"# Eval report {meta['when']}", ""]
    lines += [f"- {k}: {v}" for k, v in meta.items() if k != "when"]
    lines += ["", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join([t, p] + [m[k] for k, _ in COLUMNS]) + " |" for t, p, m in rows]
    lines += ["", LEGEND, ""]
    lines += ["## Failing scenarios", ""] + ([f"- {f}" for f in failures] or ["None."])
    return "\n".join(lines) + "\n"


def _db_name(url: str | None) -> str | None:
    return urlparse(url).path.lstrip("/") if url else None


def reseeds_default_db() -> bool:
    """True when the effective database is the one the dotenv file names (the demo database):
    `make eval` reseeds, which wipes cases, so it must not run there by accident."""
    from dotenv import dotenv_values

    default = dotenv_values(os.environ.get("ENV_FILE", ".env")).get("DATABASE_URL")
    effective = os.environ.get("DATABASE_URL") or default
    return _db_name(default) is not None and _db_name(default) == _db_name(effective)


def refuses_scratch_check() -> str | None:
    """--require-scratch: a reason to refuse, or None. The effective DATABASE_URL must be a
    well-formed url that is not the same host+port+database as any protected target: the
    dotenv file's app/migration/maint/platform urls, plus those the scenario lab lists in
    EVAL_PROTECTED_DB_TARGETS. With no protected target known at all it refuses (fail closed).
    Applies with --no-seed too."""
    import json

    from dotenv import dotenv_values

    from app.core.db_targets import BadDbUrl, db_target, safe_target

    try:
        effective = db_target(os.environ.get("DATABASE_URL") or "")
    except BadDbUrl as exc:
        return f"DATABASE_URL is not usable ({exc})"
    protected = []
    dot = dotenv_values(os.environ.get("ENV_FILE", ".env"))
    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL", "MAINT_DATABASE_URL",
                "PLATFORM_DATABASE_URL"):  # fmt: skip
        try:
            if (t := safe_target(dot.get(key))) is not None:
                protected.append(t)
        except BadDbUrl:
            continue
    try:
        listed = json.loads(os.environ.get("EVAL_PROTECTED_DB_TARGETS") or "[]")
        protected += [(str(h), int(p), str(d)) for h, p, d in listed]
    except (ValueError, TypeError):
        return "EVAL_PROTECTED_DB_TARGETS is malformed"
    if not protected:
        return "no protected database is known to compare with"
    return "DATABASE_URL is an app database" if effective in protected else None


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252 (no ₹)
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="one tenant folder; default: all")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--held-out", action="store_true", help="only held-out scenarios")
    group.add_argument("--all", action="store_true", help="tuning + held-out scenarios")
    ap.add_argument("--pipeline", choices=[*PIPELINES, "both"], default="both")
    ap.add_argument("--no-seed", action="store_true", help="skip the fresh reseed")
    ap.add_argument("--i-know", action="store_true",
                    help="allow the reseed on the app's default (demo) database")  # fmt: skip
    ap.add_argument("--scale", type=float, default=0.25, help="history scale for the reseed")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--report-dir", help="write the report (md + json) here, not evals/reports")
    ap.add_argument("--require-scratch", action="store_true",
                    help="refuse unless DATABASE_URL is a different database from every "
                    "app target (also with --no-seed)")  # fmt: skip
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between cases")
    args = ap.parse_args(argv)

    if args.require_scratch and (why := refuses_scratch_check()):
        print(f"refusing to run: {why}", file=sys.stderr)
        return 2
    if not args.no_seed and not args.i_know and reseeds_default_db():
        print(
            "refusing to reseed: DATABASE_URL points at the same database as the dotenv "
            "default (the demo data). Point DATABASE_URL at a scratch database, or pass "
            "--i-know / --no-seed.",
            file=sys.stderr,
        )
        return 2
    folders = [TENANTS_DIR / args.tenant] if args.tenant else tenant_dirs()
    if not args.no_seed:
        from scripts import seed

        for folder in folders:
            code = seed.main([folder.name, "--seed", str(args.seed), "--scale", str(args.scale)])
            if code:
                return code
    s = get_settings()
    model = model_name("main", s.llm_provider, s)
    pipelines = list(PIPELINES) if args.pipeline == "both" else [args.pipeline]
    only = set(args.only.split(",")) if args.only else None
    engine = get_engine()
    rows, failures, all_results = [], [], []
    for folder in folders:
        cfg = load_tenant(folder)
        scenarios = [
            sc
            for sc in load_scenarios(folder, cfg.slug, load_pack(cfg.vertical_pack))
            if (args.all or sc.held_out == args.held_out) and (only is None or sc.id in only)
        ]
        if not scenarios:
            continue
        skip = existing_case_orders(engine, cfg.slug)
        for pipeline in pipelines:
            print(f"{cfg.slug}: {len(scenarios)} scenarios, {pipeline}...", flush=True)
            results = run_scenarios(engine, cfg.slug, scenarios, pipeline, run_agents, skip,
                                    args.pause)  # fmt: skip
            all_results += results
            rows.append((cfg.slug, pipeline, summarize(results, model)))
            failures += [f for r in results if (f := failure_line(r))]
    if not rows:
        print("no scenarios selected")
        return 1
    meta = {
        "when": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "set": "all" if args.all else ("held-out" if args.held_out else "tuning"),
        "models": f"main {s.llm_provider}:{model}, classifier {s.llm_classifier_provider}:"
        f"{model_name('classifier', s.llm_classifier_provider, s)},"
        f" fallback {s.llm_fallback_provider}",
        "cache": "on" if s.llm_cache else "off",
        "seed": "existing DB" if args.no_seed else f"fresh, SEED={args.seed} scale={args.scale}",
    }
    print()
    print(table(rows))
    if failures:
        print("\nFailing scenarios:")
        for f in failures:
            print(f"  - {f}")
    out_dir = Path(args.report_dir) if args.report_dir else REPORTS
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"eval-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(markdown(rows, failures, meta), encoding="utf-8")
    # Machine-readable twin for the scenario lab's comparison: pass/fail per scenario.
    summary = {
        "meta": meta,
        "rows": [{"tenant": t, "pipeline": p, "metrics": m} for t, p, m in rows],
        "scenarios": [
            {"id": r.scenario.id, "tenant": r.scenario.tenant, "pipeline": r.pipeline,
             "passed": score(r).passed}
            for r in all_results
        ],
    }  # fmt: skip
    path.with_suffix(".json").write_text(json.dumps(summary), encoding="utf-8")
    print(f"\nreport: {path}")
    broken = [r for r in all_results if score(r).over_ceiling or r.outcome == "error"]
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
