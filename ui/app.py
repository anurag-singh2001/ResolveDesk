"""ResolveDesk demo UI (thin first cut of PROJECT.md section 13).

Talks only to the HTTP API. The tenant YAML files are read for one thing: the dev login
picker (which demo users exist). Who is logged in (name, role) comes from `GET /me`, and
everything shown about orders, categories, cases and approvals is what the API returned;
the UI decides nothing.
"""

import sys
from pathlib import Path

# `streamlit run ui/app.py` puts ui/ on sys.path, not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from app.config import get_settings
from app.core.money import format_inr
from app.core.tenant_config import TenantConfig, load_tenant, tenant_dirs
from ui.api_client import ApiClient, ApiError, NotFound, Unauthorized

SESSION_ENDED = "Your session has ended. Please log in again."
STAFF_ROLES = {"location_manager", "franchisee_owner", "hq_owner"}
HAPPY_PATH = ["received", "investigating", "awaiting_approval", "processing", "confirmed"]
LABELS = {
    "received": "Received",
    "investigating": "Investigating",
    "awaiting_approval": "Awaiting approval",
    "processing": "Processing",
    "confirmed": "Confirmed",
    "declined": "Declined",
    "escalated": "Escalated to a person",
    "awaiting_info": "We need more information",
    "closed": "Closed",
}


def money(paise: int | None) -> str:
    return "-" if paise is None else format_inr(paise)


NOT_SURE = "Not sure: just describe it"


def label(slug: str | None) -> str:
    return (slug or "-").replace("_", " ").capitalize()


def category_label(slug: str | None) -> str:
    return NOT_SURE if slug is None else label(slug)


@st.cache_data
def tenants() -> dict[str, TenantConfig]:
    return {d.name: load_tenant(d) for d in tenant_dirs()}


def client() -> ApiClient:
    return ApiClient(token=st.session_state.get("token"))


def end_session() -> None:
    """401 (expired or revoked token): forget everything and go back to the login screen."""
    st.session_state.clear()
    st.session_state["notice"] = SESSION_ENDED
    st.rerun()


def call(fn, *args, **kwargs):
    """Run an API call; show the API's own error and return None on failure."""
    try:
        return fn(*args, **kwargs)
    except Unauthorized:
        end_session()
    except ApiError as exc:
        st.error(f"{exc.status_code}: {exc.detail}")
    except Exception as exc:  # API down, timeout: say so plainly
        st.error(f"Could not reach the API: {exc}")
    return None


# --- login ---------------------------------------------------------------------------


def login_view() -> None:
    st.title("ResolveDesk demo")
    if notice := st.session_state.pop("notice", None):
        st.warning(notice)
    all_tenants = tenants()
    slug = st.selectbox("Business", list(all_tenants), format_func=lambda s: all_tenants[s].name)
    users = all_tenants[slug].users
    user = st.selectbox(
        "Demo user", users, format_func=lambda u: f"{u.name} ({label(u.role)}) - {u.email}"
    )
    if st.button("Log in", type="primary") and user is not None:
        # The picker only chooses whom to log in as; who we are comes from the API.
        api = ApiClient()
        if call(api.login, slug, user.email, get_settings().demo_password) is None:
            return
        me = call(api.me)
        if me is None:
            return
        st.session_state.update(
            token=api.token,
            tenant=slug,
            user_id=str(me["user_id"]),
            role=me["role"],
            name=me["name"],
            my_cases=[],
        )
        st.rerun()


# --- customer -----------------------------------------------------------------------


def status_bar(stage: str) -> None:
    if stage in HAPPY_PATH:
        current = HAPPY_PATH.index(stage)
        steps = []
        for i, s in enumerate(HAPPY_PATH):
            text = LABELS[s]
            steps.append(
                f"**[{text}]**" if i == current else (f"~~{text}~~" if i < current else text)
            )
        st.markdown(" → ".join(steps))
        st.progress((current + 1) / len(HAPPY_PATH))
    elif stage == "declined":
        st.error(LABELS[stage])
    elif stage == "escalated":
        st.warning(LABELS[stage])
    else:
        st.info(LABELS.get(stage, label(stage)))


