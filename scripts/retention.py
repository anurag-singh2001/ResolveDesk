"""`make retention` (dry run) / `make retention APPLY=1`: redact support message text and
contact data past each tenant's `support_retention_days` (app/engine/retention.py).

The redaction cannot be undone, so nothing is written without --apply, and the script refuses
to run at all unless APP_ENV is set explicitly (an unset APP_ENV means prod). Run daily."""

import argparse
import sys

from app.config import Settings, get_settings
from app.core.db import get_engine
from app.core.tenant_config import tenant_dirs
from app.engine.retention import purge_all


def run(argv: list[str], settings: Settings, engine=None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.retention")
    parser.add_argument("--apply", action="store_true", help="really redact (default: dry run)")
    args = parser.parse_args(argv)

    if "app_env" not in settings.model_fields_set:
        print("refusing to run: APP_ENV is not set explicitly (unset means prod)", file=sys.stderr)
        return 2
    if args.apply and settings.app_env == "prod":
        print(
            "WARNING: APP_ENV=prod and --apply: this permanently redacts customer data.",
            file=sys.stderr,
        )
    mode = "APPLY" if args.apply else "DRY RUN (nothing written; pass --apply to redact)"
    print(f"retention [{settings.app_env}] {mode}")

    reports = purge_all(engine or get_engine(), apply=args.apply)
    verb = "redacted" if args.apply else "would redact"
    failed = [slug for slug, r in reports.items() if r is None]
    for slug, r in reports.items():
        if r is not None:
            print(
                f"{slug}: {verb} {r.messages} message(s) in {r.cases} case(s), "
                f"{r.customers} customer contact(s)"
            )
    missing = len(tenant_dirs()) - len(reports)
    if failed or missing:
        print(f"FAILED tenants: {failed}, missing: {missing}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    return run(sys.argv[1:], get_settings())


if __name__ == "__main__":
    sys.exit(main())
