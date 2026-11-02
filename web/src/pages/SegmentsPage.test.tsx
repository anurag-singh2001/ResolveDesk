import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import type { CohortsResponse, Role, SegmentCell, SegmentsResponse } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

// The lazy chart chunk is large: a slow first import under load used to fail a test's wait.
beforeAll(async () => {
  await import("./SegmentsPage");
}, 60000);

const SEGMENTS = ["new", "active", "loyal", "at_risk", "lapsed", "lapsed_regular", "one_and_done"];

function cell(segment: string, over: Partial<SegmentCell> = {}): SegmentCell {
  return {
    segment,
    suppressed: false,
    in_segment: 40,
    share_bp: 2500,
    orders: 80,
    total_spend_paise: 1234500,
    aov_paise: 15431,
    contactable_whatsapp: 12,
    own_channel: 30,
    aggregator_only: 10,
    aggregator_only_not_contactable: 7,
    ...over,
  };
}

const hidden = (segment: string): SegmentCell => ({
  segment,
  suppressed: true,
  in_segment: null,
  share_bp: null,
  orders: null,
  total_spend_paise: null,
  aov_paise: null,
  contactable_whatsapp: null,
  own_channel: null,
  aggregator_only: null,
  aggregator_only_not_contactable: null,
});

function segmentsBody(over: Partial<SegmentsResponse> = {}, cells = SEGMENTS.map((s) => cell(s))): SegmentsResponse {
  return {
    as_of: "2026-03-30T00:00:00+05:30",
    lapsed_days: 28,
    new_days: 30,
    small_cell_min: 10,
    cells_hidden_below_min: false,
    groups: [
      { id: null, name: "All brands", customers: 160, segments: cells },
      { id: "b1", name: "Brand One", customers: 90, segments: SEGMENTS.map((s) => cell(s, { in_segment: 11 })) },
    ],
    ...over,
  };
}

function cohortsBody(): CohortsResponse {
  const row = (month: string, size: number | null, suppressed = false) => ({
    cohort_month: month,
    suppressed,
    size,
    cells: suppressed
      ? []
      : [
          { month: 1, measurable: true, returned: 5, return_bp: 2500 },
          { month: 2, measurable: true, returned: 3, return_bp: 1500 },
          { month: 3, measurable: false, returned: null, return_bp: null },
        ],
  });
  return {
    as_of: "2026-03-30T00:00:00+05:30",
    small_cell_min: 10,
    cells_hidden_below_min: true,
    groups: [
      { id: null, name: "All brands", cohorts: [row("2026-01-01", 20), row("2026-02-01", null, true)] },
      { id: "b1", name: "Brand One", cohorts: [row("2026-01-01", 12)] },
    ],
  };
}

function open(role: Role, seg: SegmentsResponse, coh = cohortsBody()) {
  seedSession();
  mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /approvals": { body: [] },
    "GET /insights/segments": { body: seg },
    "GET /insights/cohorts": { body: coh },
  });
  renderApp("/segments");
}

describe("segments page", () => {
  it.each<Role>(["hq_owner", "franchisee_owner", "location_manager"])("%s sees the segments, the chart and the cohort table", async (role) => {
    open(role, segmentsBody());
    expect(await screen.findByRole("heading", { name: "Customers by segment" })).toBeInTheDocument();
    expect(within(screen.getByTestId("side-nav")).getByRole("link", { name: "Segments" })).toBeInTheDocument();
    const table = within(screen.getByTestId("segments-table"));
    for (const label of ["New", "Active", "Loyal", "At risk", "Lapsed", "Lapsed regulars", "One-and-done"]) {
      expect(table.getByRole("rowheader", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByTestId("chart-segments")).toBeInTheDocument();
    expect(await screen.findByTestId("cohort-table")).toBeInTheDocument();
  });

  it("shows money in rupees from paise and keeps contactable beside the segment size", async () => {
    open("hq_owner", segmentsBody());
    const row = (await screen.findAllByRole("row")).find((r) => within(r).queryByRole("rowheader", { name: "New" }));
    expect(row).toBeDefined();
    const cells = within(row as HTMLElement).getAllByRole("cell").map((c) => c.textContent);
    expect(cells.slice(0, 5)).toEqual(["40", "25.00%", "₹154.31", "₹12,345.00", "12"]);
  });

  it("shows a hidden cell as hidden, never as zero", async () => {
    open("location_manager", segmentsBody({ cells_hidden_below_min: true }, SEGMENTS.map((s) => (s === "loyal" ? hidden(s) : cell(s)))));
    const table = within(await screen.findByTestId("segments-table"));
    const row = table.getByRole("rowheader", { name: "Loyal" }).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("Hidden: fewer than 10 customers");
    expect(within(row).queryByText("0")).not.toBeInTheDocument();
    expect(screen.getByTestId("segments-meta")).toHaveTextContent("Groups under 10 customers are hidden");
  });

  it("marks cohort months that are not over, and hidden cohorts", async () => {
    open("franchisee_owner", segmentsBody());
    const table = within(await screen.findByTestId("cohort-table"));
    expect(table.getByText("Not yet")).toBeInTheDocument();
    expect(table.getByText("25.00% (5)")).toBeInTheDocument();
    expect(table.getByText("Hidden: fewer than 10 customers")).toBeInTheDocument();
  });

  it("switches brand without another request and the cohort table follows", async () => {
    open("hq_owner", segmentsBody());
    await userEvent.selectOptions(await screen.findByLabelText("Brand"), "b1");
    const row = (await screen.findAllByRole("row")).find((r) => within(r).queryByRole("rowheader", { name: "New" })) as HTMLElement;
    expect(within(row).getAllByRole("cell")[0]).toHaveTextContent("11");
    expect(within(screen.getByTestId("cohort-table")).queryByText("Hidden: fewer than 10 customers")).not.toBeInTheDocument();
  });

  it("says the WhatsApp figure can exceed a real campaign audience", async () => {
    open("hq_owner", segmentsBody());
    expect(await screen.findByTestId("segments-meta")).toHaveTextContent("frequency cap is not applied");
    expect(screen.getByRole("columnheader", { name: /Can be messaged on WhatsApp\*/ })).toHaveAttribute("title", expect.stringContaining("frequency cap"));
  });

  it("copes with a hidden group total", async () => {
    const body = segmentsBody();
    body.groups[0].customers = null;
    open("location_manager", body);
    expect(await screen.findByTestId("segments-meta")).toHaveTextContent("Fewer than 10 customers with orders");
  });

  it("says plainly that counts include people who have not agreed to marketing", async () => {
    open("hq_owner", segmentsBody());
    expect(await screen.findByTestId("segments-meta")).toHaveTextContent("only the WhatsApp column reflects consent");
  });

  it("shows an empty state with no customers", async () => {
    open("hq_owner", segmentsBody({ groups: [{ id: null, name: "All brands", customers: 0, segments: SEGMENTS.map((s) => cell(s)) }] }));
    expect(await screen.findByText("No customers with orders yet")).toBeInTheDocument();
  });

  it("does not show the page to a customer", async () => {
    seedSession();
    mockFetch({ "GET /me": { body: makeMe("customer") }, "GET /orders": { body: [] } });
    renderApp("/segments");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});
