# ruff: noqa: F811 (pytest fixtures imported from other test modules)
"""S8.3: every decision links to its source, for every tenant, never naming one.

The remedy line comes from the stored basis (code, not model text); a citation resolves to the
exact section in the caller's own tenant, falls back to the document when the section changed,
and never returns policy text or another tenant's records.
"""

import json
import uuid
from datetime import UTC, datetime

from app.core.db import tenant_session
from app.core.i18n import t
from app.core.models import Case, Transaction
from app.core.tenant_config import tenant_dirs
from app.engine.proposals import create_proposal
from app.rag.policy_files import policy_files
from tests.integration.test_cases_api import _open, clean_mocks, flow  # noqa: F401
from tests.integration.test_policies_api import _in_force, ingested  # noqa: F401


def _case_with(f, app_engine, citations, basis=None):
    """A pending refund proposal on the customer's order carrying these citations (proposals
    are immutable, so they are given at creation, as the engine does)."""
    cid = uuid.uuid4()
    with tenant_session(f["tid"], app_engine) as s:
        order = s.get(Transaction, f["order_id"])
        s.add(
            Case(
                id=cid, tenant_id=f["tid"], customer_id=order.customer_id,
                transaction_id=order.id, status="awaiting_approval", channel="app",
                category="missing_items", opened_at=datetime.now(UTC),
            )
        )  # fmt: skip
        s.flush()
        params = {"transaction_id": str(order.id), "amount_paise": 100, "reason": "x"}
        proposal = create_proposal(
            s, f["tid"], case_id=cid, action="refund", reason="p", params=params,
            citations=citations, basis=basis,
        )  # fmt: skip
        return {"id": str(cid), "proposal_id": str(proposal.id)}


def _item(api, f, case):
    return next(
        p for p in api.get("/approvals", headers=f["hq"]).json() if p["case_id"] == case["id"]
    )


def test_remedy_line_names_the_rule_for_staff_and_customer(api, flow):
    case = _open(api, flow)
    expected = [t("basis.refund_missing", "en")]
    item = _item(api, flow, case)
    assert item["basis"][0] == expected[0]
    for headers in (flow["customer"], flow["hq"]):
        body = api.get(f"/cases/{case['id']}", headers=headers).json()
        assert body["basis"][0] == expected[0]


def test_citations_open_the_exact_section_and_never_carry_policy_text(
    api, app_engine, ingested, flow, tenant
):
    doc = next(f for f in _in_force(tenant) if f.meta.scope == "org")
    sec = doc.sections[0]
    ref = f"{doc.meta.id}#{sec.number}"
    case = _case_with(
        flow, app_engine,
        [{"section_ref": ref, "doc_key": doc.meta.id, "version": doc.meta.version}],
    )  # fmt: skip
    for headers in (flow["customer"], flow["hq"]):
        src = api.get(f"/cases/{case['id']}", headers=headers).json()["sources"]
        assert len(src) == 1
        assert src[0]["href"] == f"/policies#{doc.meta.id}-{sec.number}"
        assert src[0]["section_id"] == sec.number and src[0]["section_changed"] is False
        assert src[0]["document_title"] == doc.meta.title
        assert sec.content not in json.dumps(src)  # reference by id and title, never the text
    # The link target exists on the policies page for the same caller.
    page = api.get("/policies", headers=flow["customer"]).json()
    anchors = {s["anchor"] for d in page for s in d["sections"]}
    assert f"{doc.meta.id}-{sec.number}" in anchors
    item = _item(api, flow, case)
    assert item["sources"][0]["href"] == f"/policies#{doc.meta.id}-{sec.number}"


def test_a_changed_section_falls_back_to_the_document_and_says_so(
    api, app_engine, ingested, flow, tenant
):
    doc = next(f for f in _in_force(tenant) if f.meta.scope == "org")
    case = _case_with(
        flow, app_engine,
        [{"section_ref": f"{doc.meta.id}#99.9", "doc_key": doc.meta.id, "version": 1}],
    )  # fmt: skip
    src = api.get(f"/cases/{case['id']}", headers=flow["customer"]).json()["sources"][0]
    assert src["section_changed"] is True and src["section_id"] is None
    assert src["href"] == f"/policies#{doc.meta.id}"
    assert src["note"] == t("source.changed", "en")


def test_another_tenants_document_never_resolves(api, app_engine, ingested, flow, tenant):
    own = {f.meta.id for f in policy_files(tenant)}
    foreign = next(
        (
            (f.meta.id, f.sections[0].number)
            for other in tenant_dirs()
            if other != tenant
            for f in policy_files(other)
            if f.meta.id not in own
        ),
        None,
    )
    assert foreign, "needs a document that exists only in another tenant"
    case = _case_with(
        flow, app_engine,
        [{"section_ref": f"{foreign[0]}#{foreign[1]}", "doc_key": foreign[0], "version": 1}],
    )  # fmt: skip
    for headers in (flow["customer"], flow["hq"]):
        src = api.get(f"/cases/{case['id']}", headers=headers).json()["sources"][0]
        assert src["section_changed"] is True
        assert src["document_title"] is None and src["doc_key"] is None
        assert src["href"] == "/policies"
    assert _item(api, flow, case)["sources"][0]["doc_key"] is None


def test_malformed_citations_are_skipped(api, app_engine, flow):
    case = _case_with(flow, app_engine, ["<script>", {"doc_key": "x"}, {"section_ref": 5}])
    assert api.get(f"/cases/{case['id']}", headers=flow["customer"]).json()["sources"] == []


def test_a_revised_policy_says_so_even_when_the_section_still_exists(
    api, app_engine, ingested, flow, tenant
):
    doc = next(f for f in _in_force(tenant) if f.meta.scope == "org")
    sec = doc.sections[0]
    case = _case_with(
        flow,
        app_engine,
        [
            {
                "section_ref": f"{doc.meta.id}#{sec.number}",
                "doc_key": doc.meta.id,
                "version": doc.meta.version + 1,
            }
        ],
    )
    for headers in (flow["customer"], flow["hq"]):
        src = api.get(f"/cases/{case['id']}", headers=headers).json()["sources"][0]
        assert src["section_changed"] is False and src["policy_revised"] is True
        assert src["href"] == f"/policies#{doc.meta.id}-{sec.number}"
        assert src["note"] == t("source.version_changed", "en")
