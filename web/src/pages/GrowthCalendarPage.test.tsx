import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CalendarCampaign, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";
import { sendWords } from "./GrowthCalendarPage";

function camp(over: Partial<CalendarCampaign> = {}): CalendarCampaign {
  return {
    id: "c1",
    status: "pending_approval",
    location_id: "l1",
    location_name: "Indiranagar",
    brands: [{ id: "b1", name: "Brand One" }],
    audience_n: 12,
    treatment_n: 10,
    holdout_n: 2,
    budget_paise: 50000,
    start: "2026-03-10T00:00:00Z",
    window_end: "2026-03-24T00:00:00Z",
    window_days: 14,
    send_counts: { pending: 10, submitted: 0, processing: 0, succeeded: 0, failed: 0, unknown: 0, skipped: 0 },
    overlap_customers: 0,
    frequency_cap_customers: 0,
    ...over,
  };
}

function open(role: Role, campaigns: CalendarCampaign[], growth = true) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role, { growth_enabled: growth }) },
    "GET /approvals": { body: [] },
    "GET /growth/calendar": { body: { as_of: "2026-03-01T00:00:00Z", campaigns } },
  });
}

describe("send words", () => {
  it("keeps every send state apart and never says sent", () => {
    const words = sendWords(camp({ send_counts: { pending: 0, submitted: 1, processing: 2, succeeded: 3, failed: 4, unknown: 5, skipped: 0 } }));
    expect(words).toBe("1 submitted · 2 processing · 3 succeeded · 4 failed · 5 unknown");
    expect(words).not.toMatch(/\bsent\b/);
  });
});

describe("campaign calendar page", () => {
  it.each<Role>(["hq_owner", "franchisee_owner", "location_manager"])("%s sees campaigns, status and money in rupees", async (role) => {
    open(role, [camp(), camp({ id: "c2", status: "measured", budget_paise: 123450, location_name: "Koramangala" })]);
    renderApp("/growth/calendar");
    expect(await screen.findByRole("heading", { name: "Campaign calendar" })).toBeInTheDocument();
    const rows = await screen.findAllByTestId("calendar-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Pending approval")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Measured")).toBeInTheDocument();
    expect(within(rows[1]).getByText("₹1,234.50")).toBeInTheDocument();
    expect(within(screen.getByTestId("side-nav")).getByRole("link", { name: "Campaign calendar" })).toBeInTheDocument();
  });

  it("shows warnings as counts without blocking anything, and has no action buttons", async () => {
    open("hq_owner", [camp({ overlap_customers: 3, frequency_cap_customers: 2 })]);
    renderApp("/growth/calendar");
    const row = (await screen.findAllByTestId("calendar-row"))[0];
    expect(within(row).getByText("3 in overlapping campaigns")).toBeInTheDocument();
    expect(within(row).getByText("2 inside the frequency cap")).toBeInTheDocument();
    expect(screen.getByText(/nothing is blocked/)).toBeInTheDocument();
    expect(within(screen.getByRole("main")).queryAllByRole("button")).toHaveLength(0);
  });

  it("shows each send state by its own word", async () => {
    open("hq_owner", [camp({ status: "sent", send_counts: { pending: 0, submitted: 1, processing: 1, succeeded: 5, failed: 2, unknown: 1, skipped: 0 } })]);
    renderApp("/growth/calendar");
    const row = (await screen.findAllByTestId("calendar-row"))[0];
    expect(within(row).getByText("1 submitted · 1 processing · 5 succeeded · 2 failed · 1 unknown")).toBeInTheDocument();
  });

  it("is not offered where the growth flag is off", async () => {
    open("hq_owner", [camp()], false);
    renderApp("/growth/calendar");
    await screen.findByTestId("side-nav");
    expect(screen.queryByRole("heading", { name: "Campaign calendar" })).not.toBeInTheDocument();
  });
});
