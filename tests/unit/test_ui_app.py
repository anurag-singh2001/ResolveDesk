"""Demo UI smoke tests: screens render against a faked API (no network, no DB)."""

import pytest
from streamlit.testing.v1 import AppTest

from app.config import get_settings
from app.core.tenant_config import load_tenant, tenant_dirs
from ui.api_client import ApiClient, NotFound, Unauthorized

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
CATEGORIES = {"categories": ["late_delivery", "missing_items"], "free_text": False}


def fake_api(monkeypatch, routes: dict) -> list[tuple[str, str, dict]]:
    """Patch the client: a route ("/path" or "METHOD /path") maps to a JSON body, or to an
    exception it raises."""
    seen: list[tuple[str, str, dict]] = []

    def request(self, method, path, **kwargs):
        seen.append((method, path, kwargs))
        key = f"{method} {path}" if f"{method} {path}" in routes else path
        if key not in routes:
            raise NotFound(404, "not found")
        out = routes[key]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(ApiClient, "_request", request)
    return seen


def logged_in(role: str, **state) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["token"] = "tok"
    at.session_state["tenant"] = tenant_dirs()[0].name
    at.session_state["role"] = role
    at.session_state["name"] = "Demo"
    for key, value in state.items():
        at.session_state[key] = value
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


def test_login_takes_identity_from_me_not_from_the_picker(monkeypatch):
    first = load_tenant(tenant_dirs()[0]).users[0]
    api_role = "customer" if first.role != "customer" else "hq_owner"
    seen = fake_api(
        monkeypatch,
        {
            "/auth/login": {"access_token": "tok", "token_type": "bearer"},
            "/me": {
                "user_id": "u-from-api",
                "name": "Name From API",
                "email": first.email,
                "role": api_role,
                "location_ids": [],
                "brand_ids": [],
            },
            "/orders": [],
            "/approvals": [],
            "/cases": [],
            "/meta/categories": CATEGORIES,
        },
    )
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["role"] == api_role
    assert at.session_state["name"] == "Name From API"
    assert at.session_state["user_id"] == "u-from-api"
    login = next(kw for _, path, kw in seen if path == "/auth/login")
    assert login["json"]["password"] == get_settings().demo_password


def test_customer_view_shows_orders_in_rupees_and_api_message(monkeypatch):
    fake_api(
        monkeypatch,
        {
            "/orders": [ORDER],
            "/orders/o1": {**ORDER, "items": []},
            "/cases": [CASE],
            "/meta/categories": CATEGORIES,
        },
    )
    at = logged_in("customer")
    assert not at.exception
    assert "₹1,234.50" in at.selectbox[0].options[0]
    assert at.selectbox[1].options == ["Late delivery", "Missing items"]  # from the API
    assert any(CASE["message"] in m.value for m in at.markdown)
    assert any("₹349.00" in c.value for c in at.caption)


def test_customer_cases_fall_back_to_session_when_list_endpoint_missing(monkeypatch):
    fake_api(monkeypatch, {"/orders": [], "/cases/c1": CASE})  # GET /cases -> 404
    at = logged_in("customer", my_cases=["c1"])
    assert not at.exception
    assert any(CASE["message"] in m.value for m in at.markdown)


def test_staff_view_lists_pending_approvals(monkeypatch):
    fake_api(monkeypatch, {"/approvals": [PENDING], "/cases": []})
    at = logged_in("hq_owner")
    assert not at.exception
    assert {b.label for b in at.button} >= {"Approve", "Reject"}


@pytest.mark.parametrize("role", ["customer", "hq_owner"])
def test_expired_token_on_case_list_ends_session_and_shows_login(monkeypatch, role):
    fake_api(
        monkeypatch,
        {
            "/orders": [],
            "/approvals": [],
            "/meta/categories": CATEGORIES,
            "/cases": Unauthorized(401, "token expired"),
        },
    )
    at = logged_in(role)
    assert not at.exception
    assert "token" not in at.session_state and "role" not in at.session_state
    assert [b.label for b in at.button] == ["Log in"]
    assert any("session has ended" in w.value for w in at.warning)
    assert not at.error  # a 401 is not reported as an API error


def test_free_text_mode_lets_a_customer_skip_the_category(monkeypatch):
    seen = fake_api(
        monkeypatch,
        {
            "/orders": [ORDER],
            "/orders/o1": {**ORDER, "items": []},
            "/cases": [],
            "POST /cases": {**CASE, "category": None, "stage": "investigating"},
            "/meta/categories": {**CATEGORIES, "free_text": True},
        },
    )
    at = logged_in("customer")
    assert at.selectbox[1].options[0] == "Not sure: just describe it"
    at.text_area[0].input("My coffee was cold.")
    at.button[0].click().run()
    assert not at.exception
    post = next(kw for method, path, kw in seen if (method, path) == ("POST", "/cases"))
    assert post["json"]["category"] is None
