"""make refresh: re-apply tenant packs, settings and policies from tenants/ to the dev database.

Run automatically after `make migrate`. Dev only: it exits without touching anything unless
APP_ENV=dev (an unset APP_ENV counts as prod). Never loads or deletes order history; for that
use `make seed`.
"""

import sys

from sqlalchemy import create_engine

from app.config import get_settings
from app.core.db import get_engine
from app.core.tenant_config import tenant_dirs
from app.rag.embeddings import FastEmbedder
from scripts.seed import refresh_packs


def main() -> int:
    settings = get_settings()
    if settings.app_env != "dev":
        print(f"refresh skipped: APP_ENV={settings.app_env} (tenant packs refresh in dev only)")
        return 0
    if not settings.migration_database_url:
        print("MIGRATION_DATABASE_URL is not set")
        return 1
    for line in refresh_packs(
        tenant_dirs(), create_engine(settings.migration_database_url), get_engine(), FastEmbedder()
    ):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
