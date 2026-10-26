import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Campaign, GrowthSignal, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const signal: GrowthSignal = {
  id: "s-1",
  location_id: "l-1",
  metric: "repeat_rate",
  baseline_bp: 4000,
  recent_bp: 2500,
  baseline_n: 300,
  recent_n: 120,
  drop_bp: 1500,
  status: "open",
  diagnosis: { findings: ["Tickets in 'late_delivery' went from 2 to 9."], hypotheses: ["Service problems may be pushing regulars away."] },
  diagnosis_source: "template",
  recent_end: "2026-10-01T00:00:00Z",
  campaign_id: null,
};

const campaign: Campaign = {
  id: "c-1",
  signal_id: "s-1",
  location_id: "l-1",
  status: "pending_approval",
  payload_hash: "a".repeat(64),
  params: {},
  budget_paise: 250000,
  expires_at: "2999-01-01T00:00:00Z",
  sent_at: null,
  treatment_n: 45,
  holdout_n: 5,
  approvals: [{ decided_by: "u-9", role: "franchisee_owner", decision: "approved", expires_at: "2999-01-01T00:00:00Z" }],
  fully_approved: false,
  playbook: null,
};

function setup(role: Role, growth: boolean, extra: Record<string, { status?: number; body?: unknown }> = {}) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role, { growth_enabled: growth }) },
    "GET /approvals": { body: [] },
    "GET /orders": { body: [] },
    "GET /locations": { body: [{ id: "l-1", slug: "main", name: "Main Street" }] },
    "GET /growth/signals": { body: [signal] },
    ...extra,
  });
}

describe("growth page", () => {
  it.each<Role>(["location_manager", "franchisee_owner", "hq_owner"])("staff (%s) see Growth when the flag is on", async (role) => {
    setup(role, true);
    renderApp("/growth");
    expect(await screen.findByText("Main Street: repeat customers down")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Growth" }).length).toBeGreaterThan(0);
  });

  it("hides Growth when the tenant's flag is off", async () => {
    const { calls } = setup("hq_owner", false);
    renderApp("/growth");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Growth" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith("/growth"))).toBe(false);
  });

  it("hides Growth from customers even with the flag on", async () => {
    setup("customer", true);
    renderApp("/growth");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });

  it("proposes a campaign and shows audience, holdout, budget and approvals so far", async () => {
    const { calls } = setup("hq_owner", true, {
      "POST /growth/signals/s-1/campaign": { status: 201, body: campaign },
      "GET /growth/campaigns/c-1": { body: campaign },
    });
    renderApp("/growth");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Propose win-back campaign" }));
    expect(await screen.findByText("45 customers")).toBeInTheDocument();
    expect(screen.getByText("5 customers")).toBeInTheDocument();
    expect(screen.getByText("₹2,500.00")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2: Franchisee owner/)).toBeInTheDocument();
    expect(screen.getByText(/two different approvers, and at least one must be an HQ owner/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/growth/signals/s-1/campaign")).toBe(true);
  });

  it("shows the server's error when the approval is refused", async () => {
    setup("hq_owner", true, {
      "GET /growth/signals": { body: [{ ...signal, campaign_id: "c-1" }] },
      "GET /growth/campaigns/c-1": { body: campaign },
      "POST /growth/campaigns/c-1/approve": { status: 422, body: { detail: "you already approved this campaign" } },
    });
    renderApp("/growth");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Approve campaign" }));
    expect(await screen.findByText("you already approved this campaign")).toBeInTheDocument();
  });

  it("shows the updated campaign after an approval", async () => {
    setup("hq_owner", true, {
      "GET /growth/signals": { body: [{ ...signal, campaign_id: "c-1" }] },
      "GET /growth/campaigns/c-1": { body: campaign },
      "POST /growth/campaigns/c-1/approve": {
        body: { ...campaign, status: "approved", fully_approved: true, approvals: [...campaign.approvals, { ...campaign.approvals[0], role: "hq_owner" }] },
      },
    });
    renderApp("/growth");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Approve campaign" }));
    expect(await screen.findByText(/2 of 2/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve campaign" })).not.toBeInTheDocument();
  });

  it("shows the verdict and playbook lesson", async () => {
    const done: Campaign = {
      ...campaign,
      status: "approved",
      sent_at: "2026-10-05T00:00:00Z",
      playbook: { verdict: "worked", uplift_bp: 800, treatment_n: 45, holdout_n: 5, confidence_note: "Small holdout; treat as a hint.", lesson: "Win-back offers helped at this outlet." },
    };
    setup("hq_owner", true, {
      "GET /growth/signals": { body: [{ ...signal, campaign_id: "c-1" }] },
      "GET /growth/campaigns/c-1": { body: done },
    });
    renderApp("/growth");
    expect(await screen.findByTestId("playbook")).toHaveTextContent("Verdict: Worked");
    expect(screen.getByText("Win-back offers helped at this outlet.")).toBeInTheDocument();
  });

  it("refreshes signals (HQ only)", async () => {
    const { calls } = setup("hq_owner", true, { "POST /growth/signals/refresh": { body: [{ ...signal, id: "s-2" }] } });
    renderApp("/growth");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Refresh signals" }));
    expect(calls.some((c) => c.path === "/growth/signals/refresh")).toBe(true);
  });
});
