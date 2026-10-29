import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Consents, DataHeld, ErasureRequest, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

function consents(granted: boolean, withHistory = false): Consents {
  return {
    notice_version: "v1",
    consents: [{ purpose: "marketing", channel: "whatsapp", granted, updated_at: null }],
    history: [],
    benefits: {
      language: "en",
      headings: {
        title: "Offers and promotions",
        intro: "You choose whether we send you offers. Every switch starts off.",
        history: "History of your choices",
        note: "Turning offers off never changes the help you get with an order.",
        on: "On",
        off: "Off",
        notice: "Wording version",
      },
      always_on: {
        title: "Help messages",
        body: "Always on, needed to resolve your order. There is no switch for these.",
        badge: "Always on",
      },
      purposes: [
        {
          purpose: "marketing",
          channel: "whatsapp",
          granted,
          title: "Offers and vouchers",
          benefit: "Hear about offers and vouchers for your next order.",
          sent: "We send a short message about an offer or voucher.",
          cap: "At most one offer message in 30 days.",
          cap_days: 30,
          channel_label: "On WhatsApp",
          switch_label: "Send me offers and vouchers",
          state_label: granted ? "On" : "Off",
        },
      ],
      history_labelled: withHistory
        ? [
            {
              purpose: "marketing",
              channel: "whatsapp",
              granted: false,
              source: "customer",
              notice_version: "v1",
              at: "2026-10-27T10:00:00Z",
              purpose_label: "Offers and vouchers",
              channel_label: "On WhatsApp",
              action_label: "stopped",
            },
          ]
        : [],
    },
  };
}

const deferred: ErasureRequest = {
  id: "r-1",
  kind: "erasure",
  status: "deferred",
  reason: "A refund or payment linked to your orders is still being processed.",
  deferred_until: null,
  requested_at: "2026-10-27T10:00:00Z",
  completed_at: null,
};

function held(notKept: string[] = []): DataHeld {
  return {
    language: "en",
    headings: {
      title: "What we hold about you",
      item: "Item",
      yours: "What we hold",
      purpose: "Why",
      keep: "How long",
      use: "Used for",
      processors: "Who else sees it",
      not_kept: "What we do not keep",
      contact: "Questions about your data",
    },
    items: [
      {
        key: "orders",
        label: "Your orders",
        purpose: "To show what you bought.",
        use: "help",
        use_label: "Help with your orders",
        retention: "Kept 7 years, as business records.",
        retention_provisional: true,
        value: null,
        count: 3,
        summary: "3 on record",
      },
    ],
    processors: [{ name: "Neon", role: "database host", data: "all stored records" }],
    not_kept: notKept,
    provisional_label: "provisional",
    contact: {
      label: "Privacy contact",
      configured: true,
      name: "Privacy desk",
      email: "privacy@example.test",
      response_target_days: 30,
      legal_ceiling_days: 90,
      response_text: "We aim to reply within 30 days. The legal limit is 90 days.",
    },
  };
}

function setup(role: Role = "customer", erasure: ErasureRequest | null = null, notKept: string[] = []) {
  seedSession();
  return mockFetch({
    "GET /me/data-held": { body: held(notKept) },
    "GET /me": { body: makeMe(role) },
    "GET /orders": { body: [] },
    "GET /me/consents": { body: consents(false) },
    "POST /me/consents/marketing": (call) => ({ body: consents((call.body as { granted: boolean }).granted) }),
    "GET /me/data-export": { body: { profile: { name: "A" }, processors: [] } },
    "GET /me/erasure-request": { body: erasure },
    "POST /me/erasure-request": { status: 201, body: deferred },
  });
}

