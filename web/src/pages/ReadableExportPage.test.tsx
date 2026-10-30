import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReadableExport, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

const f = (label: string, value: string) => ({ label, value });

function exportBody(): ReadableExport {
  const base = { purpose: "To show what you bought.", retention: "Kept 8 years.", retention_provisional: true };
  return {
    language: "en",
    title: "Your data, in a readable form",
    generated: "Prepared on 27 Oct 2026, 14:05",
    tz_note: "Dates and times are in Indian Standard Time.",
    labels: {
      why: "Why we hold it",
      howlong: "How long we keep it",
      empty: "Nothing on record.",
      history: "Changes you made",
      print: "Print or save as PDF",
      back: "Back to Privacy & data",
    },
    provisional_label: "provisional",
    sections: [
      { key: "details", title: "Your details", ...base, records: [[f("Name", "Asha Rao")]] },
      {
        key: "orders",
        title: "Your orders",
        ...base,
        records: [[f("Order", "ORD-1001"), f("Total", "₹12,34,567.89"), f("Placed on", "27 Oct 2026, 14:05")]],
      },
      { key: "cases", title: "Your help requests", ...base, records: [] },
      { key: "remedies", title: "Refunds and vouchers", ...base, records: [] },
      { key: "choices", title: "Your choices about offers", ...base, records: [], history: [] },
      { key: "processors", title: "Companies that handle data for us", purpose: null, retention: null, retention_provisional: false, records: [[f("Name", "Neon")]] },
    ],
    contact: {
      label: "Privacy and grievance contact",
      configured: true,
      name: "Privacy desk",
      email: "privacy@example.test",
      response_target_days: 30,
      acknowledge_hours: 48,
      response_text: "We aim to reply within 30 days.",
    },
  };
}

function setup(role: Role = "customer") {
  seedSession();
  return mockFetch({
    "GET /me": { body: makeMe(role) },
    "GET /orders": { body: [] },
    "GET /me/data-export/readable": { body: exportBody() },
  });
}

describe("readable export page", () => {
  it("shows a section per data item with purpose, retention and server-formatted money and dates", async () => {
    setup();
    renderApp("/privacy/export");
    const orders = await screen.findByTestId("export-orders");
    expect(within(orders).getByText("₹12,34,567.89")).toBeInTheDocument();
    expect(within(orders).getByText("27 Oct 2026, 14:05")).toBeInTheDocument();
    expect(within(orders).getByText("To show what you bought.")).toBeInTheDocument();
    expect(within(orders).getByText("provisional")).toBeInTheDocument();
    expect(screen.getByTestId("export-cases")).toHaveTextContent("Nothing on record.");
    expect(screen.getByTestId("export-processors")).toHaveTextContent("Neon");
    expect(screen.getByTestId("export-contact")).toHaveTextContent("privacy@example.test");
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(6);
  });

  it("prints from one outline action", async () => {
    const print = vi.fn();
    vi.stubGlobal("print", print);
    setup();
    renderApp("/privacy/export");
    fireEvent.click(await screen.findByRole("button", { name: "Print or save as PDF" }));
    expect(print).toHaveBeenCalled();
  });

  it("is reachable from the Privacy page next to the JSON download", async () => {
    mockFetch({
      "GET /me": { body: makeMe("customer") },
      "GET /orders": { body: [] },
      "GET /me/data-held": { status: 500, body: { detail: "x" } },
      "GET /me/consents": { status: 500, body: { detail: "x" } },
      "GET /me/erasure-request": { body: null },
    });
    seedSession();
    renderApp("/privacy");
    expect(await screen.findByRole("button", { name: "Download my data" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open readable version" })).toHaveAttribute("href", "/privacy/export");
  });

  it("is not available to staff", async () => {
    setup("hq_owner");
    renderApp("/privacy/export");
    await waitFor(() => expect(screen.queryByTestId("export-orders")).not.toBeInTheDocument());
  });
});
