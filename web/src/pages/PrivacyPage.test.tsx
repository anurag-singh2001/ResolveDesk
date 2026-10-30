import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Consents, DataHeld, ErasureInfo, ErasureRequest, Role } from "../api/types";
import { makeMe, mockFetch, renderApp, seedSession } from "../test/utils";

function consents(granted: boolean): Consents {
  return {
    notice_version: "v1",
    consents: [{ purpose: "marketing", channel: "whatsapp", granted, updated_at: null }],
    history: [],
  };
}

const contactLine = {
  label: "Privacy contact",
  configured: true,
  name: "Privacy desk",
  email: "privacy@example.test",
  response_target_days: 30,
  legal_ceiling_days: 90,
  response_text: "We aim to reply within 30 days. The legal limit is 90 days.",
};

const deferred: ErasureRequest = {
  id: "r-1",
  kind: "erasure",
  status: "deferred",
  stage: "deferred",
  stage_label: "Could not complete yet",
  stage_text: "Nothing has been erased. Reason: A refund or payment linked to your orders is still being processed.",
  reason_code: "in_flight",
  reason: "A refund or payment linked to your orders is still being processed.",
  deferred_until: null,
  received_at: "2026-10-27T10:00:00Z",
  received_text: "Received on 27 Oct 2026",
  expected_by: "2026-11-26T10:00:00Z",
  legal_ceiling_by: "2027-01-25T10:00:00Z",
  expected_text: "We aim to finish by 26 Nov 2026. The legal limit is 25 Jan 2027.",
  completed_at: null,
  can_withdraw: true,
  contact: contactLine,
};

const received: ErasureRequest = {
  ...deferred,
  status: "pending_approval",
  stage: "received",
  stage_label: "Received",
  stage_text: "We have your request. Nothing has been erased yet. A member of our team will review it.",
  reason_code: null,
  reason: null,
};

const withdrawn: ErasureRequest = {
  ...received,
  status: "withdrawn",
  stage: "withdrawn",
  stage_label: "Withdrawn",
  stage_text: "You withdrew this request. Nothing was erased.",
  expected_by: null,
  legal_ceiling_by: null,
  expected_text: null,
  can_withdraw: false,
};

const done: ErasureRequest = {
  ...withdrawn,
  status: "completed",
  stage: "done",
  stage_label: "Done",
  stage_text: "Your data was erased on 28 Oct 2026.",
  completed_at: "2026-10-28T10:00:00Z",
};

const erasureInfo: ErasureInfo = {
  language: "en",
  title: "Erase my data",
  intro: "Erasing removes your personal details from our records. Some records have to stay.",
  headings: { remove: "We will remove", keep: "We will keep", wait: "We may wait" },
  remove: ["Your name", "Your phone number and email", "The text of your support messages"],
  keep: [
    {
      key: "records",
      label: "Orders, payments and refunds",
      reason: "Kept 7 years, for our accounts and to show what was paid.",
      provisional: true,
    },
    { key: "audit", label: "A log of actions taken", reason: "It holds codes and ids, not your name.", provisional: false },
  ],
  wait: ["A member of our team approves each request first.", "You have a case that is still being handled."],
  provisional_label: "provisional",
  timing: "We aim to reply within 30 days. The legal limit is 90 days.",
  target_days: 30,
  legal_ceiling_days: 90,
  contact: contactLine,
  buttons: { request: "Request erasure", confirm: "Yes, request erasure", back: "Cancel", withdraw: "Withdraw my request" },
  confirm: { title: "Ask us to erase your data?", body: "Once it is done it cannot be undone." },
  status_title: "Your erasure request",
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
    "GET /me/erasure-info": { body: erasureInfo },
    "GET /me/erasure-request": { body: erasure },
    "POST /me/erasure-request": { status: 201, body: received },
    "POST /me/erasure-request/cancel": { body: withdrawn },
  });
}

describe("privacy page", () => {
  it("lets a customer turn marketing on and off", async () => {
    const { calls } = setup();
    renderApp("/privacy");
    const toggle = await screen.findByRole("switch", { name: /Marketing messages on WhatsApp/ });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("switch")).toBeChecked());
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(screen.getByRole("switch")).not.toBeChecked());
    const posts = calls.filter((c) => c.method === "POST").map((c) => c.body);
    expect(posts).toEqual([{ granted: true }, { granted: false }]);
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

  it("explains what is removed, kept and may wait before the button, with a reason per kept item", async () => {
    setup();
    renderApp("/privacy");
    expect(await screen.findByTestId("erase-remove")).toHaveTextContent("Your name");
    expect(screen.getByTestId("erase-keep")).toHaveTextContent("Kept 7 years");
    expect(screen.getByTestId("erase-keep")).toHaveTextContent("provisional");
    expect(screen.getByTestId("erase-wait")).toHaveTextContent("case that is still being handled");
    expect(screen.getByTestId("erase-timing")).toHaveTextContent("30 days");
    expect(screen.getByTestId("erase-timing")).toHaveTextContent("90 days");
  });

  it("needs a confirm step with Cancel focused first, and sends nothing until confirmed", async () => {
    const { calls } = setup();
    renderApp("/privacy");
    fireEvent.click(await screen.findByRole("button", { name: "Request erasure" }));
    const dialog = await screen.findByTestId("erase-confirm");
    expect(dialog).toHaveTextContent("cannot be undone");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("erase-confirm")).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Request erasure" }));
    fireEvent.click(await screen.findByRole("button", { name: "Yes, request erasure" }));
    const status = await screen.findByTestId("erasure-status");
    expect(status).toHaveTextContent("Received");
    expect(status).toHaveTextContent("Nothing has been erased yet");
    expect(status).toHaveTextContent("We aim to finish by 26 Nov 2026");
    expect(status).toHaveTextContent("privacy@example.test");
    expect(calls.filter((c) => c.method === "POST" && c.path === "/me/erasure-request")).toHaveLength(1);
  });

  it("shows a request that could not complete with its reason, never as done, and can be withdrawn", async () => {
    const { calls } = setup("customer", deferred);
    renderApp("/privacy");
    const status = await screen.findByTestId("erasure-status");
    expect(status).toHaveTextContent("Could not complete yet");
    expect(status).toHaveTextContent("still being processed");
    expect(status).not.toHaveTextContent("Done");
    expect(screen.queryByRole("button", { name: "Request erasure" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw my request" }));
    await waitFor(() => expect(screen.getByTestId("erasure-status")).toHaveTextContent("Withdrawn"));
    expect(calls.some((c) => c.method === "POST" && c.path === "/me/erasure-request/cancel")).toBe(true);
    expect(screen.getByRole("button", { name: "Request erasure" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Withdraw my request" })).not.toBeInTheDocument();
  });

  it("shows done only for a request the server says is done, with no promised dates", async () => {
    setup("customer", done);
    renderApp("/privacy");
    const status = await screen.findByTestId("erasure-status");
    expect(status).toHaveTextContent("Done");
    expect(status).not.toHaveTextContent("We aim to finish by");
    expect(screen.queryByRole("button", { name: "Withdraw my request" })).not.toBeInTheDocument();
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
