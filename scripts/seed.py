"""make seed TENANT=<slug|all>: load tenant folders (config + catalogue).

Packs are written with MIGRATION_DATABASE_URL (owner); tenant rows with DATABASE_URL (app role,
RLS on).
"""

import sys

from sqlalchemy import create_engine

from app.config import get_settings
from app.core.db import get_engine
from app.core.tenant_config import TENANTS_DIR, load_tenant, tenant_dirs
from app.core.tenant_loader import load_pack_into_db, load_tenant_into_db
from app.core.verticals import load_pack


def main(target: str) -> int:
    folders = tenant_dirs() if target == "all" else [TENANTS_DIR / target]
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
        cfg = load_tenant(folder)
        pack = load_pack(cfg.vertical_pack)
        load_pack_into_db(owner_engine, pack)
        tid = load_tenant_into_db(engine, cfg, pack)
        print(f"loaded {cfg.slug} ({tid})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
