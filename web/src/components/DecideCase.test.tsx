import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Case, Role, StaffRemedyOptions } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const escalated: Case = {
  id: "c-1",
  transaction_id: "t-1",
  order_ref: "O0000042",
  category: null,
  stage: "needs_review",
  message: "A person is looking at this.",
  action: null,
  amount_paise: null,
  proposal_id: null,
  created_at: "2026-10-25T10:00:00Z",
};

const uncategorised: StaffRemedyOptions = {
  categories: ["missing_items", "wrong_item"],
  category: null,
  options: [],
  note: "Choose a category first.",
};
const categorised: StaffRemedyOptions = {
  categories: ["missing_items", "wrong_item"],
  category: "missing_items",
  options: [{ action: "refund", min_paise: 1, max_paise: 12000 }],
  note: null,
};

function setup(role: Role, options: { status?: number; body?: unknown }) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /cases/c-1": { body: escalated },
    "GET /cases/c-1/timeline": { body: [] },
    "GET /cases/c-1/staff-remedy-options": options,
    "GET /orders/t-1": { status: 404, body: { detail: "not found" } },
    "POST /cases/c-1/categorise": { body: categorised },
    "POST /cases/c-1/propose": {
      status: 201,
      body: { proposal_id: "p-1", case_id: "c-1", action: "refund", amount_paise: 12050, created: true, auto_approved: false, status: "awaiting_approval", needs_hq: false },
    },
  });
}

describe("decide this case", () => {
  it("lets staff categorise, then shows the allowed range and proposes in integer paise", async () => {
    const { calls } = setup("location_manager", { body: uncategorised });
    renderApp("/cases/c-1");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Category"), "missing_items");
    expect(calls.find((c) => c.path === "/cases/c-1/categorise")?.body).toEqual({ category: "missing_items" });
    expect(await screen.findByText(/Allowed: ₹0\.01 to ₹120\.00/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("Amount (₹)"), "120.50");
    await user.click(screen.getByRole("button", { name: "Propose for approval" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Refund of ₹120.50 is awaiting approval.");
    expect(calls.find((c) => c.path === "/cases/c-1/propose")?.body).toEqual({ action: "refund", amount_paise: 12050 });
  });

  it("does not send an amount that is not rupees and paise", async () => {
    const { calls } = setup("location_manager", { body: categorised });
    renderApp("/cases/c-1");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Amount (₹)"), "12.345");
    await user.click(screen.getByRole("button", { name: "Propose for approval" }));
    expect(await screen.findByText(/Enter the amount in rupees/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/cases/c-1/propose")).toBe(false);
  });

  it("shows the server's reason when a choice is out of rule", async () => {
    seedSession();
    mockFetch({
      "GET /me": { body: makeMe("hq_owner") },
      "GET /cases/c-1": { body: escalated },
      "GET /cases/c-1/timeline": { body: [] },
      "GET /cases/c-1/staff-remedy-options": { body: categorised },
      "GET /orders/t-1": { status: 404, body: { detail: "not found" } },
      "POST /cases/c-1/propose": { status: 422, body: { detail: "the amount must be between ₹0.01 and ₹120.00" } },
    });
    renderApp("/cases/c-1");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Amount (₹)"), "500");
    await user.click(screen.getByRole("button", { name: "Propose for approval" }));
    expect(await screen.findByText(/must be between/)).toBeInTheDocument();
  });

  it("is hidden when the case does not need a person", async () => {
    setup("location_manager", { status: 409, body: { detail: "this case does not need a person to decide it" } });
    renderApp("/cases/c-1");
    await screen.findByText("Case details");
    await waitFor(() => expect(screen.queryByText("Decide this case")).not.toBeInTheDocument());
  });

  it("is never shown to customers", async () => {
    const { calls } = setup("customer", { body: uncategorised });
    renderApp("/cases/c-1");
    await screen.findByText("Case details");
    expect(screen.queryByText("Decide this case")).not.toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith("/staff-remedy-options"))).toBe(false);
  });
});
