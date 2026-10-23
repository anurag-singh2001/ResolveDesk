"""make seed TENANT=<slug|all> SEED=42: load tenant folders, then generate their history.

Packs are written with MIGRATION_DATABASE_URL (owner); tenant rows with DATABASE_URL (app role,
RLS on).
"""

import argparse
import sys
import time

from sqlalchemy import create_engine

from app.config import get_settings
from app.core.db import get_engine
from app.core.tenant_config import TENANTS_DIR, load_tenant, tenant_dirs
from app.core.tenant_loader import load_pack_into_db, load_tenant_into_db
from app.core.verticals import load_pack
from simulator.load import load_history


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant", nargs="?", default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args(argv)

    folders = tenant_dirs() if args.tenant == "all" else [TENANTS_DIR / args.tenant]
    owner_url = get_settings().migration_database_url
    if not owner_url:
        print("MIGRATION_DATABASE_URL is not set")
        return 1
    owner_engine = create_engine(owner_url)
    engine = get_engine()
    for folder in folders:
        if not (folder / "tenant.yaml").is_file():
            print(f"no tenant folder: {folder.name}")
            return 1
        started = time.perf_counter()
        cfg = load_tenant(folder)
        pack = load_pack(cfg.vertical_pack)
        load_pack_into_db(owner_engine, pack)
        tid = load_tenant_into_db(engine, cfg, pack)
        summary = ""
        if not args.no_history:
            history = load_history(engine, cfg, pack, seed=args.seed, scale=args.scale)
            summary = (
                f", {len(history.customers)} customers, {len(history.transactions)} orders,"
                f" {len(history.tickets)} tickets, checksum {history.checksum()[:12]}"
            )
        print(f"loaded {cfg.slug} ({tid}){summary} in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
