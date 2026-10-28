import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { QueueItem } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const item: QueueItem = {
  case_id: "c-1",
  order_ref: "ORD-1",
  location_name: "Main Street",
  category: "missing_items",
  status: "escalated",
  reason_kind: "escalated",
  reason_code: "other",
  reason: "Needs a manager",
  waiting_since: "2026-01-01T10:00:00Z",
  waiting_seconds: 7200,
  owner_user_id: "u-1",
  owner_name: "Asha Rao",
  owned_by_me: true,
  language: "hi",
  amount_paise: null,
  proposal_id: null,
};

function setup(role: "location_manager" | "customer" = "location_manager") {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /cases/queue": { body: [item] },
    "GET /meta/categories": { body: { categories: ["missing_items"], free_text: false } },
    "GET /approvals": { body: [] },
  });
}

describe("Cases to handle", () => {
  it("shows reason, wait, owner and language, with a count badge in the nav", async () => {
    setup();
    renderApp("/queue");
    expect(await screen.findByText("Needs a manager")).toBeInTheDocument();
    expect(screen.getByText("Asha Rao (you)")).toBeInTheDocument();
    expect(screen.getByText("2 h")).toBeInTheDocument();
    expect(screen.getByText("hi")).toBeInTheDocument();
    const nav = await screen.findByTestId("side-nav");
    await waitFor(() => expect(within(nav).getByText("1")).toBeInTheDocument());
  });

  it("filters are sent to the server", async () => {
    const { fn } = setup();
    renderApp("/queue");
    await screen.findByText("Needs a manager");
    await userEvent.selectOptions(screen.getByLabelText("Reason"), "awaiting_approval");
    await userEvent.click(screen.getByLabelText("Owned by me"));
    await waitFor(() => {
      const urls = fn.mock.calls.map((c) => new URL(String(c[0]))).filter((u) => u.pathname === "/cases/queue");
      const last = urls.at(-1)!.searchParams;
      expect(last.get("reason")).toBe("awaiting_approval");
      expect(last.get("owned_by_me")).toBe("true");
    });
  });

  it("is not shown to a customer", async () => {
    setup("customer");
    renderApp("/queue");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});
