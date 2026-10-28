# ruff: noqa: F811 (pytest fixtures imported from test_cases_api)
"""S7.12: the reply language follows what the customer writes, for every tenant."""

import pytest
from sqlalchemy import select

from app.core.db import tenant_session
from app.core.i18n import t
from app.core.models import AuditEvent, Case
from tests.integration.test_cases_api import _open, clean_mocks, flow  # noqa: F401

HI = "मेरे ऑर्डर में एक आइटम नहीं आया"
HI_LATN = "mera order mein ek item nahi aaya, mujhe paisa wapas chahiye"
EN = "One item was missing from my order."


def _lang(app_engine, flow, case_id):
    with tenant_session(flow["tid"], app_engine) as s:
        return s.scalar(select(Case.language).where(Case.id == case_id))


def _post(api, flow, message):
    return api.post(
        "/cases",
        headers=flow["customer"],
        json={
            "transaction_id": str(flow["order_id"]),
            "category": "missing_items",
            "message": message,
        },
    )


@pytest.mark.parametrize("message, label", [(HI, "hi"), (HI_LATN, "hi-Latn"), (EN, "en")])
def test_the_case_is_in_the_language_the_customer_wrote(api, app_engine, flow, message, label):
    opened = _open(api, flow, message=message)
    assert _lang(app_engine, flow, opened["id"]) == label
    assert opened["message"] == t("status.awaiting_approval", label)
    if label == "hi":
        assert any("ऀ" <= ch <= "ॿ" for ch in opened["message"])
    steps = api.get(f"/cases/{opened['id']}/timeline", headers=flow["customer"]).json()
    assert steps[0]["title"] == t("tl.received.title", label)


def test_detection_is_audited_with_label_source_confidence_and_no_text(api, app_engine, flow):
    opened = _open(api, flow, message=HI_LATN)
    with tenant_session(flow["tid"], app_engine) as s:
        rows = s.scalars(
            select(AuditEvent.payload).where(AuditEvent.event == "case.language_set")
        ).all()
    mine = [r for r in rows if r.get("source") == "heuristic" and r["label"] == "hi-Latn"]
    assert mine and mine[-1]["confidence"] > 0
    assert all("mera" not in str(r) for r in rows)
    assert opened["id"]


def test_a_one_word_follow_up_does_not_flip_the_language(api, app_engine, flow):
    opened = _open(api, flow, message=HI_LATN)
    assert _post(api, flow, "ok").status_code in (200, 201)
    assert _lang(app_engine, flow, opened["id"]) == "hi-Latn"
    got = api.get(f"/cases/{opened['id']}", headers=flow["customer"]).json()
    assert got["message"] == t("status.awaiting_approval", "hi-Latn")


def test_the_old_preference_is_only_the_default_when_the_message_says_nothing(
    api, app_engine, flow
):
    put = api.put("/me/preferences", headers=flow["customer"], json={"language": "hi"})
    assert put.status_code == 200
    try:
        opened = _open(api, flow, message="refund")
        assert _lang(app_engine, flow, opened["id"]) == "hi"
    finally:
        api.put("/me/preferences", headers=flow["customer"], json={"language": "en"})
