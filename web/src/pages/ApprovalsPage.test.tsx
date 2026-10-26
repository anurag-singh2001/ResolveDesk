import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { PendingApproval } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const pending: PendingApproval = {
  proposal_id: "p-1",
  case_id: "c-1",
  category: "missing_items",
  action: "refund",
  risk: "low",
  amount_paise: 123450,
  order_ref: "ORD-1",
  order_total_paise: 500000,
  reason: "Item missing",
  checks: {},
  eligible: true,
  errors: [],
  created_at: "2026-01-01T10:00:00Z",
  customer_message: null,
  location_name: "Main Street",
  citations: [],
};

const locations = [
  { id: "l-1", slug: "main", name: "Main Street" },
  { id: "l-2", slug: "lake", name: "Lake Road" },
];

function setup(approvals: PendingApproval[] = [pending]) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe("hq_owner") },
    "GET /locations": { body: locations },
    "GET /approvals": { body: approvals },
  });
}

const queueUrls = (fn: ReturnType<typeof setup>["fn"]) =>
  fn.mock.calls.map((c) => new URL(String(c[0]))).filter((u) => u.pathname === "/approvals");

describe("approvals filter bar", () => {
  it("changing a filter re-requests the queue with the matching query", async () => {
    const { fn } = setup();
    renderApp("/approvals");
    expect((await screen.findAllByText("₹1,234.50")).length).toBeGreaterThan(0);
    expect(queueUrls(fn)[0].searchParams.get("sort")).toBeNull(); // default is oldest

    await userEvent.selectOptions(await screen.findByLabelText("Outlet"), "l-2");
    await waitFor(() => expect(queueUrls(fn).at(-1)!.searchParams.get("location_id")).toBe("l-2"));
    await userEvent.selectOptions(screen.getByLabelText("Action"), "free_item_voucher");
    await waitFor(() => expect(queueUrls(fn).at(-1)!.searchParams.get("action")).toBe("free_item_voucher"));
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "amount_desc");
    await waitFor(() => {
      const last = queueUrls(fn).at(-1)!.searchParams;
      expect(last.get("sort")).toBe("amount_desc");
      expect(last.get("location_id")).toBe("l-2"); // earlier filters are kept
    });
  });

  it("restores the filters from the URL, which is what a reload does", async () => {
    const { fn } = setup();
    renderApp("/approvals?location_id=l-1&action=refund&sort=newest");
    expect(await screen.findByLabelText("Outlet")).toHaveValue("l-1");
    expect(screen.getByLabelText("Action")).toHaveValue("refund");
    expect(screen.getByLabelText("Sort")).toHaveValue("newest");
    const first = queueUrls(fn)[0].searchParams;
    expect([first.get("location_id"), first.get("action"), first.get("sort")]).toEqual(["l-1", "refund", "newest"]);
  });

  it("says so when the filters match nothing", async () => {
    setup([]);
    renderApp("/approvals?action=refund");
    expect(await screen.findByText("No approvals match these filters")).toBeInTheDocument();
  });
});
