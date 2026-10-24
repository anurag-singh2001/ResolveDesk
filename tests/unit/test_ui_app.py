"""Demo UI smoke tests: screens render against a faked API (no network, no DB)."""

from streamlit.testing.v1 import AppTest

from app.core.tenant_config import load_tenant, tenant_dirs
from ui.api_client import ApiClient, NotFound

APP = "../../ui/app.py"
ORDER = {
    "id": "o1",
    "external_ref": "R-1",
    "placed_at": "2026-09-01T12:30:00Z",
    "total_paise": 123450,
    "status": "delivered",
}
CASE = {
    "id": "c1",
    "category": "missing_items",
    "stage": "awaiting_approval",
    "message": "We are checking this with the outlet.",
    "action": "refund",
    "amount_paise": 34900,
    "proposal_id": "p1",
}
PENDING = {
    "proposal_id": "p1",
    "case_id": "c1",
    "category": "missing_items",
    "action": "refund",
    "risk": "medium",
    "amount_paise": 34900,
    "order_ref": "R-1",
    "order_total_paise": 123450,
    "reason": "1 item not fulfilled",
    "checks": {"within_cap": True},
    "eligible": True,
    "errors": [],
}


def fake_api(monkeypatch, routes: dict) -> None:
    def request(self, method, path, **kwargs):
        if path not in routes:
            raise NotFound(404, "not found")
        return routes[path]

    monkeypatch.setattr(ApiClient, "_request", request)


def logged_in(role: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["token"] = "tok"
    at.session_state["tenant"] = tenant_dirs()[0].name
    at.session_state["role"] = role
    at.session_state["name"] = "Demo"
    return at.run()


def test_login_screen_lists_every_tenant_and_its_demo_users():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    business, user = at.selectbox
    names = {load_tenant(d).name for d in tenant_dirs()}
    assert set(business.options) == names  # options are the displayed labels
    first = load_tenant(tenant_dirs()[0])
    assert len(user.options) == len(first.users)
    assert at.button[0].label == "Log in"


def test_customer_view_shows_orders_in_rupees_and_api_message(monkeypatch):
    fake_api(
        monkeypatch,
        {"/orders": [ORDER], "/orders/o1": {**ORDER, "items": []}, "/cases": [CASE]},
    )
    at = logged_in("customer")
    assert not at.exception
    assert "₹1,234.50" in at.selectbox[0].options[0]
    assert any(CASE["message"] in m.value for m in at.markdown)
    assert any("₹349.00" in c.value for c in at.caption)


def test_customer_cases_fall_back_to_session_when_list_endpoint_missing(monkeypatch):
    fake_api(monkeypatch, {"/orders": [], "/cases/c1": CASE})  # GET /cases -> 404
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["token"] = "tok"
    at.session_state["tenant"] = tenant_dirs()[0].name
    at.session_state["role"] = "customer"
    at.session_state["name"] = "Demo"
    at.session_state["my_cases"] = ["c1"]
    at.run()
    assert not at.exception
    assert any(CASE["message"] in m.value for m in at.markdown)


def test_staff_view_lists_pending_approvals(monkeypatch):
    fake_api(monkeypatch, {"/approvals": [PENDING], "/cases": []})
    at = logged_in("hq_owner")
    assert not at.exception
    assert {b.label for b in at.button} >= {"Approve", "Reject"}
