"""Pure parts of E4.1/E4.2: the verifier's comparison, the checkpointer URL and thread id,
and the event bus wiring."""

import uuid

import pytest
from sqlalchemy import create_engine

from app.connectors.base import RefundOutcome
from app.core import events
from app.engine.checkpoint import checkpoint_url, thread_config
from app.engine.verifier import compare

OK = RefundOutcome("succeeded", "rf_1", None, 500)


@pytest.mark.parametrize(
    "ours, ref, found, expected",
    [
        ("succeeded", "rf_1", OK, "verified"),
        ("succeeded", "rf_1", RefundOutcome("succeeded", "rf_1", None, 501), "mismatch"),
        ("succeeded", "rf_1", RefundOutcome("succeeded", "rf_2", None, 500), "mismatch"),
        ("succeeded", "rf_1", None, "mismatch"),  # provider has no record of "our" success
        ("succeeded", "rf_1", RefundOutcome("processing", "rf_1", None, 500), "mismatch"),
        ("succeeded", "rf_1", RefundOutcome("unavailable"), "unknown"),
        ("succeeded", "rf_1", RefundOutcome("succeeded", "rf_1", None, None), "unknown"),
        ("failed", None, RefundOutcome("failed", "rf_1", "declined", 500), "verified"),
        ("failed", None, OK, "mismatch"),  # the money moved after all: a person checks
    ],
)
def test_verifier_trusts_only_a_matching_provider_record(ours, ref, found, expected):
    assert compare(ours, ref, 500, found)[0] == expected


def test_checkpointer_uses_the_direct_endpoint_of_the_same_database():
    pooled = create_engine(
        "postgresql+psycopg://u:p@ep-x-pooler.region.neon.tech/db1?sslmode=require"
    )
    url = checkpoint_url(pooled)
    assert url.startswith("postgresql://u:p@ep-x.region.neon.tech/db1")
    assert "sslmode=require" in url
    plain = create_engine("postgresql+psycopg://u:p@localhost:5432/db1")
    assert checkpoint_url(plain) == "postgresql://u:p@localhost:5432/db1"


def test_thread_ids_are_tenant_scoped_and_typed():
    t, c = uuid.uuid4(), uuid.uuid4()
    assert thread_config(t, c) == {"configurable": {"thread_id": f"{t}:{c}"}}
    with pytest.raises(TypeError):
        thread_config(str(t), c)  # never a string from input


def test_the_customer_update_subscriber_is_registered_for_case_events():
    for name in ("case.proposed", "case.approved", "case.rejected", "case.executed",
                 "case.verified", "case.escalated"):  # fmt: skip
        assert any(fn.__name__ == "post_customer_update" for fn in events.subscribers(name))
    assert events.subscribers("case.awaiting_info") == []  # the question is posted directly