def case_card(case: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{label(case.get('category'))}** · case `{str(case['id'])[:8]}`")
        status_bar(case["stage"])
        st.write(case["message"])  # the API's honest, customer-safe text, shown verbatim
        if case.get("amount_paise") is not None:
            st.caption(f"{label(case.get('action'))}: {money(case['amount_paise'])}")


def remember_case(case_id: str) -> None:
    mine = st.session_state.setdefault("my_cases", [])
    if case_id not in mine:
        mine.insert(0, case_id)


def load_cases(api: ApiClient) -> list[dict]:
    """GET /cases if the API has it; otherwise the cases opened in this browser session."""
    try:
        return api.list_cases()
    except Unauthorized:
        end_session()
    except NotFound:
        pass
    except ApiError as exc:
        if exc.status_code != 405:
            st.error(f"{exc.status_code}: {exc.detail}")
            return []
    cases = (call(api.get_case, cid) for cid in st.session_state.get("my_cases", []))
    return [c for c in cases if c]


def customer_view() -> None:
    api = client()
    st.header("Report a problem")
    orders = call(api.list_orders, 20) or []
    if not orders:
        st.info("No orders found.")
    else:
        order = st.selectbox(
            "Order",
            orders,
            format_func=lambda o: (
                f"{o['external_ref']} · {o['placed_at'][:16].replace('T', ' ')}"
                f" · {money(o['total_paise'])}"
            ),
        )
        detail = call(api.get_order, order["id"])
        if detail:
            st.table(
                [
                    {
                        "Item": i["name"],
                        "Ordered": i["quantity"],
                        "Received": i["quantity_fulfilled"],
                        "Total": money(i["total_paise"]),
                    }
                    for i in detail["items"]
                ]
            )
        # Fetched once per login (cleared on logout); a failed fetch is retried next rerun.
        opts = st.session_state.get("issue_options") or call(api.issue_options) or {}
        if opts:
            st.session_state["issue_options"] = opts
        # In agents mode the assistant works out the category from the description.
        cats = ([None] if opts.get("free_text") else []) + list(opts.get("categories", []))
        with st.form("report", clear_on_submit=True):
            category = st.selectbox("What went wrong?", cats, format_func=category_label)
            message = st.text_area("Tell us more", max_chars=2000)
            if st.form_submit_button("Report a problem", type="primary"):
                if not message.strip():
                    st.warning("Please describe the problem.")
                else:
                    case = call(api.create_case, order["id"], category, message.strip())
                    if case:
                        remember_case(str(case["id"]))
                        st.success("Thanks, we've got it.")
                        case_card(case)

    st.header("My cases")
    if st.button("Refresh"):
        st.rerun()
    cases = load_cases(api)
    if not cases:
        st.caption("No cases yet.")
    for case in cases:
        case_card(case)


# --- staff --------------------------------------------------------------------------


def approval_row(api: ApiClient, p: dict) -> None:
    pid = str(p["proposal_id"])
    decided = st.session_state.setdefault("decisions", {})
    title = (
        f"{label(p['action'])} {money(p['amount_paise'])} · order {p['order_ref'] or '-'}"
        f" · risk {p['risk']} · {'eligible' if p['eligible'] else 'NOT eligible'}"
    )
    with st.expander(title, expanded=pid not in decided):
        st.write(f"**Reason:** {p['reason']}")
        st.write(f"Category: {label(p['category'])} · Order total: {money(p['order_total_paise'])}")
        st.write("**Eligibility checks**")
        st.json(p["checks"], expanded=False)
        if p["errors"]:
            st.error("Blocked: " + "; ".join(p["errors"]))
        if pid in decided:
            st.success(f"Decision recorded; execution: {decided[pid]}")
            return
        note = st.text_input("Note (optional)", key=f"note-{pid}", max_chars=500)
        approve, reject = st.columns(2)
        decision = None
        if approve.button("Approve", key=f"ok-{pid}", disabled=not p["eligible"]):
            decision = "approved"
        if reject.button("Reject", key=f"no-{pid}"):
            decision = "rejected"
        if decision:
            out = call(api.decide, pid, decision, note)
            if out:
                decided[pid] = out["execution"]
                st.rerun()
        timeline(api, str(p["case_id"]), "approval")


def reconcile_button(api: ApiClient, case: dict, where: str) -> None:
    """Offered for a refund the API reports as still processing (e.g. provider timeout)."""
    stuck = case["stage"] == "processing" and case.get("action") == "refund"
    if not (stuck and case.get("proposal_id")):
        return
    clicked = st.button("Reconcile refund", key=f"rec-{where}-{case['id']}")
    if clicked and call(api.reconcile, case["proposal_id"]) is not None:
        st.success("Reconcile queued. Refresh in a moment.")


def timeline(api: ApiClient, case_id: str, where: str) -> None:
    if st.toggle("Show case timeline", key=f"tl-{where}-{case_id}"):
        events = call(api.case_events, case_id) or []
        for e in events:
            st.markdown(
                f"`{e['occurred_at'][:19].replace('T', ' ')}` **{e['event']}** ({e['actor_type']})"
            )
            if e["payload"]:
                st.json(e["payload"], expanded=False)


def staff_view() -> None:
    api = client()
    st.header("Pending approvals")
    if st.button("Refresh"):
        st.rerun()
    pending = call(api.pending_approvals) or []
    if not pending:
        st.caption("Nothing waiting for you.")
    else:
        st.dataframe(
            [
                {
                    "Order": p["order_ref"],
                    "Action": label(p["action"]),
                    "Amount": money(p["amount_paise"]),
                    "Risk": p["risk"],
                    "Eligible": "yes" if p["eligible"] else "no",
                    "Reason": p["reason"],
                }
                for p in pending
            ],
            hide_index=True,
        )
    for p in pending:
        approval_row(api, p)

    st.header("Cases")
    try:
        cases = api.list_cases()
    except Unauthorized:
        end_session()
    except ApiError:
        cases = None
        st.caption("Case list isn't available from the API yet; look a case up by id.")
    if cases:
        for case in cases:
            with st.expander(f"{label(case['category'])} · {LABELS.get(case['stage'], '?')}"):
                case_card(case)
                reconcile_button(api, case, "list")
                timeline(api, str(case["id"]), "list")
    with st.expander("Look up a case / reconcile by id"):
        case_id = st.text_input("Case id").strip()
        if case_id:
            case = call(api.get_case, case_id)
            if case:
                case_card(case)
                reconcile_button(api, case, "lookup")
                timeline(api, case_id, "lookup")


# --- shell --------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="ResolveDesk", layout="wide")
    if "token" not in st.session_state:
        login_view()
        return
    cfg = tenants()[st.session_state["tenant"]]
    with st.sidebar:
        st.write(f"**{cfg.name}**")
        st.write(f"{st.session_state['name']} · {label(st.session_state['role'])}")
        if st.button("Log out"):
            st.session_state.clear()
            st.rerun()
    if st.session_state["role"] in STAFF_ROLES:
        staff_view()
    else:
        customer_view()


main()
