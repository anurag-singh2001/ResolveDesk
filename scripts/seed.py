"""make seed TENANT=<slug|all> SEED=42: load tenant folders, then generate their history.

Packs are written with MIGRATION_DATABASE_URL (owner); tenant config with DATABASE_URL (app
role); generated history with MAINT_DATABASE_URL (may delete engine rows; RLS still applies).
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
from app.rag.embeddings import FastEmbedder, HashEmbedder
from app.rag.ingest import ingest_policies
from simulator.load import load_history


def refresh_packs(folders, owner_engine, engine, embedder) -> list[str]:
    """Bring each tenant's pack, config rows, settings and policies up to date with its folder.

    Idempotent (every write is an upsert keyed by a deterministic id) and it never reads or
    writes order history, so it is safe to run after every pull. Returns one line per tenant.
    """
    lines = []
    for folder in folders:
        if not (folder / "tenant.yaml").is_file():
            raise FileNotFoundError(f"no tenant folder: {folder.name}")
        started = time.perf_counter()
        cfg = load_tenant(folder)
        pack = load_pack(cfg.vertical_pack)
        load_pack_into_db(owner_engine, pack)
        tid = load_tenant_into_db(engine, cfg, pack)
        stats = ingest_policies(engine, cfg.slug, folder, embedder)
        lines.append(
            f"refreshed {cfg.slug} ({tid}), policies {stats.documents} ({stats.written} written)"
            f" in {time.perf_counter() - started:.1f}s"
        )
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant", nargs="?", default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument(
        "--hash-embeddings", action="store_true", help="offline: no model download (tests/CI)"
    )
    args = parser.parse_args(argv)

    folders = tenant_dirs() if args.tenant == "all" else [TENANTS_DIR / args.tenant]
    owner_url = get_settings().migration_database_url
    if not owner_url:
        print("MIGRATION_DATABASE_URL is not set")
        return 1
    owner_engine = create_engine(owner_url)
    maint_url = get_settings().maint_database_url
    if not maint_url and not args.no_history:
        print("MAINT_DATABASE_URL is not set (needed to replace history)")
        return 1
    maint_engine = create_engine(maint_url) if maint_url else None
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
        embedder = HashEmbedder() if args.hash_embeddings else FastEmbedder()
        stats = ingest_policies(engine, cfg.slug, folder, embedder)
        summary = f", policies {stats.documents} ({stats.written} written)"
        if not args.no_history:
            history = load_history(maint_engine, cfg, pack, seed=args.seed, scale=args.scale)
            summary += (
                f", {len(history.customers)} customers, {len(history.transactions)} orders,"
                f" {len(history.tickets)} tickets, checksum {history.checksum()[:12]}"
            )
        print(f"loaded {cfg.slug} ({tid}){summary} in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
