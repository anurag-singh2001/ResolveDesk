"""LangGraph checkpoints in Postgres, schema `lg` (PROJECT.md section 7: never the ledger).

The checkpointer gets its own short-lived psycopg connection per graph run or resume:
- Direct (unpooled) endpoint: Neon's pooled endpoint is PgBouncer in transaction mode, which
  rejects the `search_path` startup option and would mix session state across clients. The
  direct host is the pooled one without "-pooler" (Neon's naming); other hosts are unchanged.
- Same role as the engine (the app role, NOBYPASSRLS), with USAGE+CREATE on schema lg only
  (scripts/neon_bootstrap.sql). `setup()` creates the library's tables there on first use.
- autocommit: every checkpoint write is its own short transaction, so no transaction is open
  while a node calls a model or a provider (hard rule 5).

Checkpoint tables have no tenant_id/RLS (the library owns them). Isolation instead: the
thread id is "<tenant_id>:<case_id>", built only from the auth/system tenant and a case that
was loaded under that tenant's RLS; no API takes a thread id from input.
"""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from sqlalchemy.engine import Engine

SCHEMA = "lg"
_ready: set[tuple[str | None, str | None]] = set()


def checkpoint_url(engine: Engine) -> str:
    """libpq URL for the checkpointer: the engine's database on the direct endpoint."""
    url = engine.url.set(drivername="postgresql")
    if url.host:
        url = url.set(host=re.sub(r"-pooler(?=\.)", "", url.host, count=1))
    return url.render_as_string(hide_password=False)


def thread_config(tenant_id: uuid.UUID, case_id: uuid.UUID) -> dict:
    if not isinstance(tenant_id, uuid.UUID) or not isinstance(case_id, uuid.UUID):
        raise TypeError("tenant_id and case_id must be UUIDs from server-side context")
    return {"configurable": {"thread_id": f"{tenant_id}:{case_id}"}}


@contextmanager
def open_checkpointer(engine: Engine) -> Iterator[PostgresSaver]:
    with psycopg.connect(
        checkpoint_url(engine),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=f"-c search_path={SCHEMA}",
        connect_timeout=15,
    ) as conn:
        saver = PostgresSaver(conn)
        key = (engine.url.host, engine.url.database)
        if key not in _ready:
            saver.setup()  # idempotent: applies only the library's missing migrations
            _ready.add(key)
        yield saver
