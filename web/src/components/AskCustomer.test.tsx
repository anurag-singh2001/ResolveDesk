import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AskSuggestion, CustomerOffer as Offer, PendingApproval } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";
import { CustomerOffer } from "./CustomerOffer";

const proposal: PendingApproval = {
  proposal_id: "p-1",
  case_id: "c-1",
  category: "wrong_item",
  action: "free_item_voucher",
  risk: "medium",
  amount_paise: 5000,
  order_ref: "O0000042",
  order_total_paise: 14900,
  reason: "Wrong item.",
  checks: { within_cap: true },
  eligible: true,
  errors: [],
  created_at: new Date(Date.now() - 5 * 60000).toISOString(),
  customer_message: "I got the wrong dish.",
  location_name: "Main Street",
  citations: [],
};

const suggestion: AskSuggestion = {
  proposal_id: "p-1",
  can_ask: true,
  blocked_reason: null,
  answer_days: 3,
  options: [
    { code: "voucher_14900", action: "free_item_voucher", amount_paise: 14900 },
    { code: "refund_7450", action: "refund", amount_paise: 7450 },
  ],
};

function setup(pending: PendingApproval = proposal, routes: Record<string, { status?: number; body?: unknown }> = {}) {
  seedSession();
  const mock = mockFetch({
    "GET /me": { body: makeMe("hq_owner") },
    "GET /approvals": { body: [pending] },
    "GET /approvals/p-1/ask-customer": { body: suggestion },
    ...routes,
  });
  renderApp("/approvals/p-1");
  return mock;
}

describe("ask the customer (staff)", () => {
  it("is an outline action that loads the allowed options only when opened", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    const btn = await screen.findByRole("button", { name: "Ask the customer" });
    expect(calls.some((c) => c.path.endsWith("/ask-customer"))).toBe(false);
    await user.click(btn);
    expect(await screen.findByText("Up to ₹149.00 (the most the rules allow).")).toBeInTheDocument();
    expect(screen.getByText("Up to ₹74.50 (the most the rules allow).")).toBeInTheDocument();
    expect(screen.getByLabelText("Free item voucher (₹)")).toHaveValue("149");
    expect(screen.getByLabelText("Refund (₹)")).toHaveValue("74.50");
  });

  it("checks the amounts before the confirm step", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Ask the customer" }));
    const refund = await screen.findByLabelText("Refund (₹)");
    await user.clear(refund);
    await user.type(refund, "80");
    await user.click(screen.getByRole("button", { name: "Review question" }));
    expect(screen.getByText("The most you can offer as refund is ₹74.50.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confirm question" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("confirms with Cancel focused first, then sends integer paise", async () => {
    const { calls } = setup(proposal, {
      "POST /approvals/p-1/ask-customer": { body: { proposal_id: "p-1", expires_at: "2026-11-03T10:00:00Z", options: suggestion.options } },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Ask the customer" }));
    await screen.findByLabelText("Refund (₹)");
    await user.click(screen.getByRole("button", { name: "Review question" }));
    const group = screen.getByRole("group", { name: "Confirm question" });
    expect(group).toHaveTextContent("free item voucher of ₹149.00 and refund of ₹74.50");
    expect(group.querySelector("button")).toHaveFocus();
    expect(group.querySelector("button")).toHaveTextContent("Cancel");
    await user.click(screen.getByRole("button", { name: "Yes, ask the customer" }));
    expect(await screen.findByText("Waiting for the customer.")).toBeInTheDocument();
    const sent = calls.find((c) => c.method === "POST" && c.path === "/approvals/p-1/ask-customer")!;
    expect(sent.body).toEqual({
      options: [
        { action: "free_item_voucher", amount_paise: 14900 },
        { action: "refund", amount_paise: 7450 },
      ],
    });
  });

  it("explains why asking is not allowed and sends nothing", async () => {
    const { calls } = setup(proposal, {
      "GET /approvals/p-1/ask-customer": {
        body: { ...suggestion, can_ask: false, options: [], blocked_reason: "An allergy, illness or foreign-object report goes straight to a manager." },
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Ask the customer" }));
    expect(await screen.findByText(/goes straight to a manager/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review question" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows 'Waiting for the customer', disables Approve and hides the switch while the question is open", async () => {
    setup({
      ...proposal,
      offer: {
        state: "open",
        asked_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 3 * 86400000).toISOString(),
        options: [
          { code: "voucher_14900", kind: "voucher", amount_paise: 14900 },
          { code: "refund_7450", kind: "refund", amount_paise: 7450 },
        ],
      },
    });
    expect(await screen.findByRole("heading", { name: "Waiting for the customer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Switch remedy" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ask the customer" })).not.toBeInTheDocument();
  });

  it("lets a person decide once the question has timed out", async () => {
    setup({ ...proposal, offer: { state: "expired", asked_at: "2026-10-20T10:00:00Z", expires_at: "2026-10-23T10:00:00Z", options: [] } });
    expect(await screen.findByText("The customer did not answer.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });
});

describe("the customer's question", () => {
  const open: Offer = {
    state: "open",
    heading: "Please choose an option",
    intro: "Our team has two options for you. This is a choice, not a promise: pick the one you prefer, and a team member will review it before anything is decided.",
    expires_note: "Please answer within 3 days. If we do not hear from you, a team member will still look at your case.",
    status_text: "We are waiting for your choice between two options.",
    options: [
      { code: "voucher_14900", kind: "voucher", title: "Voucher", summary: "A voucher worth ₹149.00 for a future order.", amount_paise: 14900, approval: "team", timing: "After a team member approves it." },
      { code: "refund_7450", kind: "refund", title: "Ask for a refund", summary: "You can ask for a partial refund of up to ₹74.50; a team member decides.", amount_paise: 7450, approval: "team", timing: "After a team member approves it." },
    ],
  };

  it("shows the server's text and options and sends only the option code", async () => {
    seedSession();
    const chosen: Offer = { ...open, state: "chosen", options: [], status_text: "Thank you. We have your choice. A team member will review it. Nothing is decided yet." };
    const { calls } = mockFetch({
      "GET /cases/c-1/offer": { body: open },
      "PUT /cases/c-1/offer-choice": { body: chosen },
    });
    render(<CustomerOffer caseId="c-1" />);
    const user = userEvent.setup();
    expect(await screen.findByText(/This is a choice, not a promise/)).toBeInTheDocument();
    expect(screen.getByText(/Please answer within 3 days/)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Ask for a refund/));
    await user.click(screen.getByRole("button", { name: "Send my choice" }));
    expect(await screen.findByText(/Nothing is decided yet/)).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ option: "refund_7450" });
  });

  it("shows nothing when there is no question", async () => {
    seedSession();
    mockFetch({ "GET /cases/c-1/offer": { body: { ...open, state: "none", options: [], heading: "", intro: "", expires_note: "", status_text: "" } } });
    const { container } = render(<CustomerOffer caseId="c-1" />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});
