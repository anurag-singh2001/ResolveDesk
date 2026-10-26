# ruff: noqa: F811 (pytest fixtures imported from test_agent_graph)
"""S4.1: POST /cases/{id}/messages - the customer answers a needs-info question, for every
tenant (scripted LLMs; no tenant is named)."""

import uuid

import pytest
from sqlalchemy import func, select

import app.engine.graph as graph
import app.engine.needs as needs
from app.api import routes_cases
from app.config import get_settings
from app.core.db import tenant_session
from app.core.models import ActionProposal, Case, Ticket, TicketMessage
from app.engine import agent_runner
from mocks.registry import reset_mocks
from tests.helpers import login
from tests.integration.test_agent_graph import (  # noqa: F401 (fixtures)
    FakeBudget,
    FakeLLM,
    _classify,
    _refund,
    case,
    policies_loaded,
)
from tests.integration.test_workflow_resume import _deps

REPLY = "The costliest item was missing."


@pytest.fixture(autouse=True)
def clean_mocks():
    reset_mocks()
    yield
    reset_mocks()


@pytest.fixture
def waiting(api, app_engine, case, policies_loaded, tenant, monkeypatch):
    """A free-text case paused at its question, the owner's login and scripted models."""
    clf = FakeLLM({"Classification": [_classify(needs=["which item"]), _classify()]})
    res = FakeLLM({"ResolutionDraft": [_refund(case)]})
    first = graph.run_case(
        _deps(app_engine, clf, res), case["tid"], case["case_id"], "Something was wrong.",
        FakeBudget([clf, res]),
    )  # fmt: skip
    assert first["outcome"] == "awaiting_info"
    monkeypatch.setattr(agent_runner, "_deps", lambda engine, budget: _deps(engine, clf, res))
    agents = get_settings().model_copy(update={"engine_mode": "agents"})
    monkeypatch.setattr(routes_cases, "get_settings", lambda: agents)
    cfg = policies_loaded[tenant.name]
    customers = [u for u in cfg.users if u.role == "customer"]
    return {
        "owner": login(api, cfg.slug, customers[0].email),
        "other_customer": login(api, cfg.slug, customers[1].email),
        "hq": login(api, cfg.slug, next(u.email for u in cfg.users if u.role == "hq_owner")),
        "other_tenant": next(
            login(api, c.slug, next(u.email for u in c.users if u.role == "customer"))
            for c in policies_loaded.values()
            if c.slug != cfg.slug
        ),
        "clf": clf,
        "res": res,
        "url": f"/cases/{case['case_id']}/messages",
    }


def _proposals(app_engine, case) -> int:
    with tenant_session(case["tid"], app_engine) as s:
        return s.scalar(
            select(func.count()).select_from(ActionProposal).where(
                ActionProposal.case_id == case["case_id"]
            )
        )  # fmt: skip


def test_a_reply_continues_the_case_and_shows_in_the_timeline(api, app_engine, case, waiting):
    resp = api.post(waiting["url"], headers=waiting["owner"], json={"message": REPLY})
    assert resp.status_code == 201, resp.text
    # The response is the state at submit time; the resume runs in the background after it.
    now = api.get(f"/cases/{case['case_id']}", headers=waiting["owner"]).json()
    assert now["stage"] == "awaiting_approval"  # the graph resumed and proposed
    assert REPLY in waiting["clf"].calls[1][1][-1].content  # the model input carries the reply
    assert _proposals(app_engine, case) == 1
    with tenant_session(case["tid"], app_engine) as s:
        bodies = s.scalars(
            select(TicketMessage.body).join(Ticket).where(Ticket.case_id == case["case_id"])
        ).all()
    assert REPLY in bodies
    steps = api.get(f"/cases/{case['case_id']}/timeline", headers=waiting["owner"]).json()
    assert "You replied" in [s["title"] for s in steps]


def test_a_second_reply_does_not_make_a_second_proposal(api, app_engine, case, waiting):
    first = api.post(waiting["url"], headers=waiting["owner"], json={"message": REPLY})
    again = api.post(waiting["url"], headers=waiting["owner"], json={"message": REPLY})
    assert first.status_code == 201
    assert again.status_code == 409
    assert _proposals(app_engine, case) == 1


def test_a_racing_reply_resumes_the_thread_only_once(app_engine, case, waiting):
    """Two replies that both passed the status check: the graph's claim lets one through."""
    deps = _deps(app_engine, waiting["clf"], waiting["res"])
    one = graph.resume_case(deps, case["tid"], case["case_id"], "info", {"kind": "info"})
    two = graph.resume_case(deps, case["tid"], case["case_id"], "info", {"kind": "info"})
    assert one["outcome"] != "skipped" and two["outcome"] == "skipped"
    assert _proposals(app_engine, case) == 1


@pytest.mark.parametrize("who", ["other_customer", "other_tenant"])
def test_someone_elses_case_is_a_404(api, app_engine, case, waiting, who):
    resp = api.post(waiting["url"], headers=waiting[who], json={"message": REPLY})
    assert resp.status_code == 404
    with tenant_session(case["tid"], app_engine) as s:
        assert s.get(Case, case["case_id"]).status == "awaiting_info"


def test_unknown_case_is_a_404_and_staff_cannot_reply(api, case, waiting):
    missing = api.post(
        f"/cases/{uuid.uuid4()}/messages", headers=waiting["owner"], json={"message": REPLY}
    )
    assert missing.status_code == 404
    staff = api.post(waiting["url"], headers=waiting["hq"], json={"message": REPLY})
    assert staff.status_code == 403


def test_a_case_not_waiting_for_info_is_a_409(api, app_engine, case, waiting):
    with tenant_session(case["tid"], app_engine) as s:
        s.get(Case, case["case_id"]).status = "investigating"
    resp = api.post(waiting["url"], headers=waiting["owner"], json={"message": REPLY})
    assert resp.status_code == 409
    assert "waiting" in resp.json()["detail"]


def test_an_empty_reply_is_rejected(api, waiting):
    resp = api.post(waiting["url"], headers=waiting["owner"], json={"message": ""})
    assert resp.status_code == 422


def test_the_customer_is_told_what_we_need_in_status_and_timeline(api, case, waiting):
    """The question is a code-owned template picked by the need code, never model text."""
    base = f"/cases/{case['case_id']}"
    status = api.get(base, headers=waiting["owner"]).json()
    assert status["stage"] == "awaiting_info"
    assert needs.QUESTIONS[needs.NEED_DETAILS] in status["message"]
    steps = api.get(f"{base}/timeline", headers=waiting["owner"]).json()
    asked = [s for s in steps if s["stage"] == "awaiting_info"]
    assert [s["text"] for s in asked] == [needs.QUESTIONS[needs.NEED_DETAILS]]
    assert asked[0]["title"] == "Question for you"


def test_need_codes_map_to_templates_and_unknown_codes_to_a_generic_sentence():
    assert needs.question_for(needs.NEED_ORDER) == needs.QUESTIONS[needs.NEED_ORDER]
    for odd in (None, "", "which_item_is_it", 7, "<script>"):
        assert needs.question_for(odd) == needs.GENERIC_QUESTION
    assert needs.need_from_payload({"reason": "x"}) is None
    assert needs.need_from_payload(None) is None
