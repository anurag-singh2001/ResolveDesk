import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const order = {
  id: "o-1",
  external_ref: "O-1",
  brand_id: null,
  location_id: null,
  placed_at: "2026-10-25T10:00:00Z",
  total_paise: 40000,
  status: "delivered",
  items: [],
  promised_at: null,
  completed_at: null,
};
const two = {
  choice_required: true,
  options: [
    { code: "voucher", kind: "voucher", title: "Voucher", summary: "A voucher worth ₹150.00 for a future order.", amount_paise: 15000, approval: "instant", timing: "Usually instant." },
    { code: "refund_50pct", kind: "refund", title: "Refund", summary: "₹200.00 back to your original payment method.", amount_paise: 20000, approval: "team", timing: "After a team member approves it." },
  ],
};

function setup(optionsBody: unknown) {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe("customer") },
    "GET /orders/o-1": { body: order },
    "GET /meta/categories": { body: { categories: ["wrong_item", "missing_items"], free_text: false } },
    "GET /orders/o-1/remedy-options": { body: optionsBody },
    "POST /cases": { body: { id: "c-9", stage: "received" } },
    "GET /cases/c-9": { status: 404 },
  });
}

describe("remedy choice on the report form", () => {
  it("shows the server's options with amount and timing and sends the pick", async () => {
    const { calls } = setup(two);
    renderApp("/orders/o-1/report");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("What went wrong?"), "wrong_item");
    expect(await screen.findByText("A voucher worth ₹150.00 for a future order.")).toBeInTheDocument();
    expect(screen.getByText("Usually instant.")).toBeInTheDocument();
    expect(screen.getByText("After a team member approves it.")).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Refund/));
    await user.type(screen.getByLabelText(/Tell us what happened/), "Wrong dish");
    await user.click(screen.getByRole("button", { name: "Submit report" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/cases");
    expect(post?.body).toMatchObject({ category: "wrong_item", remedy_choice: "refund_50pct" });
  });

  it("shows no choice for a single option and sends none", async () => {
    const { calls } = setup({ choice_required: false, options: [two.options[0]] });
    renderApp("/orders/o-1/report");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("What went wrong?"), "missing_items");
    await user.type(screen.getByLabelText(/Tell us what happened/), "Item missing");
    expect(screen.queryByText("How would you like this settled?")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Submit report" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/cases");
    expect((post?.body as { remedy_choice: unknown }).remedy_choice).toBeNull();
  });
});
