import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const mix = {
  whatsapp: { campaigns: 0, budget_cap_paise: 0, treatment_sends: 0, succeeded_sends: 0, note: "" },
  manual_spend: [] as unknown[],
  manual_spend_note: "entered by hand, not verified",
};

function setup(role: Role) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role, { growth_enabled: true }) },
    "GET /approvals": { body: [] },
    "GET /cases/queue": { body: [] },
    "GET /growth/signals": { body: [] },
    "GET /locations": { body: [] },
    "GET /growth/channel-mix": { body: mix },
    "POST /growth/spend": {
      status: 201,
      body: { id: "m-1", channel: "aggregator_ads", amount_paise: 150050, period_start: "2026-10-01", period_end: "2026-10-31", verification: "x" },
    },
  });
}

async function fill(user: ReturnType<typeof userEvent.setup>, amount: string) {
  const box = await screen.findByLabelText("Amount (₹)");
  if (amount) await user.type(box, amount);
  await user.type(screen.getByLabelText("From"), "2026-10-01");
  await user.type(screen.getByLabelText("To"), "2026-10-31");
  await user.click(screen.getByRole("button", { name: "Save spend" }));
}

describe("manual spend form", () => {
  it("sends the rupee amount as integer paise", async () => {
    const { calls } = setup("hq_owner");
    renderApp("/growth");
    await fill(userEvent.setup(), "1500.50");
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/growth/spend")).toBe(true));
    const body = calls.find((c) => c.path === "/growth/spend")?.body as Record<string, unknown>;
    expect(body.amount_paise).toBe(150050);
    expect(Number.isInteger(body.amount_paise)).toBe(true);
    expect(await screen.findByText(/Saved/)).toBeInTheDocument();
  });

  it.each(["-5", "0", "abc", "10.555", ""])("rejects %j with a message and sends nothing", async (bad) => {
    const { calls } = setup("hq_owner");
    renderApp("/growth");
    await fill(userEvent.setup(), bad);
    expect(await screen.findByText(/Enter an amount in rupees above zero/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("is not offered to anyone but HQ", async () => {
    setup("location_manager");
    renderApp("/growth");
    await screen.findByText("No signals right now");
    expect(screen.queryByText("Add spend by hand")).not.toBeInTheDocument();
  });
});
