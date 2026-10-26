import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OutletInsight, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const row: OutletInsight = {
  location_id: "l-1",
  name: "Main Street",
  cases_opened: 12,
  refunds_confirmed_count: 3,
  refunds_confirmed_paise: 123450,
  vouchers_issued_count: 0,
  vouchers_issued_paise: 0,
  median_decision_minutes: null,
  orders: 200,
  repeat_rate_bp: 3125,
};

function setup(role: Role) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /approvals": { body: [] },
    "GET /orders": { body: [] },
    "GET /insights/outlets": { body: [row] },
  });
}

describe("insights page", () => {
  it.each<Role>(["hq_owner", "franchisee_owner"])("%s sees the nav item and the metrics in rupees", async (role) => {
    setup(role);
    renderApp("/insights");
    const table = await screen.findByRole("table");
    expect(within(screen.getByTestId("side-nav")).getByRole("link", { name: "Insights" })).toBeInTheDocument();
    expect(within(table).getByText("Main Street")).toBeInTheDocument();
    expect(within(table).getByText("₹1,234.50")).toBeInTheDocument();
    expect(within(table).getByText("31.2%")).toBeInTheDocument();
    expect(within(table).getByText("—")).toBeInTheDocument(); // no decisions yet
  });

  it.each<Role>(["location_manager", "customer"])("%s has no nav item and gets page not found", async (role) => {
    const { calls } = setup(role);
    renderApp("/insights");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Insights" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/insights/outlets")).toBe(false);
  });
});
