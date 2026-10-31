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

  it("links each citation to its policy section and says which rule set the amount", async () => {
    setup(
      { body: {} },
      {
        ...proposal,
        basis: ["The voucher is sized to the order total.", "The voucher is capped at ₹150.00 by the voucher limit."],
        sources: [
          { doc_key: "late_delivery_v3", version: 3, document_title: "Late delivery policy", section_id: "2.1", href: "/policies#late_delivery_v3-2.1", section_changed: false, note: null },
          { doc_key: "refunds_v1", version: 1, document_title: "Refund policy", section_id: null, href: "/policies#refunds_v1", section_changed: true, note: "This section has changed since the decision; the document is linked instead." },
        ],
      },
    );
    await screen.findByText("My fries never came.");
    expect(screen.getByTestId("remedy-basis")).toHaveTextContent("capped at ₹150.00");
    const link = screen.getByRole("link", { name: "Late delivery policy, section 2.1" });
    expect(link).toHaveAttribute("href", "/policies#late_delivery_v3-2.1");
    expect(screen.getByRole("link", { name: "Refund policy" })).toHaveAttribute("href", "/policies#refunds_v1");
    expect(screen.getByText(/section has changed since the decision/)).toBeInTheDocument();
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

  it("shows a failed fair-use check as an amber warning, not a red failure", async () => {
    setup({ body: {} }, {
      ...proposal,
      checks: { within_cap: true, fair_use_ok: false, fair_use_grants_30d: 3, fair_use_max_grants_30d: 3 },
    });
    const warning = await screen.findByTestId("fair-use-warning");
    expect(warning).toHaveTextContent("Repeat claimant: 3 grants in 30 days (limit 3). A person must decide.");
    const list = screen.getByRole("list", { name: "Checks" });
    expect(list).not.toHaveTextContent("failed");
    expect(list).not.toHaveTextContent("✗");
  });

  it("shows no fair-use warning when fair use is fine", async () => {
    setup({ body: {} }, {
      ...proposal,
      checks: { within_cap: true, fair_use_ok: true, fair_use_grants_30d: 0, fair_use_max_grants_30d: 3 },
    });
    const list = await screen.findByRole("list", { name: "Checks" });
    expect(screen.queryByTestId("fair-use-warning")).toBeNull();
    expect(list).toHaveTextContent("Fair use ok");
  });

  it("shows amounts, counts and needs_* flags as values, not as passed/failed", async () => {
    setup({ body: {} }, {
      ...proposal,
      checks: { within_cap: true, amount_paise: 24450, fair_use_grants_30d: 0, needs_hq: false },
    });
    const details = await screen.findByRole("list", { name: "Checks" });
    expect(details).toHaveTextContent("Within cap");
    expect(details).not.toHaveTextContent("Amount");
    const facts = screen.getByLabelText("Details");
    expect(facts).toHaveTextContent("₹244.50");
    expect(facts).toHaveTextContent("Fair use grants 30d");
    expect(facts).toHaveTextContent("0");
    expect(facts).toHaveTextContent("No");
  });

  it("disables Approve when the checks failed but allows Reject", async () => {
    setup({ body: {} }, { ...proposal, eligible: false, errors: ["amount exceeds cap"], checks: { within_cap: false } });
    await screen.findByText("My fries never came.");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    expect(screen.getByText("amount exceeds cap")).toBeInTheDocument();
  });

  it("shows the plain basis line only, never the engineer wording of the stored reason", async () => {
    setup({ body: {} }, {
      ...proposal,
      reason: "deterministic rule: customer chose a 50% refund",
      basis: ["The customer chose a 50% refund."],
    });
    expect(await screen.findByTestId("remedy-basis")).toHaveTextContent("The customer chose a 50% refund.");
    expect(screen.queryByText(/deterministic rule/i)).toBeNull();
  });

  it("strips the engineer prefix when there is no basis line", async () => {
    setup({ body: {} }, { ...proposal, reason: "deterministic rule: customer chose a 50% refund", basis: [] });
    expect(await screen.findByText("Customer chose a 50% refund")).toBeInTheDocument();
    expect(screen.queryByText(/deterministic rule/i)).toBeNull();
  });

  it("removes Approve, Reject and Switch remedy once a decision is made", async () => {
    setup({ body: { proposal_id: "p-1", decision: "approved", expires_at: "2026-01-01T00:00:00Z", execution: "queued" } });
    await screen.findByRole("button", { name: "Switch remedy" });
    await approve();
    expect(await screen.findByText("Approved.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Switch remedy" })).toBeNull();
  });

  it("warns when a pending voucher is worth more than its order", async () => {
    setup({ body: {} }, {
      ...proposal,
      action: "free_item_voucher",
      amount_paise: 15000,
      order_total_paise: 14900,
      eligible: false,
      errors: ["voucher exceeds what the customer paid for the order"],
      checks: { value_paise: 15000, order_total_paise: 14900 },
    });
    const warning = await screen.findByTestId("over-total-warning");
    expect(warning).toHaveTextContent("more than the order total");
    expect(warning).toHaveTextContent("₹150.00");
    expect(warning).toHaveTextContent("₹149.00");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  });
});
