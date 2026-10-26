"""`make retention`: redact support message text and contact data past each tenant's
`support_retention_days` (app/engine/retention.py). Idempotent; run daily, not per minute."""

import sys

from app.core.db import get_engine
from app.engine.retention import purge_all


def main() -> int:
    for slug, r in purge_all(get_engine()).items():
        print(
            f"{slug}: redacted {r.messages} message(s) in {r.cases} case(s), "
            f"{r.customers} customer contact(s)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
