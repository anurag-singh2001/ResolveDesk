"""Thin HTTP client for the ResolveDesk API. The UI holds no business logic: every decision
(eligibility, amounts, status text) comes from the API; this only moves JSON."""

import os
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8000"


class ApiError(Exception):
    """Any non-2xx answer. `detail` is the API's own explanation."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class Unauthorized(ApiError):  # 401: not logged in / token expired
    pass


class Forbidden(ApiError):  # 403: wrong role
    pass


class NotFound(ApiError):  # 404: absent, out of scope, or another tenant's
    pass


class Conflict(ApiError):  # 409: e.g. already decided
    pass


class Unprocessable(ApiError):  # 422: validation / not eligible
    pass


_ERRORS: dict[int, type[ApiError]] = {
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    422: Unprocessable,
}


def _detail(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    return body.get("detail", body) if isinstance(body, dict) else body


class ApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.token = token
        self._http = httpx.Client(
            base_url=base_url or os.environ.get("API_URL", DEFAULT_API_URL),
            transport=transport,
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.is_success:
            return response.json() if response.content else None
        raise _ERRORS.get(response.status_code, ApiError)(response.status_code, _detail(response))

    # auth
    def login(self, tenant: str, email: str, password: str) -> str:
        body = {"tenant": tenant, "email": email, "password": password}
        self.token = self._request("POST", "/auth/login", json=body)["access_token"]
        return self.token

    def me(self) -> dict:
        return self._request("GET", "/me")

    # tenant metadata
    def categories(self) -> list[str]:
        """The caller's tenant issue categories (from its vertical pack, via the API)."""
        return self._request("GET", "/meta/categories")["categories"]

    # orders
    def list_orders(self, limit: int = 20) -> list[dict]:
        return self._request("GET", "/orders", params={"limit": limit})

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/orders/{order_id}")

    # cases
    def create_case(self, transaction_id: str, category: str, message: str) -> dict:
        body = {"transaction_id": transaction_id, "category": category, "message": message}
        return self._request("POST", "/cases", json=body)

    def get_case(self, case_id: str) -> dict:
        return self._request("GET", f"/cases/{case_id}")

    def list_cases(self, limit: int = 50) -> list[dict]:
        return self._request("GET", "/cases", params={"limit": limit})

    def case_events(self, case_id: str) -> list[dict]:
        return self._request("GET", f"/cases/{case_id}/events")

    # approvals
    def pending_approvals(self, limit: int = 100) -> list[dict]:
        return self._request("GET", "/approvals", params={"limit": limit})

    def decide(self, proposal_id: str, decision: str, note: str | None = None) -> dict:
        body = {"decision": decision, "note": note or None}
        return self._request("POST", f"/approvals/{proposal_id}/decision", json=body)

    def reconcile(self, proposal_id: str) -> dict:
        return self._request("POST", f"/approvals/{proposal_id}/reconcile")
