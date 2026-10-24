"""Demo UI client: request shapes, bearer auth and error mapping. No network, no DB."""

import json

import httpx
import pytest

from ui.api_client import (
    ApiClient,
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    Unauthorized,
    Unprocessable,
)

CASE = {"id": "c1", "category": "x", "stage": "received", "message": "m"}


def recording_client(respond, token: str | None = "tok"):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    api = ApiClient(base_url="http://api.test", token=token, transport=httpx.MockTransport(handler))
    return api, seen


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_login_posts_credentials_and_keeps_token():
    api, seen = recording_client(
        lambda r: httpx.Response(200, json={"access_token": "new", "token_type": "bearer"}),
        token=None,
    )
    assert api.login("some-tenant", "a@b.test", "demo") == "new"
    assert seen[0].method == "POST" and seen[0].url.path == "/auth/login"
    assert body(seen[0]) == {"tenant": "some-tenant", "email": "a@b.test", "password": "demo"}
    assert "authorization" not in seen[0].headers

    api.me()
    assert seen[1].headers["authorization"] == "Bearer new"


@pytest.mark.parametrize(
    "call,method,path,params",
    [
        (lambda a: a.me(), "GET", "/me", {}),
        (lambda a: a.list_orders(5), "GET", "/orders", {"limit": "5"}),
        (lambda a: a.get_order("o1"), "GET", "/orders/o1", {}),
        (lambda a: a.get_case("c1"), "GET", "/cases/c1", {}),
        (lambda a: a.list_cases(7), "GET", "/cases", {"limit": "7"}),
        (lambda a: a.case_events("c1"), "GET", "/cases/c1/events", {}),
        (lambda a: a.pending_approvals(3), "GET", "/approvals", {"limit": "3"}),
        (lambda a: a.reconcile("p1"), "POST", "/approvals/p1/reconcile", {}),
    ],
)
def test_endpoints_send_bearer_and_expected_path(call, method, path, params):
    api, seen = recording_client(lambda r: httpx.Response(200, json={}))
    call(api)
    (req,) = seen
    assert (req.method, req.url.path, dict(req.url.params)) == (method, path, params)
    assert req.headers["authorization"] == "Bearer tok"


def test_create_case_body():
    api, seen = recording_client(lambda r: httpx.Response(201, json=CASE))
    assert api.create_case("t1", "late", "cold food") == CASE
    assert body(seen[0]) == {"transaction_id": "t1", "category": "late", "message": "cold food"}


@pytest.mark.parametrize("note,sent", [("ok by me", "ok by me"), ("", None), (None, None)])
def test_decision_body(note, sent):
    api, seen = recording_client(lambda r: httpx.Response(200, json={"execution": "queued"}))
    assert api.decide("p1", "approved", note) == {"execution": "queued"}
    assert seen[0].url.path == "/approvals/p1/decision"
    assert body(seen[0]) == {"decision": "approved", "note": sent}


@pytest.mark.parametrize(
    "status,error",
    [
        (401, Unauthorized),
        (403, Forbidden),
        (404, NotFound),
        (409, Conflict),
        (422, Unprocessable),
        (405, ApiError),
        (500, ApiError),
    ],
)
def test_errors_map_to_types_with_api_detail(status, error):
    api, _ = recording_client(lambda r: httpx.Response(status, json={"detail": "why"}))
    with pytest.raises(error) as exc:
        api.get_case("c1")
    assert exc.type is error
    assert exc.value.status_code == status and exc.value.detail == "why"


def test_structured_and_non_json_detail():
    api, _ = recording_client(lambda r: httpx.Response(422, json={"detail": ["over limit"]}))
    with pytest.raises(Unprocessable) as exc:
        api.decide("p1", "approved")
    assert exc.value.detail == ["over limit"]

    api, _ = recording_client(lambda r: httpx.Response(502, text="bad gateway"))
    with pytest.raises(ApiError) as exc:
        api.me()
    assert exc.value.detail == "bad gateway"


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("API_URL", "http://elsewhere.test:9000")
    seen: list[httpx.Request] = []
    api = ApiClient(
        transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={}))
    )
    api.me()
    assert str(seen[0].url) == "http://elsewhere.test:9000/me"
