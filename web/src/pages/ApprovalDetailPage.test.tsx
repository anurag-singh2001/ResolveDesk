import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { PendingApproval } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const proposal: PendingApproval = {
  proposal_id: "p-1",
  case_id: "c-1",
  category: "missing_items",
  action: "refund",
  risk: "high",
  amount_paise: 18050,
  order_ref: "O0000042",
  order_total_paise: 64000,
  reason: "One item on record was not fulfilled.",
  checks: { within_cap: true, order_belongs_to_customer: true, needs_hq: false },
  eligible: true,
  errors: [],
  created_at: new Date(Date.now() - 5 * 60000).toISOString(),
  customer_message: "My fries never came.",
  location_name: "Main Street",
  citations: [{ section_ref: "missing_items_v2#1.2", doc_key: "missing_items", version: 2 }],
};

function setup(decision: { status?: number; body?: unknown }, p: PendingApproval = proposal) {
  seedSession();
  const mock = mockFetch({
    "GET /me": { body: makeMe("location_manager") },
    "GET /approvals": { body: [p] },
    "POST /approvals/p-1/decision": decision,
  });
  renderApp("/approvals/p-1");
  return mock;
}

async function approve(note?: string) {
  const user = userEvent.setup();
  await screen.findByText("My fries never came.");
  if (note) await user.type(screen.getByLabelText("Note (optional)"), note);
  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(screen.getByRole("group", { name: "Confirm decision" })).toHaveTextContent("₹180.50");
  await user.click(screen.getByRole("button", { name: "Yes, approve" }));
}

describe("approval detail", () => {
  it("shows the evidence: message, checks, citations and amounts", async () => {
    setup({ body: {} });
    expect(await screen.findByText("My fries never came.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Checks" })).toHaveTextContent("Within cap");
    expect(screen.getByRole("list", { name: "Policy citations" })).toHaveTextContent("missing_items_v2#1.2 · v2");
    expect(screen.getByText("₹640.00")).toBeInTheDocument();
  });

  it("approves after confirmation and sends the note", async () => {
    const { calls } = setup({
      body: { proposal_id: "p-1", decision: "approved", expires_at: "2999-01-01T00:00:00Z", execution: "queued" },
    });
    await approve("checked with kitchen");
    expect(await screen.findByText("Approved.")).toBeInTheDocument();
    expect(screen.getByText(/only once the provider confirms/)).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ decision: "approved", note: "checked with kitchen" });
  });

  it("rejects with a null note when none is given", async () => {
    const { calls } = setup({
      body: { proposal_id: "p-1", decision: "rejected", expires_at: "2999-01-01T00:00:00Z", execution: "none" },
    });
    const user = userEvent.setup();
    await screen.findByText("My fries never came.");
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject" }));
    expect(await screen.findByText("Rejected.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ decision: "rejected", note: null });
  });

  it("explains a 403 as needing a senior approver", async () => {
    setup({ status: 403, body: { detail: "amount above the escalation limit needs an hq_owner" } });
    await approve();
    expect(await screen.findByRole("alert")).toHaveTextContent("needs a senior approver");
  });

  it("explains a 409 as already decided and hides the buttons", async () => {
    setup({ status: 409, body: { detail: "already decided" } });
    await approve();
    expect(await screen.findByText("Someone has already decided this proposal.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("disables Approve when the checks failed but allows Reject", async () => {
    setup({ body: {} }, { ...proposal, eligible: false, errors: ["amount exceeds cap"], checks: { within_cap: false } });
    await screen.findByText("My fries never came.");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    expect(screen.getByText("amount exceeds cap")).toBeInTheDocument();
  });
});
