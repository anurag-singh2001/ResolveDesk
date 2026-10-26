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

function setup(role: Role, kase: Case | (() => Case), timeline: { status?: number; body?: unknown } = { body: [] }) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /cases/c-1": typeof kase === "function" ? () => ({ body: kase() }) : { body: kase },
    "GET /cases/c-1/timeline": timeline,
    "POST /cases/c-1/messages": { status: 201, body: base },
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
});