describe("privacy page", () => {
  it("lets a customer turn marketing on and off", async () => {
    const { calls } = setup();
    renderApp("/privacy");
    const toggle = await screen.findByRole("switch", { name: /Send me offers and vouchers/ });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("switch")).toBeChecked());
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(screen.getByRole("switch")).not.toBeChecked());
    const posts = calls.filter((c) => c.method === "POST").map((c) => c.body);
    expect(posts).toEqual([{ granted: true }, { granted: false }]);
  });

  it("explains each choice as a benefit with its cap, and shows help as always on without a switch", async () => {
    setup();
    renderApp("/privacy");
    const row = await screen.findByTestId("consent-marketing");
    expect(row).toHaveTextContent("Hear about offers and vouchers");
    expect(row).toHaveTextContent("At most one offer message in 30 days.");
    expect(row).toHaveTextContent("On WhatsApp");
    expect(screen.getByRole("switch")).not.toBeChecked(); // off by default
    expect(screen.getAllByRole("switch")).toHaveLength(1); // help has none
    const help = screen.getByTestId("consent-always-on");
    expect(help).toHaveTextContent("Always on");
    expect(help.querySelector("[role=switch],input")).toBeNull();
    expect(screen.getByTestId("consent-note")).toHaveTextContent("never changes the help");
  });

  it("withdraws in one click and keeps the history visible with the wording version", async () => {
    seedSession();
    const { calls } = mockFetch({
      "GET /me/data-held": { body: held() },
      "GET /me": { body: makeMe("customer") },
      "GET /orders": { body: [] },
      "GET /me/consents": { body: consents(true, true) },
      "POST /me/consents/marketing": { body: consents(false, true) },
      "GET /me/erasure-request": { body: null },
    });
    renderApp("/privacy");
    const toggle = await screen.findByRole("switch", { name: /Send me offers and vouchers/ });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("switch")).not.toBeChecked());
    expect(calls.filter((c) => c.method === "POST").map((c) => c.body)).toEqual([{ granted: false }]);
    expect(screen.getByTestId("consent-history")).toHaveTextContent("stopped Offers and vouchers On WhatsApp");
    expect(screen.getByTestId("consent-history")).toHaveTextContent("Wording version: v1");
  });

  it("downloads the data", async () => {
    const create = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
    const { calls } = setup();
    renderApp("/privacy");
    fireEvent.click(await screen.findByRole("button", { name: "Download my data" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(calls.some((c) => c.path === "/me/data-export")).toBe(true);
  });

  it("files an erasure request and shows the deferred status with its reason", async () => {
    const { calls } = setup();
    renderApp("/privacy");
    fireEvent.click(await screen.findByRole("button", { name: "Request erasure" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/me/erasure-request")).toBe(true));
  });

  it("shows an existing deferred request with the reason and no second button", async () => {
    setup("customer", deferred);
    renderApp("/privacy");
    const status = await screen.findByTestId("erasure-status");
    expect(status).toHaveTextContent("Deferred");
    expect(status).toHaveTextContent("still being processed");
    expect(screen.queryByRole("button", { name: "Request erasure" })).not.toBeInTheDocument();
  });

  it("shows what we hold with purpose, retention, count, processors and the contact twice", async () => {
    setup();
    renderApp("/privacy");
    const row = await screen.findByTestId("held-orders");
    expect(row).toHaveTextContent("3 on record");
    expect(row).toHaveTextContent("Kept 7 years");
    expect(row).toHaveTextContent("provisional");
    expect(screen.getByTestId("held-processors")).toHaveTextContent("Neon");
    const contacts = screen.getAllByTestId("privacy-contact");
    expect(contacts).toHaveLength(2);
    expect(contacts[0]).toHaveTextContent("Privacy contact: Privacy desk, privacy@example.test");
    expect(contacts[0]).toHaveTextContent("90 days");
  });

  it("hides the what-we-do-not-keep line unless the server sends a backed claim", async () => {
    setup();
    const first = renderApp("/privacy");
    await screen.findByTestId("held-orders");
    expect(screen.queryByTestId("held-not-kept")).not.toBeInTheDocument();
    first.unmount();
    setup("customer", null, ["We do not keep your card numbers."]);
    renderApp("/privacy");
    expect(await screen.findByTestId("held-not-kept")).toHaveTextContent("card numbers");
  });

  it("is not available to staff", async () => {
    const { calls } = setup("hq_owner");
    renderApp("/privacy");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith("/me/"))).toBe(false);
  });
});
