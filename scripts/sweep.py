"""`make sweep`: finish approved-but-never-executed proposals, reconcile unfinished
executions, and escalate cases whose agent run died (app/engine/sweeper.py).

Safe to run at any time and as often as you like (cron, after a restart): every write uses
the proposal's stable idempotency key.
"""

import sys

from app.core.db import get_engine
from app.engine.sweeper import sweep_all


def main() -> int:
    reports = sweep_all(get_engine())
    for slug, r in reports.items():
        print(
            f"{slug}: executed {len(r.executed)}, reconciled {len(r.reconciled)}, "
            f"escalated {len(r.escalated_cases)} case(s), "
            f"owners assigned {len(r.owners_assigned)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
