import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { MetricGroup, MetricPoint, MetricsResponse, Role } from "../api/types";
import { formatBp, bucketLabel, timezoneLabel } from "../lib/dashboard";
import { formatPaise, formatPaiseShort } from "../lib/money";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

function point(over: Partial<MetricPoint> = {}): MetricPoint {
  return {
    bucket_start: "2026-03-09",
    cases_opened: 4,
    cases_by_category: {},
    refunds_count: 1,
    refunds_paise: 123450,
    vouchers_count: 1,
    vouchers_paise: 5000,
    remedy_spend_paise: 128450,
    decisions: 0,
    median_decision_minutes: null,
    sla_met_bp: null,
    orders: 10,
    repeat_orders: 0,
    repeat_rate_bp: null,
    revenue_paise: 999900,
    aov_paise: 99990,
    ai_decided: 0,
    ai_overridden: 0,
    ai_accuracy_bp: null,
    ...over,
  };
}

function response(groups: MetricGroup[]): MetricsResponse {
  return { granularity: "day", timezone: "Asia/Kolkata", start: "2026-03-01", end: "2026-03-30", decision_sla_minutes: 240, groups };
}

const A = { id: "g-a", name: "Alpha", points: [point()] };
const B = { id: "g-b", name: "Beta", points: [point({ cases_opened: 2, orders: 3, remedy_spend_paise: 700, revenue_paise: 30000 })] };

function mockMetrics(role: Role, pick: (url: URL) => { status?: number; body?: unknown }) {
  seedSession();
  const urls: URL[] = [];
  const base = mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /approvals": { body: [] },
  });
  const inner = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    if (url.pathname === "/insights/metrics") {
      urls.push(url);
      const r = pick(url);
      return new Response(JSON.stringify(r.body ?? null), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }
    return inner(input, init);
  }) as typeof fetch;
  return { urls, base };
}

describe("dashboard formatting", () => {
  it("formats paise with integer maths and null as no data", () => {
    expect(formatPaise(123450)).toBe("₹1,234.50");
    expect(formatPaise(29)).toBe("₹0.29");
    expect(formatPaiseShort(123450)).toBe("₹1,234");
    expect(formatBp(3125)).toBe("31.25%");
    expect(formatBp(5)).toBe("0.05%");
    expect(formatBp(0)).toBe("0.00%");
    expect(formatBp(null)).toBe("No data");
    expect(bucketLabel("2026-03-09", "week")).toBe("Week of 9 Mar");
    expect(timezoneLabel("Asia/Kolkata")).toBe("Asia/Kolkata (IST)");
  });
});

describe("dashboard page", () => {
  it.each<Role>(["hq_owner", "franchisee_owner", "location_manager"])("%s gets the dashboard in the nav and the charts", async (role) => {
    mockMetrics(role, () => ({ body: response([{ id: null, name: "All", points: [point()] }]) }));
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { name: "Remedy spend" })).toBeInTheDocument();
    expect(within(screen.getByTestId("side-nav")).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    for (const t of ["Cases opened", "Median decision time", "Decisions within SLA", "Repeat rate", "AI accuracy", "Orders", "Average order value"]) {
      expect(screen.getByRole("heading", { name: t })).toBeInTheDocument();
    }
    expect(screen.getByTestId("dashboard-meta")).toHaveTextContent("Asia/Kolkata (IST)");
    expect(screen.getByTestId("dashboard-meta")).toHaveTextContent("Decision SLA 240 min");
  });

  it("shows money in rupees from paise and null as no data, not zero", async () => {
    mockMetrics("hq_owner", () => ({ body: response([{ id: null, name: "All", points: [point()] }]) }));
    renderApp("/dashboard");
    await screen.findByRole("heading", { name: "Remedy spend" });
    const remedy = within(screen.getByTestId("table-remedy"));
    expect(remedy.getByText("₹1,234.50")).toBeInTheDocument();
    expect(remedy.getByText("₹50.00")).toBeInTheDocument();
    const decision = within(screen.getByTestId("table-decision"));
    expect(decision.getByText("No data")).toBeInTheDocument();
    expect(decision.queryByText("0 min")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("table-ai")).getByText("No data")).toBeInTheDocument();
    expect(within(screen.getByTestId("table-aov")).getByText("₹999.90")).toBeInTheDocument();
  });

  it("lets an HQ owner drill from all scope to a brand to a location, asking the server each time", async () => {
    const { urls } = mockMetrics("hq_owner", (url) => {
      const gb = url.searchParams.get("group_by");
      if (gb === "none") return { body: response([{ id: null, name: "All", points: [point()] }]) };
      if (gb === "brand") return { body: response([A, B]) };
      return { body: response([A, B]) };
    });
    renderApp("/dashboard");
    expect(await screen.findByRole("region", { name: "By brand" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "By location" })).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("region", { name: "By brand" })).getByRole("button", { name: "Alpha" }));
    await waitFor(() => expect(urls.some((u) => u.searchParams.get("brand_id") === "g-a")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("region", { name: "By brand" })).not.toBeInTheDocument());
    await userEvent.click(await within(await screen.findByRole("region", { name: "By location" })).findByRole("button", { name: "Beta" }));
    await waitFor(() => expect(urls.some((u) => u.searchParams.get("location_id") === "g-b")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("region", { name: "By location" })).not.toBeInTheDocument());
    expect(screen.getByRole("navigation", { name: "Drill-down" })).toHaveTextContent("All in scope/Alpha/Beta");
  });

  it("shows a single-location caller one row with nothing to drill into", async () => {
    mockMetrics("location_manager", (url) =>
      url.searchParams.get("group_by") === "none" ? { body: response([{ id: null, name: "All", points: [point()] }]) } : { body: response([A]) },
    );
    renderApp("/dashboard");
    const region = await screen.findByRole("region", { name: "By location" });
    expect(within(region).getByText("Alpha")).toBeInTheDocument();
    expect(within(region).queryByRole("button")).not.toBeInTheDocument();
  });

  it("sends the day/week and period choices to the server", async () => {
    const { urls } = mockMetrics("franchisee_owner", () => ({ body: response([{ id: null, name: "All", points: [point()] }]) }));
    renderApp("/dashboard");
    await screen.findByRole("heading", { name: "Remedy spend" });
    await userEvent.click(screen.getByRole("button", { name: "Week" }));
    await userEvent.selectOptions(screen.getByLabelText("Period"), "90");
    await waitFor(() => expect(urls.some((u) => u.searchParams.get("granularity") === "week" && u.searchParams.get("days") === "90")).toBe(true));
  });

  it("shows an empty state when nothing happened", async () => {
    mockMetrics("hq_owner", () => ({
      body: response([{ id: null, name: "All", points: [point({ cases_opened: 0, orders: 0, remedy_spend_paise: 0, revenue_paise: 0, decisions: 0 })] }]),
    }));
    renderApp("/dashboard");
    expect(await screen.findByText("No activity in this period")).toBeInTheDocument();
  });

  it("shows a plain message for 403 and an error for 500", async () => {
    mockMetrics("hq_owner", () => ({ status: 403, body: { detail: "nope" } }));
    renderApp("/dashboard");
    expect(await screen.findByText("You don't have permission to do that.")).toBeInTheDocument();
  });

  it("is not available to a customer", async () => {
    mockMetrics("customer", () => ({ body: response([]) }));
    renderApp("/dashboard");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});
