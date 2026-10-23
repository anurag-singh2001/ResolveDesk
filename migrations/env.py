from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.core.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # Tests pass the test-branch URL via attributes; otherwise use the owner URL from settings.
    url = config.attributes.get("url") or get_settings().migration_database_url
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL is not set")
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
