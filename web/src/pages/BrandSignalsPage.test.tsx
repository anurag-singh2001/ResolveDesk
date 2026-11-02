import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BrandSignal, BrandSignalsResponse, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

function brand(over: Partial<BrandSignal> = {}): BrandSignal {
  return {
    brand_id: "b-1",
    name: "Alpha",
    status: "steady",
    baseline_orders: 120,
    recent_orders: 90,
    min_orders: 30,
    baseline_bp: 5000,
    recent_bp: 4900,
    drop_bp: 100,
    diagnosis: null,
    ...over,
  };
}

function res(brands: BrandSignal[]): BrandSignalsResponse {
  return {
    as_of: "2026-03-30T00:00:00Z",
    recent_start: "2026-03-09T00:00:00Z",
    baseline_start: "2026-02-09T00:00:00Z",
    definition: "A customer who orders from two brands counts as a repeat within each brand separately.",
    brands,
  };
}

function open(role: Role, body: BrandSignalsResponse) {
  seedSession();
  mockFetch({
    "GET /me": { body: makeMe(role, { growth_enabled: true }) },
    "GET /approvals": { body: [] },
    "GET /growth/brand-signals": { body },
  });
  renderApp("/growth/brands");
}

describe("brand signals page", () => {
  it("shows a dropping brand with findings and possible reasons, and a steady one", async () => {
    open(
      "hq_owner",
      res([
        brand({ name: "Alpha", status: "drop", baseline_bp: 5000, recent_bp: 3000, drop_bp: 2000, diagnosis: { findings: ["Tickets in 'late' went from 1 to 4."], hypotheses: ["A win-back offer may help."] } }),
        brand({ brand_id: "b-2", name: "Beta" }),
      ]),
    );
    expect(await screen.findByRole("heading", { name: "Alpha" })).toBeInTheDocument();
    expect(screen.getByText("Repeat rate dropped")).toBeInTheDocument();
    expect(screen.getByText("Steady")).toBeInTheDocument();
    expect(screen.getByText("Tickets in 'late' went from 1 to 4.")).toBeInTheDocument();
    expect(screen.getByText(/Possible reasons \(not confirmed\)/)).toBeInTheDocument();
    expect(screen.getByTestId("definition")).toHaveTextContent("within each brand separately");
    expect(screen.getByRole("link", { name: "segment view" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /campaign/i })).toBeNull();
  });

  it("shows low volume instead of a trend and leaves the brand out of the chart", async () => {
    open("hq_owner", res([brand({ status: "low_volume", baseline_orders: 8, recent_orders: 5, baseline_bp: null, recent_bp: null, drop_bp: null })]));
    expect(await screen.findByText(/Low volume: fewer than 30 orders/)).toBeInTheDocument();
    expect(screen.getAllByText("Low volume").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("chart-brand-repeat")).toBeNull();
    expect(screen.queryByText("Drop")).toBeNull();
  });

  it("charts brands that have enough orders, with a table view", async () => {
    open("hq_owner", res([brand()]));
    const chart = await screen.findByTestId("chart-brand-repeat");
    expect(chart).toBeInTheDocument();
    expect(within(screen.getByTestId("table-brand-repeat")).getByText("50.00%")).toBeInTheDocument();
  });

  it.each<Role>(["franchisee_owner", "location_manager"])("%s has no brand signals page or nav link", async (role) => {
    open(role, res([brand()]));
    expect(await screen.findByTestId("side-nav")).toBeInTheDocument();
    expect(within(screen.getByTestId("side-nav")).queryByRole("link", { name: "Brand signals" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Alpha" })).toBeNull();
  });
});
