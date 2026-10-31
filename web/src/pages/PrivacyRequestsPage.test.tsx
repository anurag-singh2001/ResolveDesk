import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { PrivacyDryRun, PrivacyQueue, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const queue: PrivacyQueue = {
  target_days: 30,
  truncated: false,
  items: [
    {
      id: "r-1",
      kind: "erasure",
      customer_ref: "C0****42",
      status: "pending_approval",
      stage: "received",
      received_at: "2026-10-01T10:00:00Z",
      target_at: "2026-10-31T10:00:00Z",
      days_left: 4,
      overdue: false,
      deferred_until: null,
      reason_code: null,
      reason: null,
    },
    {
      id: "r-2",
      kind: "erasure",
      customer_ref: "C0****77",
      status: "deferred",
      stage: "deferred",
      received_at: "2026-09-01T10:00:00Z",
      target_at: "2026-10-01T10:00:00Z",
      days_left: -3,
      overdue: true,
      deferred_until: null,
      reason_code: "open_case",
      reason: "You have a case that is still being handled.",
    },
  ],
};

const dry: PrivacyDryRun = {
  request_id: "r-1",
  status: "pending_approval",
  remove: { messages: 3, name: 1, contact_fields: 2, profile_fields: 0, login: 1, marketing_consents: 1 },
  keep: { orders: 5, refund_operations: 1, cases: 2, tickets: 2, proposals: 1, approvals: 1, executions: 1, consent_history: 2, completion_contact: 1 },
  deferred: null,
  payload_hash: "h".repeat(64),
  approval_token: "1.tok",
  expires_at: "2026-10-27T11:00:00Z",
};

function setup(role: Role = "hq_owner", approve: { status?: number; body?: unknown } = { body: {} }) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /data-requests/queue": { body: queue },
    "GET /data-requests/r-1/dry-run": { body: dry },
    "POST /data-requests/r-1/approve": approve,
  });
}

describe("privacy requests queue", () => {
  it("lists open requests with stage, dates, time left, overdue and why deferred", async () => {
    setup();
    renderApp("/privacy-requests");
    expect(await screen.findByRole("heading", { name: "Privacy requests" })).toBeInTheDocument();
    expect(await screen.findByText("C0****42")).toBeInTheDocument();
    expect(screen.getByText("4 days left")).toBeInTheDocument();
    expect(screen.getByText("3 days late")).toBeInTheDocument();
    expect(screen.getByText("You have a case that is still being handled.")).toBeInTheDocument();
    expect(screen.getByText("Deferred")).toBeInTheDocument();
  });

  it("is not shown to roles other than the HQ owner", async () => {
    setup("location_manager");
    renderApp("/privacy-requests");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });

  it("shows counts, asks to confirm with Cancel focused, and sends the bound approval", async () => {
    const { calls } = setup();
    renderApp("/privacy-requests");
    const user = userEvent.setup();
    await user.click((await screen.findAllByRole("button", { name: "Review" }))[0]);
    expect(await screen.findByText("Will be removed")).toBeInTheDocument();
    expect(screen.getByText("Will be kept")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve erasure" }));
    const dialog = await screen.findByTestId("pq-confirm");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: /Erase now/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/data-requests/r-1/approve")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ payload_hash: dry.payload_hash, approval_token: dry.approval_token });
  });

  it("says so when the data changed since the review and offers to review again", async () => {
    setup("hq_owner", { status: 409, body: { detail: "the request or the customer's data changed since you reviewed it; review again" } });
    renderApp("/privacy-requests");
    const user = userEvent.setup();
    await user.click((await screen.findAllByRole("button", { name: "Review" }))[0]);
    await user.click(await screen.findByRole("button", { name: "Approve erasure" }));
    await user.click(within(await screen.findByTestId("pq-confirm")).getByRole("button", { name: /Erase now/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/changed since you reviewed/);
    expect(screen.getByRole("button", { name: "Review again" })).toBeInTheDocument();
  });

  it("shows the held completion contact and says when the list is cut short", async () => {
    seedSession();
    mockFetch({
      "GET /me": { body: makeMe("hq_owner") },
      "GET /data-requests/queue": { body: { ...queue, truncated: true } },
      "GET /data-requests/r-1/dry-run": { body: dry },
    });
    renderApp("/privacy-requests");
    const user = userEvent.setup();
    expect(await screen.findByText(/More are waiting/)).toBeInTheDocument();
    await user.click((await screen.findAllByRole("button", { name: "Review" }))[0]);
    expect(await screen.findByText(/held for the completion message/)).toBeInTheDocument();
  });

  it("uses no em dashes", () => {
    expect(JSON.stringify([queue, dry])).not.toContain("—");
  });
});
