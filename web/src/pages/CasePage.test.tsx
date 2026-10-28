import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Case, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const base: Case = {
  id: "c-1",
  transaction_id: "t-1",
  order_ref: "O0000042",
  category: "late_delivery",
  stage: "awaiting_approval",
  message: "We've proposed a refund. A member of staff is reviewing it.",
  action: "refund",
  amount_paise: 12000,
  proposal_id: "p-1",
  created_at: "2026-10-25T10:00:00Z",
};

const order = {
  id: "t-1",
  external_ref: "O0000042",
  brand_id: "b-1",
  location_id: "l-1",
  brand_name: "Zesty Bowls",
  location_name: "Indiranagar",
  placed_at: "2026-10-25T09:00:00Z",
  total_paise: 45000,
  status: "delivered",
  promised_at: "2026-10-25T09:40:00Z",
  completed_at: "2026-10-25T10:05:00Z",
  items: [
    { sku: "a", name: "Chicken biryani", quantity: 2, quantity_fulfilled: 1, total_paise: 30000 },
    { sku: "b", name: "Raita", quantity: 1, quantity_fulfilled: 1, total_paise: 15000 },
  ],
};

const said: Case = {
  ...base,
  customer_messages: [
    { at: "2026-10-25T10:00:00Z", text: "One biryani was missing." },
    { at: "2026-10-25T10:20:00Z", text: "It was the chicken one." },
  ],
};

function setup(role: Role, kase: Case | (() => Case), timeline: { status?: number; body?: unknown } = { body: [] }) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /cases/c-1": typeof kase === "function" ? () => ({ body: kase() }) : { body: kase },
    "GET /cases/c-1/timeline": timeline,
    "GET /orders/t-1": { body: order },
    "POST /cases/c-1/messages": { status: 201, body: base },
    "POST /cases/c-1/rerun-ai": { status: 202, body: { status: "started" } },
    "GET /cases/c-1/events": { body: [{ occurred_at: "2026-10-25T10:00:01Z", actor_type: "system", event: "case.opened", payload: { a: 1 } }] },
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("case page", () => {
  it("shows the API message, the proposed remedy and the timeline", async () => {
    setup("customer", base, {
      body: [{ at: "2026-10-25T10:00:00Z", stage: "received", title: "We got your report", text: "Thanks for telling us." }],
    });
    renderApp("/cases/c-1");
    expect(await screen.findByText(base.message)).toBeInTheDocument();
    expect(screen.getByText("Proposed remedy")).toBeInTheDocument();
    expect(screen.getByText("₹120.00")).toBeInTheDocument();
    expect(await screen.findByText("We got your report")).toBeInTheDocument();
    expect(screen.queryByText(/Audit trail/)).not.toBeInTheDocument();
  });

  it("shows only the stepper when the timeline endpoint is absent", async () => {
    setup("customer", base, { status: 404, body: { detail: "Not Found" } });
    renderApp("/cases/c-1");
    expect(await screen.findByText(base.message)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Case progress" })).toBeInTheDocument();
    await screen.findByText("Case details");
    expect(screen.queryByRole("heading", { name: "Timeline" })).not.toBeInTheDocument();
  });

  it("shows a reply box only while awaiting info, posts the reply and refreshes", async () => {
    let stage = "awaiting_info";
    const { calls } = setup("customer", () => ({ ...base, stage, action: null, amount_paise: null }));
    renderApp("/cases/c-1");
    const box = await screen.findByLabelText("Your reply");
    const user = userEvent.setup();
    await user.type(box, "The large fries.");
    stage = "investigating";
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    await screen.findByText(/Updating automatically/);
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/cases/c-1/messages");
    expect(post?.body).toEqual({ message: "The large fries." });
    expect(screen.queryByLabelText("Your reply")).not.toBeInTheDocument();
  });

  it("has no reply box in other stages", async () => {
    setup("customer", base);
    renderApp("/cases/c-1");
    await screen.findByText(base.message);
    expect(screen.queryByLabelText("Your reply")).not.toBeInTheDocument();
  });

  it("gives staff a collapsible audit trail", async () => {
    setup("hq_owner", base);
    renderApp("/cases/c-1");
    const summary = await screen.findByText(/Audit trail/);
    await userEvent.setup().click(summary);
    expect(await screen.findByText("case.opened")).toBeInTheDocument();
  });

  it("polls every 3 s while investigating and stops when the stage settles", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let stage = "investigating";
    const { calls } = setup("customer", () => ({ ...base, stage, action: null, amount_paise: null }));
    renderApp("/cases/c-1");
    await screen.findByText(/Updating automatically/);
    const caseCalls = () => calls.filter((c) => c.path === "/cases/c-1").length;
    const before = caseCalls();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(caseCalls()).toBe(before + 1);
    stage = "awaiting_approval";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    const settled = caseCalls();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(caseCalls()).toBe(settled);
    expect(screen.queryByText(/Updating automatically/)).not.toBeInTheDocument();
  });

  it("shows staff the order card and the customer's words, apart from the status text", async () => {
    setup("hq_owner", said);
    renderApp("/cases/c-1");
    expect(await screen.findByText("Customer said")).toBeInTheDocument();
    const quotes = screen.getAllByRole("blockquote").map((q) => q.textContent);
    expect(quotes).toEqual(["One biryani was missing.", "It was the chicken one."]);
    expect(await screen.findByRole("heading", { name: "Order" })).toBeInTheDocument();
    expect(screen.getByText("Zesty Bowls")).toBeInTheDocument();
    expect(screen.getByText("Indiranagar")).toBeInTheDocument();
    expect(screen.getByText("Chicken biryani")).toBeInTheDocument();
    expect(screen.getByText("₹450.00")).toBeInTheDocument();
    expect(screen.getByText(said.message)).toBeInTheDocument();
    expect(screen.getByText("Promised by")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
  });

  it("labels the customer's own messages 'You wrote' and shows no order card", async () => {
    const { calls } = setup("customer", said);
    renderApp("/cases/c-1");
    expect(await screen.findByText("You wrote")).toBeInTheDocument();
    expect(screen.queryByText("Customer said")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Order" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/orders/t-1")).toBe(false);
  });

  it("offers staff 'Run the AI again' on an AI-failure escalation, once, with a status line", async () => {
    const stuck = { ...base, stage: "escalated", action: null, amount_paise: null, can_rerun_ai: true };
    const { calls } = setup("hq_owner", stuck);
    renderApp("/cases/c-1");
    const button = await screen.findByRole("button", { name: "Run the AI again" });
    await userEvent.setup().click(button);
    expect(await screen.findByRole("status")).toHaveTextContent("The AI is running again");
    expect(screen.queryByRole("button", { name: "Run the AI again" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST" && c.path === "/cases/c-1/rerun-ai")).toHaveLength(1);
  });

  it("shows no re-run button for other escalations, or to customers", async () => {
    setup("hq_owner", { ...base, stage: "escalated", can_rerun_ai: false });
    const first = renderApp("/cases/c-1");
    await screen.findByText(base.message);
    expect(screen.queryByRole("button", { name: "Run the AI again" })).not.toBeInTheDocument();
    first.unmount();
    setup("customer", { ...base, stage: "escalated", can_rerun_ai: true });
    renderApp("/cases/c-1");
    await screen.findByText(base.message);
    expect(screen.queryByRole("button", { name: "Run the AI again" })).not.toBeInTheDocument();
  });
});
