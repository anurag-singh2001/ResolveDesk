import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Alternatives, PendingApproval } from "../api/types";
import { parseRupeesToPaise } from "../lib/money";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const proposal: PendingApproval = {
  proposal_id: "p-1",
  case_id: "c-1",
  category: "wrong_item",
  action: "free_item_voucher",
  risk: "medium",
  amount_paise: 5000,
  order_ref: "O0000042",
  order_total_paise: 64000,
  reason: "Wrong item.",
  checks: { within_cap: true },
  eligible: true,
  errors: [],
  created_at: new Date(Date.now() - 5 * 60000).toISOString(),
  customer_message: "I got the wrong dish.",
  location_name: "Main Street",
  citations: [],
};

const alternatives: Alternatives = {
  proposal_id: "p-1",
  current_action: "free_item_voucher",
  current_amount_paise: 5000,
  alternatives: [
    { action: "free_item_voucher", min_paise: 1000, max_paise: 30000, step_paise: 100, needs_hq_above_paise: null, you_can_approve_up_to_paise: 30000 },
    { action: "refund", min_paise: 100, max_paise: 32000, step_paise: 1, needs_hq_above_paise: 30000, you_can_approve_up_to_paise: 30000 },
  ],
};

function setup(routes: Record<string, { status?: number; body?: unknown }> = {}) {
  seedSession();
  const mock = mockFetch({
    "GET /me": { body: makeMe("location_manager") },
    "GET /approvals": { body: [proposal] },
    "GET /approvals/p-1/alternatives": { body: alternatives },
    ...routes,
  });
  renderApp("/approvals/p-1");
  return mock;
}

async function openAndFill(user: ReturnType<typeof userEvent.setup>, remedy: string, amount: string, why = "fairer") {
  await user.click(await screen.findByRole("button", { name: "Switch remedy" }));
  await user.click(await screen.findByRole("radio", { name: new RegExp(remedy) }));
  await user.type(screen.getByLabelText("Amount (₹)"), amount);
  if (why) await user.type(screen.getByLabelText("Why are you switching?"), why);
}

describe("parseRupeesToPaise", () => {
  it("uses integer maths and rejects what is not money", () => {
    expect(parseRupeesToPaise("180.50")).toBe(18050);
    expect(parseRupeesToPaise("0.29")).toBe(29);
    expect(parseRupeesToPaise("7")).toBe(700);
    expect(parseRupeesToPaise("7.5")).toBe(750);
    expect(["", "1.234", "-5", "abc", "1e3", "1,000"].map(parseRupeesToPaise)).toEqual([null, null, null, null, null, null]);
  });
});

describe("switch remedy", () => {
  it("is an outline action that loads the allowed remedies and ranges only when opened", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    const btn = await screen.findByRole("button", { name: "Switch remedy" });
    expect(calls.some((c) => c.path.endsWith("/alternatives"))).toBe(false);
    await user.click(btn);
    expect(await screen.findByText(/Between ₹10.00 and ₹300.00/)).toBeInTheDocument();
    expect(screen.getByText(/Between ₹1.00 and ₹320.00; above ₹300.00 needs HQ/)).toBeInTheDocument();
  });

  it("checks the range before the confirm step", async () => {
    const { calls } = setup();
    const user = userEvent.setup();
    await openAndFill(user, "Refund", "400");
    await user.click(screen.getByRole("button", { name: "Review switch" }));
    expect(screen.getByText("The amount must be between ₹1.00 and ₹320.00.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confirm switch" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/switch"))).toBe(false);
  });

  it("asks for a reason", async () => {
    setup();
    const user = userEvent.setup();
    await openAndFill(user, "Refund", "100", "");
    await user.click(screen.getByRole("button", { name: "Review switch" }));
    expect(screen.getByText(/Say why you are switching/)).toBeInTheDocument();
  });

  it("confirms with Cancel focused first, then sends integer paise and the reason", async () => {
    const { calls } = setup({
      "POST /approvals/p-1/switch": {
        body: { old_proposal_id: "p-1", proposal_id: "p-2", action: "refund", amount_paise: 18050, decision: null, waiting_for: null, expires_at: null, execution: "none" },
      },
    });
    const user = userEvent.setup();
    await openAndFill(user, "Refund", "180.50", "customer was charged twice");
    await user.click(screen.getByRole("button", { name: "Review switch" }));
    const group = screen.getByRole("group", { name: "Confirm switch" });
    expect(group).toHaveTextContent("Replace free item voucher of ₹50.00 with refund of ₹180.50");
    expect(group.querySelector("button")).toHaveFocus();
    expect(group.querySelector("button")).toHaveTextContent("Cancel");
    await user.click(screen.getByRole("button", { name: "Yes, switch" }));
    expect(await screen.findByText("Remedy switched.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the new proposal" })).toHaveAttribute("href", "/approvals/p-2");
    const sent = calls.find((c) => c.path === "/approvals/p-1/switch")!;
    expect(sent.body).toEqual({ action: "refund", amount_paise: 18050, approve: false, note: "customer was charged twice" });
  });

  it("does not ask to approve over the caller's limit; the server is told approve=false", async () => {
    const { calls } = setup({
      "POST /approvals/p-1/switch": {
        body: { old_proposal_id: "p-1", proposal_id: "p-2", action: "refund", amount_paise: 31000, decision: null, waiting_for: "hq_owner", expires_at: null, execution: "none" },
      },
    });
    const user = userEvent.setup();
    await openAndFill(user, "Refund", "310");
    await user.click(screen.getByLabelText("Approve it now as well"));
    expect(screen.getByText(/over your approval limit/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review switch" }));
    await user.click(screen.getByRole("button", { name: "Yes, switch" }));
    expect(await screen.findByText(/waits for a senior approver/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/approvals/p-1/switch")!.body).toMatchObject({ approve: false });
  });

  it("approves in the same step within the limit", async () => {
    const { calls } = setup({
      "POST /approvals/p-1/switch": {
        body: { old_proposal_id: "p-1", proposal_id: "p-2", action: "free_item_voucher", amount_paise: 9000, decision: "approved", waiting_for: null, expires_at: "2999-01-01T00:00:00Z", execution: "queued" },
      },
    });
    const user = userEvent.setup();
    await openAndFill(user, "Free item voucher", "90");
    await user.click(screen.getByLabelText("Approve it now as well"));
    await user.click(screen.getByRole("button", { name: "Review switch" }));
    expect(screen.getByRole("group", { name: "Confirm switch" })).toHaveTextContent("and approve it");
    await user.click(screen.getByRole("button", { name: "Yes, switch" }));
    expect(await screen.findByText(/It is approved\./)).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/approvals/p-1/switch")!.body).toMatchObject({ approve: true, amount_paise: 9000 });
  });

  it("explains a conflict and shows server rule errors", async () => {
    setup({ "POST /approvals/p-1/switch": { status: 409, body: { detail: "no longer pending" } } });
    const user = userEvent.setup();
    await openAndFill(user, "Refund", "100");
    await user.click(screen.getByRole("button", { name: "Review switch" }));
    await user.click(screen.getByRole("button", { name: "Yes, switch" }));
    expect(await screen.findByText("Someone has already decided or switched this proposal.")).toBeInTheDocument();
  });

  it("shows a message when no other remedy is allowed", async () => {
    setup({ "GET /approvals/p-1/alternatives": { body: { ...alternatives, alternatives: [] } } });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Switch remedy" }));
    expect(await screen.findByText("No other remedy is allowed for this case.")).toBeInTheDocument();
  });
});
